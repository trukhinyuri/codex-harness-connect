"""Logical storage bounds; permanent receipts are never expired or recycled.

These bounds are not a physical SQLite/WAL disk-space guarantee. Existing stores
are migrated without deleting history; the next event write enforces retention.
"""
from __future__ import annotations

import json
import sqlite3

MAX_SESSIONS = 4096
MAX_EVENT_BYTES = 64 * 1024
MAX_SESSION_EVENT_BYTES = 4 * 1024 * 1024
MAX_TOTAL_EVENT_BYTES = 64 * 1024 * 1024
MAX_OUTCOME_BYTES = 32 * 1024
MAX_STATUS_EVENT_BYTES = 256 * 1024
MAX_CURSOR = 2**63 - 1


class StorageCapacityError(RuntimeError):
    """Admission failed before spawning; replay remains available at capacity."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        super().__init__("storage_capacity_exhausted: permanent session capacity reached; "
                         "recover existing request IDs. No job was launched. "
                         "Receipts cannot be deleted or automatically rotated safely.")


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def byte_preview(value: str, limit: int) -> tuple[str, bool]:
    raw = value.encode("utf-8")
    return raw[:limit].decode("utf-8", errors="ignore"), len(raw) > limit


def bounded_outcome(outcome: dict) -> dict:
    """Persist recovery/semantic metadata, never a transcript or approval answer."""
    result = {key: outcome.get(key) for key in (
        "protocol", "native_session_id", "identity_verified", "semantic_status", "exit_code",
        "result_subtype", "is_error", "output_bytes", "permission_denial_count",
        "permission_denials_truncated", "api_error_status")}
    result.update(schema_version=1, task_acceptance="requires-parent-verification",
                  snapshot_truncated=False)

    def preview(value, limit=128):
        if isinstance(value, str):
            value, truncated = byte_preview(value, limit)
            result["snapshot_truncated"] |= truncated
        return value

    for key in ("protocol", "result_subtype"):
        result[key] = preview(result[key])
    errors = outcome.get("errors", [])
    result["errors"] = [{"code": preview(item.get("code")),
                         "message": preview(item.get("message"), 1024)} for item in errors[:8]]
    result["errors_truncated"] = bool(outcome.get("errors_truncated") or len(errors) > 8)
    deferred = outcome.get("deferred_tool_use")
    result["deferred_tool_use"] = ({key: preview(deferred.get(key), 1024)
                                    for key in ("id", "name")} if deferred else None)
    result["deferred_tool_truncated"] = bool(outcome.get("deferred_tool_truncated"))
    rates = outcome.get("rate_limit_events", [])
    result["rate_limit_events"] = [{key: preview(item.get(key)) for key in (
        "status", "resets_at", "rate_limit_type", "utilization", "overage_status",
        "overage_resets_at", "overage_disabled_reason", "metadata_truncated")}
        for item in rates[-8:]]
    result["rate_limit_events_truncated"] = bool(
        outcome.get("rate_limit_events_truncated") or len(rates) > 8)
    result["snapshot_truncated"] |= bool(result["errors_truncated"] or
        result["deferred_tool_truncated"] or result["rate_limit_events_truncated"])
    # The producer is a reviewed bounded parser, not arbitrary tool output.
    if len(encoded(result).encode("utf-8")) > MAX_OUTCOME_BYTES:
        raise ValueError("Native outcome exceeded its bounded metadata contract")
    return result


def initialize(db: sqlite3.Connection) -> None:
    """Migrate counters and policy atomically without expiring accepted requests."""
    if not db.in_transaction:
        raise RuntimeError("Storage migration requires the caller's write transaction")
    columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    if "payload_bytes" not in columns:
        db.execute("ALTER TABLE events ADD COLUMN payload_bytes INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE events SET payload_bytes=length(CAST(data AS BLOB))")
    db.execute("CREATE TABLE IF NOT EXISTS storage_policy (id INTEGER PRIMARY KEY CHECK(id=1), "
               "version INTEGER NOT NULL, session_capacity INTEGER NOT NULL)")
    db.execute("INSERT OR IGNORE INTO storage_policy VALUES(1,1,?)", (MAX_SESSIONS,))
    fresh = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                           "AND name='event_usage'").fetchone()
    db.execute("CREATE TABLE IF NOT EXISTS event_usage (session_id TEXT PRIMARY KEY, "
               "event_count INTEGER NOT NULL, event_bytes INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS event_totals (id INTEGER PRIMARY KEY CHECK(id=1), "
               "event_count INTEGER NOT NULL, event_bytes INTEGER NOT NULL)")
    db.execute("INSERT OR IGNORE INTO event_totals VALUES(1,0,0)")
    if fresh:
        db.execute("INSERT INTO event_usage SELECT session_id,COUNT(*),SUM(payload_bytes) "
                   "FROM events GROUP BY session_id")
        db.execute("UPDATE event_totals SET event_count=(SELECT COUNT(*) FROM events), "
                   "event_bytes=COALESCE((SELECT SUM(payload_bytes) FROM events),0) WHERE id=1")
    # execute(), unlike executescript(), does not commit the migration midway.
    db.execute("""CREATE TRIGGER IF NOT EXISTS events_usage_insert AFTER INSERT ON events BEGIN
        UPDATE events SET payload_bytes=length(CAST(NEW.data AS BLOB)) WHERE cursor=NEW.cursor;
        INSERT INTO event_usage VALUES(NEW.session_id,1,length(CAST(NEW.data AS BLOB)))
        ON CONFLICT(session_id) DO UPDATE SET event_count=event_count+1,
          event_bytes=event_bytes+length(CAST(NEW.data AS BLOB));
        UPDATE event_totals SET event_count=event_count+1,
          event_bytes=event_bytes+length(CAST(NEW.data AS BLOB));
        END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS events_usage_delete AFTER DELETE ON events BEGIN
        UPDATE event_usage SET event_count=event_count-1,event_bytes=event_bytes-OLD.payload_bytes
          WHERE session_id=OLD.session_id;
        UPDATE event_totals SET event_count=event_count-1,event_bytes=event_bytes-OLD.payload_bytes;
        END""")


def retain(db: sqlite3.Connection, session_id: str, max_events: int, max_total_events: int) -> None:
    """Evict oldest payloads, retaining per-job gap evidence and permanent receipts."""
    def prune(sid, count_limit, byte_limit):
        usage = db.execute("SELECT event_count,event_bytes FROM " +
                           ("event_usage WHERE session_id=?" if sid else "event_totals WHERE id=1"),
                           (sid,) if sid else ()).fetchone()
        if not usage or (usage[0] <= count_limit and usage[1] <= byte_limit):
            return
        count, size = usage
        rows = db.execute("SELECT cursor,payload_bytes FROM events " +
                          ("WHERE session_id=? " if sid else "") + "ORDER BY cursor",
                          (sid,) if sid else ())
        cutoff = None
        for cursor, payload_bytes in rows:
            cutoff = cursor
            count -= 1
            size -= payload_bytes
            if count <= count_limit and size <= byte_limit:
                break
        rows.close()
        if cutoff is None:
            return
        where = "cursor<=?" + (" AND session_id=?" if sid else "")
        args = (cutoff, sid) if sid else (cutoff,)
        dropped = db.execute("SELECT session_id,MAX(cursor) FROM events WHERE " + where +
                             " GROUP BY session_id", args).fetchall()
        db.executemany("UPDATE sessions SET discarded_until=MAX(discarded_until,?) "
                       "WHERE session_id=?", [(cursor, owner) for owner, cursor in dropped])
        db.execute("DELETE FROM events WHERE " + where, args)

    prune(session_id, max_events, MAX_SESSION_EVENT_BYTES)
    prune(None, max_total_events, MAX_TOTAL_EVENT_BYTES)
