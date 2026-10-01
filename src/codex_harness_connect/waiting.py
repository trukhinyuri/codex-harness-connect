"""Bounded observation of durable jobs without acknowledging or controlling them."""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from .sessions import TERMINAL

MAX_WAIT_BYTES = 64 * 1024
_ACTIVE = frozenset({"starting", "running", "cancelling", "stopping"})
_SEMANTIC = frozenset({"unknown", "succeeded", "failed"})


class WaitTarget(BaseModel):
    """A local job ID and the last cursor actually drained by this reader."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: StrictStr
    after: StrictInt = Field(default=0, ge=0, le=2**63 - 1)

    @field_validator("session_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError("session_id must be exactly 32 lowercase hexadecimal characters")
        return value


def _text(value: str, byte_limit: int = 128) -> str:
    # Slice before encoding to keep an unexpectedly noisy callback bounded too.
    return value[:byte_limit].encode("utf-8", errors="replace")[:byte_limit].decode(
        "utf-8", errors="ignore")


def _cursor(value: Any) -> bool:
    return type(value) is int and 0 <= value < 2**63


def _base(target: WaitTarget) -> dict:
    return {"session_id": target.session_id, "after": target.after,
            "next_cursor": target.after, "first_pending_cursor": None,
            "changes_available": False, "truncated": False}


def _error(target: WaitTarget, code: str, message: str) -> dict:
    return {**_base(target), "status": "unknown", "terminal": False,
            "semantic_status": "unknown", "task_acceptance": "requires-parent-verification",
            "error": {"code": code, "message": _text(message)}}


def _summary(target: WaitTarget, result: Any) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("session"), dict):
        raise ValueError("Status reader must return a session object")
    session = result["session"]
    if session.get("session_id") != target.session_id:
        raise ValueError("Status reader returned a different session ID")
    status = session.get("status")
    if not isinstance(status, str):
        raise ValueError("Status reader returned no string status")
    events = result.get("events")
    if not isinstance(events, list) or len(events) > 1:
        raise ValueError("Status reader must return at most one event")
    truncated = result.get("truncated")
    if type(truncated) is not bool:
        raise ValueError("Status reader returned an invalid retention flag")
    earliest = result.get("earliest_cursor")
    if earliest is not None and not _cursor(earliest):
        raise ValueError("Status reader returned an invalid earliest cursor")
    pending = None
    if events:
        event = events[0]
        if not isinstance(event, dict) or not _cursor(event.get("cursor")):
            raise ValueError("Status reader returned an invalid event cursor")
        pending = event["cursor"]
        if pending <= target.after:
            raise ValueError("Status reader returned an already acknowledged event")
        if event.get("session_id", target.session_id) != target.session_id:
            raise ValueError("Status reader returned an event for a different session")
    next_cursor = result.get("next_cursor")
    if (type(next_cursor) is not int
            or (next_cursor != (pending if pending is not None else target.after)
                and not (pending is None and truncated and next_cursor > target.after))):
        raise ValueError("Status reader returned an inconsistent next cursor")
    known = status in _ACTIVE or status in TERMINAL
    semantic = session.get("semantic_status")
    summary = {**_base(target), "status": status if known else "unknown",
               "terminal": status in TERMINAL, "status_known": known,
               "semantic_status": semantic if semantic in _SEMANTIC else "unknown",
               "task_acceptance": "requires-parent-verification",
               "first_pending_cursor": pending, "changes_available": pending is not None,
               "earliest_cursor": earliest, "truncated": truncated}
    if not known:
        summary["observed_status"] = _text(status)
    summary["summary_truncated"] = not known and summary["observed_status"] != status
    # Native conversation identity and OS process identity remain distinct.
    for key in ("native_session_id", "worker_start", "child_start", "termination_scope"):
        value = session.get(key)
        if value is None or isinstance(value, str):
            summary[key] = _text(value) if value is not None else None
            if summary[key] != value:
                summary["summary_truncated"] = True
    for key in ("worker_pid", "child_pid", "process_group", "exit_code", "exit_signal"):
        value = session.get(key)
        if value is None or (type(value) is int and -(2**63) <= value < 2**63):
            summary[key] = value
    for key in ("worker_alive", "heartbeat_fresh", "live", "full_process_containment_verified"):
        value = session.get(key)
        if type(value) is bool:
            summary[key] = value
    error = session.get("error")
    if isinstance(error, str) and error:
        # A native/worker error can contain project text or stderr. Its details belong
        # in explicit transcript reads, not compact observation responses.
        summary["session_error_present"] = True
    return summary


async def _read(target: WaitTarget, read_status: Callable) -> dict:
    try:
        if inspect.iscoroutinefunction(read_status):
            result = await read_status(target.session_id, target.after, 1)
        else:
            result = await asyncio.to_thread(read_status, target.session_id, target.after, 1)
            if inspect.isawaitable(result):
                result = await result
        return _summary(target, result)
    except (KeyError, PermissionError):
        # Do not expose another profile's existence or callback exception payload.
        return _error(target, "unavailable", "Session is unavailable in the selected scope")
    except ValueError:
        return _error(target, "invalid_status", "Status reader returned invalid data")
    except Exception as exc:
        return _error(target, "read_failed", type(exc).__name__)


def _reason(summaries: list[dict]) -> str | None:
    for reason, predicate in (
        ("error", lambda s: "error" in s),
        ("retention_gap", lambda s: s["truncated"]),
        ("changes", lambda s: s["changes_available"]),
        ("terminal", lambda s: s["terminal"]),
        ("unknown_status", lambda s: not s["status_known"]),
    ):
        if any(predicate(summary) for summary in summaries):
            return reason
    return None


def _response(reason: str, summaries: list[dict]) -> dict:
    response = {"reason": reason, "timed_out": reason == "timeout", "sessions": summaries}
    if len(json.dumps(response, ensure_ascii=True).encode("utf-8")) > MAX_WAIT_BYTES:
        raise ValueError("Wait response exceeds 64 KiB; use smaller cursor values")
    return response


async def wait_for_sessions(targets: list[WaitTarget], read_status: Callable,
                            timeout_seconds: float = 30) -> dict:
    """Wait for unread events, terminal state, retention loss or observation failure.

    Every read uses the original acknowledged cursor and limit=1. Cancelling this
    coroutine stops observation only; it does not send control to a native job.
    Synchronous readers run off the event loop. A deadline can stop waiting for a
    blocked reader, but cannot forcibly stop its already running read-only thread.
    """
    if not isinstance(targets, list) or not 1 <= len(targets) <= 8:
        raise ValueError("targets must contain between one and eight jobs")
    if any(not isinstance(target, WaitTarget) for target in targets):
        raise ValueError("targets must contain WaitTarget objects")
    if len({target.session_id for target in targets}) != len(targets):
        raise ValueError("Duplicate session IDs are not allowed")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not 0 <= timeout_seconds <= 45 or not math.isfinite(timeout_seconds)):
        raise ValueError("timeout_seconds must be finite and between zero and 45")
    if not callable(read_status):
        raise ValueError("read_status must be callable")
    # Check that even the unchanged caller cursor can be emitted within the cap.
    _response("snapshot", [_base(target) for target in targets])
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    summaries = [_error(target, "read_timeout", "Status read did not finish") for target in targets]
    interval = 0.2
    while True:
        # timeout=0 still performs a bounded immediate snapshot, not a long wait.
        read_budget = max(0, deadline - loop.time()) if timeout_seconds else 1.0
        reads = [asyncio.create_task(_read(target, read_status)) for target in targets]
        try:
            done, pending = await asyncio.wait(reads, timeout=read_budget)
            for index, task in enumerate(reads):
                if task in done:
                    summaries[index] = task.result()
                else:
                    summaries[index] = _error(targets[index], "read_timeout",
                                              "Status read did not finish")
            if pending:
                return _response("error", summaries)
        finally:
            for task in reads:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*reads, return_exceptions=True)
        reason = _reason(summaries)
        if reason:
            return _response(reason, summaries)
        if not timeout_seconds:
            return _response("snapshot", summaries)
        remaining = deadline - loop.time()
        if remaining <= 0:
            return _response("timeout", summaries)
        await asyncio.sleep(min(interval, remaining))
        if loop.time() >= deadline:
            return _response("timeout", summaries)
        interval = min(0.5, interval * 1.5)
