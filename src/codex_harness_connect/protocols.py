"""Bounded Claude Code print-mode NDJSON parsing, not a general transcript parser.

Feed only decoded stdout from a reviewed Claude pipe launch. Never feed stderr,
PTY output, tool contents or an arbitrary CLI. No parser can authenticate a
forged protocol channel; that boundary belongs to the launch/worker contract.

Schema sources checked 2026-10-01:
https://code.claude.com/docs/en/headless#stream-responses
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/message_parser.py
https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py
Fixtures/tests establish parser behavior, not live vendor compatibility.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any, Literal, TypedDict
from uuid import UUID

SemanticStatus = Literal["unknown", "succeeded", "failed"]
TaskAcceptance = Literal["requires-parent-verification"]


class DeferredToolSummary(TypedDict):
    id: str
    name: str


class RateLimitSummary(TypedDict):
    status: str
    resets_at: int | None
    rate_limit_type: str | None
    utilization: float | None
    overage_status: str | None
    overage_resets_at: int | None
    overage_disabled_reason: str | None
    metadata_truncated: bool


class ProtocolError(TypedDict):
    code: str
    message: str


class NormalizedEvent(TypedDict, total=False):
    kind: str
    type: str | None
    subtype: str | None
    code: str
    message: str
    native_session_id: str | None
    identity_verified: bool
    model: str | None
    content_types: list[str | None]
    parent_tool_use_id: str | None
    event_type: str | None
    text: str | None
    text_truncated: bool
    is_error: bool
    semantic_status: SemanticStatus
    errors: list[str | None]
    result: str | None
    result_truncated: bool
    task_acceptance: TaskAcceptance
    permission_denial_count: int
    permission_denials_truncated: bool
    deferred_tool_use: DeferredToolSummary | None
    deferred_tool_truncated: bool
    api_error_status: int | None
    rate_limit_info: RateLimitSummary


class ClaudeOutcome(TypedDict):
    protocol: str
    native_session_id: str | None
    identity_verified: bool
    semantic_status: SemanticStatus
    exit_code: int | None
    result_subtype: str | None
    is_error: bool | None
    errors: list[ProtocolError]
    errors_truncated: bool
    output_bytes: int
    final_events: list[NormalizedEvent]
    task_acceptance: TaskAcceptance
    permission_denial_count: int | None
    permission_denials_truncated: bool
    deferred_tool_use: DeferredToolSummary | None
    deferred_tool_truncated: bool
    api_error_status: int | None
    rate_limit_events: list[RateLimitSummary]
    rate_limit_events_truncated: bool


MAX_LINE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_LINES = 100_000
MAX_ERRORS = 32
MAX_PREVIEW_CHARS = 4096
MAX_DENIAL_COUNT = 1024
MAX_TOOL_IDENTIFIER_CHARS = 256
MAX_RATE_LIMIT_EVENTS = 32
MAX_TIMESTAMP = 2**53 - 1
_RATE_STATUSES = frozenset({"allowed", "allowed_warning", "rejected"})
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def _uuid(value: Any) -> str | None:
    if isinstance(value, str) and _UUID.fullmatch(value):
        return str(UUID(value))
    return None


def _bounded_text(value: Any, limit: int = 256) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:limit].encode("utf-8", "replace").decode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _no_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON number")


class ClaudeStreamParser:
    """One print-mode turn; retains framing/identity/result metadata, not text history.

    ``feed(text)`` returns bounded normalized events. ``finish(exit_code)`` also
    returns ``final_events`` for a complete last JSON object without a trailing
    newline. Bounds/errors make semantic status unknown; they do not kill or
    retry inference. Identity ambiguity clears ``native_session_id``.
    """

    def __init__(
        self,
        *,
        max_line_bytes: int = MAX_LINE_BYTES,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        max_lines: int = MAX_LINES,
    ):
        for value, ceiling in (
            (max_line_bytes, 4 * MAX_LINE_BYTES),
            (max_output_bytes, 8 * MAX_OUTPUT_BYTES),
            (max_lines, 10 * MAX_LINES),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= ceiling:
                raise ValueError("Parser limits must be positive bounded integers")
        if max_line_bytes > max_output_bytes:
            raise ValueError("Line limit cannot exceed total output limit")
        self.max_line_bytes = max_line_bytes
        self.max_output_bytes = max_output_bytes
        self.max_lines = max_lines
        self._buffer = bytearray()
        self._bytes = self._lines = self._errors_dropped = 0
        self._errors: list[ProtocolError] = []
        self._faulted = self._halted = self._identity_invalid = False
        self._init_id: str | None = None
        self._result_status: SemanticStatus = "unknown"
        self._result_subtype: str | None = None
        self._result_error: bool | None = None
        self._result_seen = False
        self._finished: ClaudeOutcome | None = None
        self._exit_code: int | None = None
        self._denial_count: int | None = None
        self._denials_truncated = self._deferred_truncated = False
        self._deferred: DeferredToolSummary | None = None
        self._api_error_status: int | None = None
        self._rate_limits: list[RateLimitSummary] = []
        self._rate_limits_truncated = False

    @property
    def native_session_id(self) -> str | None:
        return None if self._identity_invalid else self._init_id

    def _error(self, code: str, message: str) -> list[NormalizedEvent]:
        self._faulted = True
        error: ProtocolError = {"code": code, "message": message}
        if len(self._errors) >= MAX_ERRORS:
            self._errors_dropped += 1
            return []
        self._errors.append(error)
        return [{"kind": "protocol_error", **error}]

    def _stop(self, code: str, message: str) -> list[NormalizedEvent]:
        self._halted = True
        self._buffer.clear()
        return self._error(code, message)

    def feed(self, text: str) -> list[NormalizedEvent]:
        if not isinstance(text, str):
            raise TypeError("feed requires decoded stdout text")
        if self._finished is not None:
            raise RuntimeError("Parser is already finished")
        events: list[NormalizedEvent] = []
        if self._halted:
            return events
        # Bounded temporary encoding, even if a caller provides a huge string.
        for offset in range(0, len(text), 16_384):
            try:
                data = text[offset : offset + 16_384].encode("utf-8")
            except UnicodeEncodeError:
                events += self._stop("invalid_unicode", "Decoded stdout is not valid Unicode")
                break
            if self._bytes + len(data) > self.max_output_bytes:
                events += self._stop("output_limit", "Total protocol output limit exceeded")
                break
            self._bytes += len(data)
            parts = data.split(b"\n")
            for index, part in enumerate(parts):
                if len(self._buffer) + len(part) > self.max_line_bytes:
                    events += self._stop("line_limit", "Protocol line limit exceeded")
                    break
                self._buffer.extend(part)
                if index != len(parts) - 1:
                    line = bytes(self._buffer)
                    self._buffer.clear()
                    events += self._line(line)
                    if self._halted:
                        break
            if self._halted:
                break
        return events

    def _line(self, line: bytes) -> list[NormalizedEvent]:
        self._lines += 1
        if self._lines > self.max_lines:
            return self._stop("line_count_limit", "Protocol line count limit exceeded")
        if not line.strip():
            return []
        try:
            item = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_no_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            # A malformed object could have been another init with a different
            # id. The channel no longer verifies an unambiguous identity.
            self._identity_invalid = True
            return self._error("invalid_json", "Malformed, incomplete or ambiguous protocol JSON")
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            return self._error(
                "invalid_event", "Protocol event must be an object with a string type"
            )
        if self._result_seen:
            if item["type"] == "result" or (
                item["type"] == "system" and item.get("subtype") == "init"
            ):
                if _uuid(item.get("session_id")) != self._init_id:
                    self._identity_invalid = True
            return self._error(
                "event_after_result", "A print-mode event followed the terminal result"
            )
        kind = item["type"]
        if kind == "system" and item.get("subtype") == "init":
            native = _uuid(item.get("session_id"))
            if native is None:
                self._identity_invalid = True
                return self._error("invalid_init_id", "Init session id must be a canonical UUID")
            if self._init_id is not None and native != self._init_id:
                self._identity_invalid = True
                return self._error(
                    "conflicting_init_id", "Init events disagree about session identity"
                )
            self._init_id = native
            return [
                {
                    "kind": "init",
                    "native_session_id": self.native_session_id,
                    "identity_verified": self.native_session_id is not None,
                    "model": _bounded_text(item.get("model")),
                }
            ]
        if kind == "result":
            return self._result(item)
        if kind == "rate_limit_event":
            return self._rate_limit(item)
        if kind in ("assistant", "user"):
            message = item.get("message")
            if not isinstance(message, dict):
                return self._error(
                    "invalid_message", "Assistant/user event requires a message object"
                )
            content = message.get("content")
            if not isinstance(content, (str, list)):
                return self._error("invalid_content", "Message content must be text or an array")
            block_types = (
                ["text"]
                if isinstance(content, str)
                else [
                    _bounded_text(block.get("type"), 64)
                    for block in content[:32]
                    if isinstance(block, dict)
                ]
            )
            return [
                {
                    "kind": kind,
                    "content_types": block_types,
                    "parent_tool_use_id": _bounded_text(item.get("parent_tool_use_id")),
                }
            ]
        if kind == "stream_event":
            event = item.get("event")
            if not isinstance(event, dict):
                return self._error("invalid_partial", "Partial event requires an event object")
            delta = event.get("delta")
            text = delta.get("text") if isinstance(delta, dict) else None
            normalized: NormalizedEvent = {
                "kind": "partial",
                "event_type": _bounded_text(event.get("type"), 64),
                "parent_tool_use_id": _bounded_text(item.get("parent_tool_use_id")),
            }
            if isinstance(text, str):
                normalized.update(
                    text=_bounded_text(text, MAX_PREVIEW_CHARS),
                    text_truncated=len(text) > MAX_PREVIEW_CHARS,
                )
            return [normalized]
        return [
            {
                "kind": "system" if kind == "system" else "unknown",
                "type": _bounded_text(kind, 64),
                "subtype": _bounded_text(item.get("subtype"), 64),
            }
        ]

    def _result(self, item: dict) -> list[NormalizedEvent]:
        self._result_seen = True
        native = _uuid(item.get("session_id"))
        if native is None or self._init_id is None or native != self._init_id:
            self._identity_invalid = True
            return self._error(
                "unverified_result_id", "Result requires the same UUID as a valid init"
            )
        subtype, is_error = item.get("subtype"), item.get("is_error")
        if (
            not isinstance(subtype, str)
            or not subtype
            or len(subtype) > 128
            or type(is_error) is not bool
        ):
            return self._error("invalid_result", "Result requires subtype and boolean is_error")
        for field in ("duration_ms", "duration_api_ms", "num_turns"):
            value = item.get(field)
            if type(value) is not int or value < 0:
                return self._error(
                    "invalid_result", "Result is missing valid required numeric metadata"
                )
        errors = item.get("errors", [])
        if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
            return self._error("invalid_result", "Result errors must be a string array")
        if "result" in item and item["result"] is not None and not isinstance(item["result"], str):
            return self._error("invalid_result", "Result text must be a string or null")
        denials = item.get("permission_denials")
        if denials is not None and not isinstance(denials, list):
            return self._error("invalid_result", "Permission denials must be an array or null")
        deferred = item.get("deferred_tool_use")
        if deferred is not None and (
            not isinstance(deferred, dict)
            or not isinstance(deferred.get("id"), str) or not deferred["id"]
            or not isinstance(deferred.get("name"), str) or not deferred["name"]
            or not isinstance(deferred.get("input"), dict)
        ):
            return self._error("invalid_result", "Deferred tool requires string id/name and object input")
        api_status = item.get("api_error_status")
        if api_status is not None and (type(api_status) is not int or not 100 <= api_status <= 599):
            return self._error("invalid_result", "API error status must be a valid HTTP integer or null")
        if api_status is not None and not is_error:
            return self._error("invalid_result", "API error status conflicts with non-error result")
        self._denial_count = min(len(denials or []), MAX_DENIAL_COUNT)
        self._denials_truncated = len(denials or []) > MAX_DENIAL_COUNT
        if deferred is not None:
            self._deferred = {"id": _bounded_text(deferred["id"], MAX_TOOL_IDENTIFIER_CHARS),
                              "name": _bounded_text(deferred["name"], MAX_TOOL_IDENTIFIER_CHARS)}
            self._deferred_truncated = any(len(deferred[key]) > MAX_TOOL_IDENTIFIER_CHARS
                                           for key in ("id", "name"))
        self._api_error_status = api_status
        self._result_subtype, self._result_error = subtype, is_error
        if is_error:
            self._result_status = "failed"
        elif subtype == "success" and not errors:
            self._result_status = "succeeded"
        else:
            return self._error("unrecognized_result", "Non-error result does not establish success")
        terminal_reason = item.get("terminal_reason")
        if terminal_reason not in (None, "completed"):
            self._result_status = (
                "failed"
                if terminal_reason in ("aborted_streaming", "aborted_tools", "max_turns")
                else "unknown"
            )
        normalized: NormalizedEvent = {
            "kind": "result",
            "native_session_id": self.native_session_id,
            "identity_verified": self.native_session_id is not None,
            "subtype": subtype,
            "is_error": is_error,
            "semantic_status": "unknown" if self._faulted else self._result_status,
            "errors": [_bounded_text(error, 512) for error in errors[:MAX_ERRORS]],
            "task_acceptance": "requires-parent-verification",
            "permission_denial_count": self._denial_count,
            "permission_denials_truncated": self._denials_truncated,
            "deferred_tool_use": copy.deepcopy(self._deferred),
            "deferred_tool_truncated": self._deferred_truncated,
            "api_error_status": self._api_error_status,
        }
        if isinstance(item.get("result"), str):
            normalized.update(
                result=_bounded_text(item["result"], MAX_PREVIEW_CHARS),
                result_truncated=len(item["result"]) > MAX_PREVIEW_CHARS,
            )
        return [normalized]

    def _rate_limit(self, item: dict) -> list[NormalizedEvent]:
        # SDK wire discriminant is rate_limit_event; info keys are camelCase.
        # Rate events never establish or change the resumable session identity.
        info = item.get("rate_limit_info")
        if (not isinstance(info, dict) or not isinstance(info.get("status"), str)
                or info["status"] not in _RATE_STATUSES
                or _uuid(item.get("uuid")) is None or _uuid(item.get("session_id")) is None):
            return self._error("invalid_rate_limit", "Rate limit event requires typed metadata and UUIDs")
        if self._init_id is not None and _uuid(item["session_id"]) != self._init_id:
            return self._error("invalid_rate_limit", "Rate limit session does not match the verified init")
        for key in ("resetsAt", "overageResetsAt"):
            value = info.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= MAX_TIMESTAMP):
                return self._error("invalid_rate_limit", "Rate limit reset must be a bounded Unix integer")
        utilization = info.get("utilization")
        if utilization is not None and (type(utilization) not in (int, float)
                or not 0 <= utilization <= 1 or not math.isfinite(utilization)):
            return self._error("invalid_rate_limit", "Rate limit utilization must be a finite fraction")
        if info.get("overageStatus") is not None and (
                not isinstance(info["overageStatus"], str) or info["overageStatus"] not in _RATE_STATUSES):
            return self._error("invalid_rate_limit", "Unknown overage status")
        for key in ("rateLimitType", "overageDisabledReason"):
            if info.get(key) is not None and not isinstance(info[key], str):
                return self._error("invalid_rate_limit", "Rate limit labels must be text or null")
        summary: RateLimitSummary = {
            "status": info["status"], "resets_at": info.get("resetsAt"),
            "rate_limit_type": _bounded_text(info.get("rateLimitType"), 64),
            "utilization": float(utilization) if utilization is not None else None,
            "overage_status": info.get("overageStatus"),
            "overage_resets_at": info.get("overageResetsAt"),
            "overage_disabled_reason": _bounded_text(info.get("overageDisabledReason")),
            "metadata_truncated": any(isinstance(info.get(key), str) and len(info[key]) > limit
                                      for key, limit in (("rateLimitType", 64),
                                                         ("overageDisabledReason", 256))),
        }
        self._rate_limits.append(copy.deepcopy(summary))
        if len(self._rate_limits) > MAX_RATE_LIMIT_EVENTS:
            del self._rate_limits[0]
            self._rate_limits_truncated = True
        return [{"kind": "rate_limit", "rate_limit_info": summary,
                 "task_acceptance": "requires-parent-verification"}]

    def finish(self, exit_code: int | None) -> ClaudeOutcome:
        if exit_code is not None and type(exit_code) is not int:
            raise TypeError("exit_code must be an integer or unknown")
        if self._finished is not None:
            if exit_code != self._exit_code:
                raise ValueError("Cannot change the observed exit code after finish")
            return copy.deepcopy(self._finished)
        final_events: list[NormalizedEvent] = []
        if self._buffer and not self._halted:
            final_events = self._line(bytes(self._buffer))
        self._buffer.clear()
        if not self._result_seen:
            final_events += self._error(
                "missing_result", "No terminal protocol result was received"
            )
        if self._init_id is None:
            final_events += self._error("missing_init", "No verified init event was received")
        status: SemanticStatus = "unknown"
        if not self._faulted and exit_code is not None:
            status = "failed" if exit_code != 0 else self._result_status
        self._exit_code = exit_code
        self._finished = {
            "protocol": "claude-print-stream-json/v1",
            "native_session_id": self.native_session_id,
            "identity_verified": self.native_session_id is not None,
            "semantic_status": status,
            "exit_code": exit_code,
            "result_subtype": self._result_subtype,
            "is_error": self._result_error,
            "errors": self._errors.copy(),
            "errors_truncated": self._errors_dropped > 0,
            "output_bytes": self._bytes,
            "final_events": final_events,
            "task_acceptance": "requires-parent-verification",
            "permission_denial_count": self._denial_count,
            "permission_denials_truncated": self._denials_truncated,
            "deferred_tool_use": copy.deepcopy(self._deferred),
            "deferred_tool_truncated": self._deferred_truncated,
            "api_error_status": self._api_error_status,
            "rate_limit_events": copy.deepcopy(self._rate_limits),
            "rate_limit_events_truncated": self._rate_limits_truncated,
        }
        return copy.deepcopy(self._finished)
