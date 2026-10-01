"""Byte retention, permanent outcomes and recovery under lost event history."""
import json
import sqlite3
import sys
import time
import uuid
from contextlib import closing

import pytest

from codex_harness_connect import sessions, storage
from codex_harness_connect.sessions import SessionService, event, session_db, update


def receipt(db, sid=None, **fields):
    sid = sid or uuid.uuid4().hex
    db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at) "
               "VALUES(?,'completed','pipe','/synthetic','synthetic',?)", (sid, time.time()))
    if fields:
        update(db, sid, **fields)
    return sid


def check_counters(db):
    actual = tuple(db.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(data AS BLOB))),0) "
                              "FROM events").fetchone())
    assert tuple(db.execute("SELECT event_count,event_bytes FROM event_totals").fetchone()) == actual
    for sid, count, size in db.execute("SELECT * FROM event_usage"):
        assert tuple(db.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(data AS BLOB))),0) "
                                "FROM events WHERE session_id=?", (sid,)).fetchone()) == (count, size)


def test_byte_retention_is_utf8_exact_and_does_not_forget_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_SESSION_EVENT_BYTES", 400)
    monkeypatch.setattr(storage, "MAX_TOTAL_EVENT_BYTES", 650)
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        first, second = receipt(db), receipt(db)
        for i in range(12):
            event(db, first if i % 2 else second, "output", {"text": "🌍\0" * 20})
            check_counters(db)
            assert db.execute("SELECT event_bytes FROM event_totals").fetchone()[0] <= 650
            assert max(row[0] for row in db.execute("SELECT event_bytes FROM event_usage")) <= 400
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    for sid in (first, second):
        page = service.status(sid)
        assert page["truncated"] and page["session"]["history_truncated"]
        assert page["session"]["event_bytes"] <= 400


def test_oversized_event_is_explicitly_omitted_not_a_write_failure(tmp_path):
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db)
        event(db, sid, "native_protocol", {"text": "🌍" * storage.MAX_EVENT_BYTES})
        event(db, sid, "exit", {"status": "completed"})
        check_counters(db)
    page = service.status(sid)
    assert page["truncated"]
    assert page["events"][0]["data"]["payload_omitted"]
    assert page["events"][0]["data"]["original_payload_bytes"] > storage.MAX_EVENT_BYTES
    assert page["events"][-1]["kind"] == "exit"
    assert page["session"]["status"] == "completed"


def test_counters_and_watermarks_roll_back_together(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_TOTAL_EVENT_BYTES", 80)
    SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db)
        event(db, sid, "output", {"text": "original"})
    with pytest.raises(RuntimeError):
        with session_db(tmp_path) as db:
            event(db, sid, "output", {"text": "new" * 100})
            raise RuntimeError("fault after eviction")
    with session_db(tmp_path) as db:
        check_counters(db)
        assert json.loads(db.execute("SELECT data FROM events").fetchone()[0]) == {"text": "original"}
        assert db.execute("SELECT discarded_until FROM sessions").fetchone()[0] == 0


def test_fully_evicted_job_advances_recovery_watermark(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_TOTAL_EVENT_BYTES", 100)
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        first, second = receipt(db), receipt(db)
        event(db, first, "output", {"text": "first"})
        event(db, second, "output", {"text": "later" * 15})
    page = service.status(first)
    assert page["events"] == [] and page["truncated"] and page["next_cursor"] > 0
    assert not service.status(first, after=page["next_cursor"])["truncated"]


def test_durable_outcome_survives_global_event_eviction(tmp_path, monkeypatch):
    service = SessionService(tmp_path)
    native_id = str(uuid.uuid4())
    values = [{"type": "system", "subtype": "init", "session_id": native_id},
              {"type": "result", "subtype": "success", "is_error": False,
               "session_id": native_id, "result": "SYNTHETIC_ONLY", "permission_denials": [],
               "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1}]
    code = "import json; " + "; ".join(f"print(json.dumps({item!r}))" for item in values)
    job = service.start([sys.executable, "-c", code], str(tmp_path), protocol="claude-stream-json")
    deadline = time.monotonic() + 8
    while True:
        final = service.status(job["session_id"])["session"]
        if final["status"] in sessions.TERMINAL and not final["worker_alive"]:
            break
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert final["status"] == "completed" and final["semantic_status"] == "succeeded"
    outcome = final["native_outcome"]
    assert outcome["native_session_id"] == native_id and outcome["identity_verified"]
    assert "SYNTHETIC_ONLY" not in json.dumps(outcome)
    monkeypatch.setattr(storage, "MAX_TOTAL_EVENT_BYTES", 100)
    with session_db(tmp_path) as db:
        other = receipt(db)
        event(db, other, "output", {"text": "later" * 15})
    reconnected = SessionService(tmp_path)
    page = reconnected.status(job["session_id"])
    assert page["events"] == [] and page["truncated"]
    assert page["session"]["native_outcome"] == outcome
    assert page["session"]["native_session_id"] == native_id


def test_outcome_snapshot_bounds_utf8_errors_rates_and_critical_identity():
    from codex_harness_connect.protocols import ClaudeStreamParser

    parser = ClaudeStreamParser()
    outcome = parser.finish(1)
    outcome["errors"] *= 100
    outcome["errors"][0]["message"] = "🌍" * 10000
    outcome["rate_limit_events"] = [{"status": "rejected", "rate_limit_type": "🌍" * 1000}] * 50
    snapshot = storage.bounded_outcome(outcome)
    assert len(storage.encoded(snapshot).encode()) <= storage.MAX_OUTCOME_BYTES
    assert snapshot["snapshot_truncated"] and snapshot["errors_truncated"]
    assert snapshot["rate_limit_events_truncated"] and snapshot["semantic_status"] == "unknown"
    assert len(snapshot["errors"][0]["message"].encode()) <= 1024
    assert snapshot["task_acceptance"] == "requires-parent-verification"


def test_migration_keeps_legacy_history_and_initializes_exact_counters(tmp_path):
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db)
        db.execute("DROP TRIGGER events_usage_insert")
        db.execute("DROP TRIGGER events_usage_delete")
        db.execute("DROP TABLE event_usage")
        db.execute("DROP TABLE event_totals")
        db.execute("ALTER TABLE events DROP COLUMN payload_bytes")
        data = json.dumps({"text": "🌍" * storage.MAX_EVENT_BYTES})
        db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,'output',?,?)",
                   (sid, data, time.time()))
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        check_counters(db)
        assert db.execute("SELECT data FROM events").fetchone()[0] == data
    page = service.status(sid)
    assert page["events"][0]["data"]["payload_omitted"]
    assert len(json.dumps(page["events"]).encode()) < storage.MAX_STATUS_EVENT_BYTES


def test_failed_migration_rolls_back_schema_and_byte_backfill(tmp_path, monkeypatch):
    SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db)
        db.execute("DROP TRIGGER events_usage_insert")
        db.execute("DROP TRIGGER events_usage_delete")
        db.execute("DROP TABLE event_usage")
        db.execute("DROP TABLE event_totals")
        db.execute("ALTER TABLE events DROP COLUMN payload_bytes")
        db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,'output',?,?)",
                   (sid, json.dumps({"text": "x" * 70000}), time.time()))
    original = storage.initialize

    def fail(db):
        original(db)
        raise RuntimeError("migration interrupted")

    monkeypatch.setattr(storage, "initialize", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        SessionService(tmp_path)
    with session_db(tmp_path) as db:
        assert "payload_bytes" not in {row[1] for row in db.execute("PRAGMA table_info(events)")}
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='event_usage'").fetchone()
    monkeypatch.setattr(storage, "initialize", original)
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        check_counters(db)
    assert service.status(sid)["payloads_omitted"]


def test_old_worker_insert_is_counted_without_trusting_supplied_size(tmp_path):
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db)
        # Already running alpha.4 workers omit the new column after migration.
        db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,'output',?,?)",
                   (sid, json.dumps({"text": "x" * 70000}), time.time()))
        check_counters(db)
    assert service.storage_status()["legacy_store_over_budget"]
    page = service.status(sid)
    assert page["payloads_omitted"] and page["events"][0]["data"]["original_payload_bytes"] > 70000


@pytest.mark.parametrize("after", [True, -1, 2**63, 1.5, "0"])
def test_status_rejects_cursor_outside_sqlite_range(tmp_path, after):
    service = SessionService(tmp_path)
    with pytest.raises(ValueError, match="64-bit"):
        service.status("a" * 32, after=after)


def test_event_pages_byte_bound_without_skip_and_error_preview(tmp_path):
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        sid = receipt(db, error="🌍" * 10000)
        for i in range(10):
            event(db, sid, "output", {"text": "🌍" * 10000, "ordinal": i})
    seen, cursor = [], 0
    while True:
        page = service.status(sid, after=cursor, limit=1000)
        if not page["events"]:
            break
        seen.extend(item["data"]["ordinal"] for item in page["events"])
        assert len(storage.encoded(page["events"]).encode()) < storage.MAX_STATUS_EVENT_BYTES + 4
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
    assert seen == list(range(10))
    assert len(page["session"]["error"].encode()) <= 4096
    assert page["session"]["error_truncated"]


def test_storage_measurement_does_not_checkpoint_or_delete_with_pinned_reader(tmp_path):
    service = SessionService(tmp_path)
    with closing(sqlite3.connect(tmp_path / "sessions.sqlite3")) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM sessions").fetchall()
        with session_db(tmp_path) as db:
            sid = receipt(db)
            event(db, sid, "output", {"text": "measurement"})
        observed = service.storage_status()
        assert observed["accepted_sessions"] == 1
        assert observed["file_bytes"]["database"] > 0 and observed["file_bytes"]["wal"] > 0
        assert not observed["physical_disk_bound_verified"] and not observed["maintenance_performed"]
        assert reader.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert service.status(sid)["events"]


def test_real_history_pages_equal_timestamps_are_complete(tmp_path):
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        ids = [receipt(db, f"{i:032x}", created_at=1) for i in range(55)]
    seen, cursor = [], None
    while True:
        page = service.list_page(limit=7, before_session_id=cursor)
        seen.extend(job["session_id"] for job in page["sessions"])
        assert not any("process_members" in job or "cwd" in job for job in page["sessions"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert seen == sorted(ids, reverse=True)
    with pytest.raises(ValueError):
        service.list_page(before_session_id="f" * 32)


def test_wait_reports_fully_evicted_terminal_job(tmp_path, monkeypatch):
    import asyncio

    from codex_harness_connect.waiting import WaitTarget, wait_for_sessions
    monkeypatch.setattr(storage, "MAX_TOTAL_EVENT_BYTES", 100)
    service = SessionService(tmp_path)
    with session_db(tmp_path) as db:
        first, second = receipt(db), receipt(db)
        event(db, first, "output", {"text": "first"})
        event(db, second, "output", {"text": "later" * 15})
    result = asyncio.run(wait_for_sessions([WaitTarget(session_id=first, after=0)], service.status, 0))
    assert result["reason"] == "retention_gap"
    item = result["sessions"][0]
    assert item["terminal"] and item["next_cursor"] == 0 and "error" not in item
