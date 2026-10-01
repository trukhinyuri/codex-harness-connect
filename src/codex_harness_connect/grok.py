"""Prepared Grok Build 1.0.44 contract; subscription-route launches stay gated.

This module never invokes Grok, reads credentials, or changes native configuration.
Wire provenance and the remaining preflight gap are in docs/grok-prepared-contract.md.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import PurePath
from typing import Literal, NoReturn, TypedDict
from uuid import UUID

SUPPORTED_VERSION = "1.0.44"
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_PREVIEW_CHARS = 4096
MAX_JSON_DEPTH = 64
MAX_JSON_CONTAINERS = 100_000
MAX_ERRORS = 8
_CHUNK_CHARS = 16 * 1024
Mode = Literal["batch", "interactive"]
SemanticStatus = Literal["unknown", "succeeded", "failed"]
STOP_REASONS = frozenset(
    {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}
)
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class GrokResult(TypedDict):
    protocol: Literal["grok-json"]
    native_session_id: str | None
    identity_verified: bool
    semantic_status: SemanticStatus
    stop_reason: str | None
    request_id: str | None
    exit_code: int
    text_preview: str | None
    message_preview: str | None
    structured_output_error_preview: str | None
    output_bytes: int
    errors: list[str]


def _session_uuid(value: str, name: str) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ValueError(f"{name} must be a UUID session ID")
    return str(UUID(value))


def build_grok_argv(
    executable: str,
    prompt: str,
    mode: Mode,
    *,
    subscription_entitlement_confirmed: bool,
    native_session_id: str | None = None,
    new_session_id: str | None = None,
    max_turns: int | None = None,
    installed_version: str = SUPPORTED_VERSION,
) -> list[str]:
    """Build reviewable arguments, not authorization to execute them.

    A new session needs a caller-owned UUID so its final JSON can be checked against
    that identity. Resume uses --resume; --session-id is exclusively new-session.
    There is intentionally no free-form flag, model, provider, auth, or env surface.
    """
    if subscription_entitlement_confirmed is not True:
        raise PermissionError("Explicit included-subscription entitlement acknowledgement required")
    if installed_version != SUPPORTED_VERSION:
        raise ValueError("Grok version must be reviewed before constructing launch arguments")
    if (
        not isinstance(executable, str)
        or not PurePath(executable).is_absolute()
        or len(executable) > 4096
        or "\x00" in executable
    ):
        raise ValueError("executable must be an absolute native binary path")
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 100_000 or "\x00" in prompt:
        raise ValueError("prompt must contain 1..100000 characters and no NUL")
    if mode not in ("batch", "interactive"):
        raise ValueError("mode must be batch or interactive")
    if (native_session_id is None) == (new_session_id is None):
        raise ValueError("Specify exactly one new_session_id or native_session_id")
    if max_turns is not None and (type(max_turns) is not int or not 1 <= max_turns <= 10_000):
        raise ValueError("max_turns must be an integer in 1..10000")

    argv = [executable]
    if native_session_id is not None:
        argv.append(f"--resume={_session_uuid(native_session_id, 'native_session_id')}")
    else:
        argv.append(f"--session-id={_session_uuid(new_session_id, 'new_session_id')}")
    if max_turns is not None:
        argv.append(f"--max-turns={max_turns}")
    if mode == "batch":
        argv.extend(["--output-format=json", f"--single={prompt}"])
    else:
        # Prevent a prompt that resembles a subcommand or flag being parsed as one.
        argv.extend(["--", prompt])
    return argv


def require_grok_subscription_route(
    *, subscription_entitlement_confirmed: bool, api_key_auth_disabled: bool | None = None
) -> NoReturn:
    """Fail closed until a native preflight can prove the effective inference route.

    inspect.loginPolicy covers first-party API auth only. Even True does not prove
    the effective model has no BYOK endpoint, nor bind an entitlement to a live
    cached session. A boolean acknowledgement must never unlock paid fallback.
    """
    if subscription_entitlement_confirmed is not True:
        raise PermissionError("Explicit included-subscription entitlement acknowledgement required")
    if api_key_auth_disabled is not None and type(api_key_auth_disabled) is not bool:
        raise ValueError("api_key_auth_disabled must be a native boolean or None")
    first_party = (
        "Native login policy permits first-party API-key authentication; "
        if api_key_auth_disabled is False
        else ""
    )
    raise PermissionError(
        first_party
        + "Grok subscription-only route unverified: effective model/provider, session auth, "
        "and absence of API-key/BYOK fallback require native preflight evidence"
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _no_constant(value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _check_json_bounds(raw: str) -> None:
    """Bound nesting and container count before the JSON decoder allocates them."""
    depth = 0
    containers = 0
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            containers += 1
            if depth > MAX_JSON_DEPTH or containers > MAX_JSON_CONTAINERS:
                raise ValueError("JSON structure exceeds parser bounds")
        elif char in "]}":
            depth -= 1


class GrokJsonParser:
    """Consume exactly one bounded JSON object from Grok's --single JSON stdout.

    Only vendor fields are interpreted. Session identity must match the UUID used
    by the reviewed launch; arbitrary JSON keys cannot replace it. A clean native
    exit plus end_turn is success. Truncation, malformed data, unknown stop tokens,
    and conflicting identity remain unknown.
    """

    def __init__(
        self,
        expected_session_id: str,
        *,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        max_preview_chars: int = MAX_PREVIEW_CHARS,
    ) -> None:
        self.expected_session_id = _session_uuid(expected_session_id, "expected_session_id")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
            raise ValueError("max_output_bytes must be in 1..MAX_OUTPUT_BYTES")
        if type(max_preview_chars) is not int or not 0 <= max_preview_chars <= MAX_PREVIEW_CHARS:
            raise ValueError("max_preview_chars must be in 0..MAX_PREVIEW_CHARS")
        self.max_output_bytes = max_output_bytes
        self.max_preview_chars = max_preview_chars
        self._chunks: list[str] = []
        self._output_bytes = 0
        self._errors: list[str] = []
        self._faulted = False
        self._finished: GrokResult | None = None

    def _error(self, message: str) -> None:
        self._faulted = True
        if len(self._errors) < MAX_ERRORS:
            self._errors.append(message)

    def feed(self, text: str) -> None:
        if self._finished is not None:
            raise RuntimeError("Cannot feed a finished parser")
        if not isinstance(text, str):
            raise TypeError("feed requires decoded stdout text")
        if self._faulted:
            return
        try:
            size = len(text.encode("utf-8", errors="strict"))
        except UnicodeEncodeError:
            self._error("stdout contains invalid Unicode")
            self._chunks.clear()
            return
        self._output_bytes += size
        if self._output_bytes > self.max_output_bytes:
            self._error("stdout exceeds output byte limit")
            self._chunks.clear()
            return
        if self._chunks and len(self._chunks[-1]) < _CHUNK_CHARS:
            available = _CHUNK_CHARS - len(self._chunks[-1])
            self._chunks[-1] += text[:available]
            text = text[available:]
        for index in range(0, len(text), _CHUNK_CHARS):
            self._chunks.append(text[index : index + _CHUNK_CHARS])

    def _preview(self, value: str) -> str:
        value.encode("utf-8", errors="strict")
        return value[: self.max_preview_chars]

    def finish(self, exit_code: int) -> GrokResult:
        if type(exit_code) is not int:
            raise ValueError("exit_code must be an integer")
        if self._finished is not None:
            if self._finished["exit_code"] != exit_code:
                raise RuntimeError("Cannot change a finished parser's exit code")
            return copy.deepcopy(self._finished)
        result: GrokResult = {
            "protocol": "grok-json",
            "native_session_id": None,
            "identity_verified": False,
            "semantic_status": "unknown",
            "stop_reason": None,
            "request_id": None,
            "exit_code": exit_code,
            "text_preview": None,
            "message_preview": None,
            "structured_output_error_preview": None,
            "output_bytes": self._output_bytes,
            "errors": [],
        }
        raw = "".join(self._chunks)
        self._chunks.clear()
        if not self._faulted:
            try:
                _check_json_bounds(raw)
                value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
                if not isinstance(value, dict):
                    raise ValueError("final output must be one JSON object")
                self._interpret(value, result)
            except (ValueError, RecursionError, OverflowError):
                # Do not include parser exception text: it may contain native output.
                self._error("final output does not satisfy the Grok JSON contract")
        if self._faulted:
            result["native_session_id"] = None
            result["identity_verified"] = False
            result["semantic_status"] = "unknown"
        elif exit_code != 0:
            result["semantic_status"] = "failed"
        result["errors"] = list(self._errors)
        self._finished = result
        return copy.deepcopy(result)

    def _interpret(self, value: dict[str, object], result: GrokResult) -> None:
        if value.get("type") == "error":
            if any(key in value for key in ("sessionId", "stopReason", "text", "requestId")):
                raise ValueError("mixed terminal result and error")
            message = value.get("message")
            if not isinstance(message, str):
                raise ValueError("error message must be a string")
            result["message_preview"] = self._preview(message)
            result["semantic_status"] = "failed"
            return
        if "type" in value:
            raise ValueError("unknown terminal output type")
        text = value.get("text")
        stop_reason = value.get("stopReason")
        request_id = value.get("requestId")
        session_id = _session_uuid(value.get("sessionId"), "sessionId")
        if session_id != self.expected_session_id:
            raise ValueError("session identity mismatch")
        if not isinstance(text, str) or not isinstance(stop_reason, str) or stop_reason not in STOP_REASONS:
            raise ValueError("invalid text or stop reason")
        if (
            not isinstance(request_id, str)
            or len(request_id) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in request_id)
        ):
            raise ValueError("requestId must be a bounded string; empty is valid")
        request_id.encode("utf-8", errors="strict")
        if "thought" in value and not isinstance(value["thought"], str):
            raise ValueError("thought must be a string when present")
        structured_error = value.get("structuredOutputError")
        if "structuredOutputError" in value and not isinstance(structured_error, str):
            raise ValueError("structuredOutputError must be a string when present")
        result["native_session_id"] = session_id
        result["identity_verified"] = True
        result["stop_reason"] = stop_reason
        result["request_id"] = request_id
        result["text_preview"] = self._preview(text)
        if isinstance(structured_error, str):
            result["structured_output_error_preview"] = self._preview(structured_error)
        result["semantic_status"] = (
            "succeeded" if stop_reason == "end_turn" and structured_error is None else "failed"
        )
