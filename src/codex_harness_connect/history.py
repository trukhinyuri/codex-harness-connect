"""Bounded connector history pages, ordered by adapter then newest job."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping

MAX_HISTORY_ITEMS = 50
MAX_HISTORY_BYTES = 64 * 1024
HISTORY_ORDER = "adapter ascending; created_at and session_id descending within adapter"
_CURSOR = re.compile(r"([a-z][a-z0-9-]{0,31}):([0-9a-f]{32})\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_SUMMARY_FIELDS = frozenset({
    "session_id", "request_id", "status", "mode", "created_at", "started_at", "finished_at",
    "native_session_id", "semantic_status", "worker_alive", "live", "exit_code", "exit_signal",
    "history_truncated", "event_count", "event_bytes", "has_native_outcome",
    "full_process_containment_verified", "task_acceptance",
})


def _response(sessions: list[dict], more: bool) -> dict:
    last = sessions[-1] if sessions else None
    return {"sessions": sessions,
            "next_cursor": f"{last['adapter']}:{last['session_id']}" if more and last else None,
            "has_more": more, "order": HISTORY_ORDER}


def _size(response: dict) -> int:
    # FastMCP pretty-prints text content with indent=2. ASCII escaping is a
    # conservative bound for that UTF-8 serializer; include all response fields.
    return len(json.dumps(response, allow_nan=False, indent=2).encode("utf-8"))


def list_history(pools: Mapping, *, adapter: str | None = None, limit: int = 20,
                 cursor: str | None = None) -> dict:
    """Page without consuming jobs or events; a cursor names the last emitted job.

    Adapters sort lexically; each pool's page sorts newest first. A continuation
    from an exhausted pool still visits every later pool. Existing cursors are
    verified by the owning pool, even when the pool has no following jobs.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_ITEMS:
        raise ValueError("History limit must be an integer between 1 and 50")
    if adapter is not None and (not isinstance(adapter, str) or adapter not in pools):
        raise ValueError("Adapter is absent from this plugin's harness scope")
    names = sorted(pools) if adapter is None else [adapter]
    before = None
    if cursor is not None:
        match = _CURSOR.fullmatch(cursor) if isinstance(cursor, str) and len(cursor) <= 65 else None
        if match is None:
            raise ValueError("Invalid history cursor")
        name, before = match.groups()
        if name not in names:
            raise ValueError("History cursor is outside the selected harness scope")
        names = names[names.index(name):]

    sessions = []
    for name in names:
        remaining = limit - len(sessions)
        try:
            page = pools[name].list_page(limit=max(1, remaining), before_session_id=before)
            jobs = page["sessions"]
            if not isinstance(jobs, list) or len(jobs) > max(1, remaining):
                raise ValueError("Invalid history page")
            for job in jobs:
                sid = job.get("session_id")
                if not isinstance(sid, str) or _ID.fullmatch(sid) is None:
                    raise ValueError("Invalid history job")
                summary = {key: value for key, value in job.items() if key in _SUMMARY_FIELDS}
                summary["adapter"] = name
                if remaining == 0:
                    return _response(sessions, True)
                candidate = [*sessions, summary]
                if _size(_response(candidate, True)) > MAX_HISTORY_BYTES:
                    if not sessions:
                        raise ValueError("History summary exceeds its byte budget")
                    return _response(sessions, True)
                sessions.append(summary)
                remaining -= 1
            if page["has_more"]:
                return _response(sessions, True)
        except Exception:
            # DB/path/driver errors cannot reveal private state through this tool.
            raise ValueError("Session history is unavailable") from None
        before = None
    return _response(sessions, False)
