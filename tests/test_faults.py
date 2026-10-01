"""Synthetic database/retention/cancellation regressions; no model providers."""
import json
import os
import signal
import sqlite3
import sys
import time
import uuid

from codex_harness_connect import sessions
from codex_harness_connect.sessions import SessionService, connect_db, process_identity

TERMINAL = {"completed", "failed", "cancelled", "timed_out", "lost"}
BURST_DONE = "\nRETENTION_BURST_DONE\n"


def wait_for(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    result = None
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Fault scenario did not reach its required condition: {result}")


def captured(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None


def wait_for_burst(service, sid):
    cursor = 0
    tail = ""

    def drained():
        nonlocal cursor, tail
        result = service.status(sid, after=cursor, limit=1000)
        cursor = result["next_cursor"]
        for item in result["events"]:
            combined = tail + item["data"].get("text", "")
            if BURST_DONE in combined:
                return result
            tail = combined[-len(BURST_DONE):]
        assert result["session"]["status"] not in TERMINAL, "Native tree exited before the burst drained"
        return None

    return wait_for(drained)


def kill_exact(info):
    if info and process_identity(info["pid"]) == info["start"]:
        os.kill(info["pid"], signal.SIGKILL)
        wait_for(lambda: process_identity(info["pid"]) != info["start"], seconds=2)


def tree(service, tmp_path):
    capture = tmp_path / "native-descendant.json"
    child_code = (
        "import json,os,signal,time; "
        "from codex_harness_connect.sessions import process_identity; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"open({str(capture)!r},'w').write(json.dumps(dict(pid=os.getpid(),"
        "start=process_identity(os.getpid()),group=os.getpgrp()))); time.sleep(60)"
    )
    code = (
        "import os,signal,subprocess,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "[os.write(1,b'x'*4096) for _ in range(1800)]; "
        f"os.write(1,{BURST_DONE.encode()!r}); time.sleep(60)"
    )
    job = service.start([sys.executable, "-c", code], str(tmp_path), timeout_seconds=20)
    descendant = wait_for(lambda: captured(capture))
    assert descendant["start"] and process_identity(descendant["pid"]) == descendant["start"]
    return job, descendant


def bounded_state(service, sid):
    with sessions.session_db(service.state_root) as db:
        count = db.execute("SELECT COUNT(*) FROM events WHERE session_id=?", (sid,)).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count <= sessions.MAX_EVENTS and total <= sessions.MAX_TOTAL_EVENTS
    assert service.state_root.stat().st_mode & 0o777 == 0o700
    for file in service.state_root.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600


def test_database_lock_after_launch_kills_native_tree_and_preserves_unknown_result(tmp_path):
    service = SessionService(tmp_path / "state")
    job, descendant = tree(service, tmp_path)
    sid = job["session_id"]
    native = {"pid": job["child_pid"], "start": job["child_start"]}
    lock = connect_db(service.state_root)
    try:
        ready = wait_for_burst(service, sid)
        assert ready["session"]["discarded_until"] > 0
        assert ready["session"]["status"] == "running"
        assert process_identity(native["pid"]) == native["start"]
        assert process_identity(descendant["pid"]) == descendant["start"]
        # The persisted tail marker proves the worker consumed the full burst.
        # Only periodic heartbeats now compete with this one bounded attempt.
        # This injector timeout is separate from the worker's unchanged 100ms.
        lock.execute("PRAGMA busy_timeout=1000")
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            exc.add_note(f"Fault lock not acquired: SQLite {sqlite3.sqlite_version}; "
                         f"code={exc.sqlite_errorcode}; name={exc.sqlite_errorname}")
            raise
        assert lock.in_transaction, "Shutdown must be tested while the fault lock is held"
        # Release is deliberately later than worker busy_timeout and its error
        # recording attempt. Native safety must not depend on unlocking SQLite.
        wait_for(lambda: process_identity(native["pid"]) != native["start"]
                 and process_identity(descendant["pid"]) != descendant["start"], seconds=3)
        before = time.monotonic()
        try:
            during = service.status(sid)["session"]
            assert during["status"] != "completed"
        except sqlite3.OperationalError as exc:
            assert "locked" in str(exc)
        assert time.monotonic() - before < 0.5
        lock.rollback()
        final = wait_for(lambda: service.status(sid)["session"] if
                         service.status(sid)["session"]["status"] in TERMINAL else None)
        assert final["status"] in {"failed", "lost"}
        assert final["exit_code"] is None
        assert final["semantic_status"] == "unknown"
        bounded_state(service, sid)
        print("CONTENTION_OBSERVATION", json.dumps({"session_id": sid, "status": final["status"],
              "native": native, "descendant": descendant, "native_tree_live": False,
              "semantic_status": final["semantic_status"]}))
    finally:
        lock.rollback()
        lock.close()
        kill_exact(descendant)
        kill_exact(native)
        kill_exact({"pid": job["worker_pid"], "start": job["worker_start"]})


def test_cancellation_after_retention_pressure_cleans_confirmed_tree(tmp_path):
    service = SessionService(tmp_path / "state")
    job, descendant = tree(service, tmp_path)
    sid = job["session_id"]
    native = {"pid": job["child_pid"], "start": job["child_start"]}
    try:
        wait_for(lambda: service.status(sid)["session"]["discarded_until"] > 0)
        before = service.status(sid, limit=1000)
        assert before["truncated"]
        assert service.cancel(sid)["accepted"]
        final = wait_for(lambda: service.status(sid) if
                         service.status(sid)["session"]["status"] in TERMINAL else None)
        assert final["session"]["status"] == "cancelled"
        assert final["session"]["exit_signal"] == signal.SIGKILL
        assert process_identity(native["pid"]) != native["start"]
        assert process_identity(descendant["pid"]) != descendant["start"]
        after = service.status(sid, after=before["next_cursor"], limit=1000)
        assert after["events"] and all(event["cursor"] > before["next_cursor"] for event in after["events"])
        bounded_state(service, sid)
    finally:
        kill_exact(descendant)
        kill_exact(native)
        kill_exact({"pid": job["worker_pid"], "start": job["worker_start"]})


def test_scaled_global_and_per_session_retention_keep_monotonic_reconnect(tmp_path, monkeypatch):
    service = SessionService(tmp_path / "state")
    monkeypatch.setattr(sessions, "MAX_EVENTS", 8)
    monkeypatch.setattr(sessions, "MAX_TOTAL_EVENTS", 16)
    ids = [uuid.uuid4().hex for _ in range(3)]
    with sessions.session_db(service.state_root) as db:
        for sid in ids:
            db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at) "
                       "VALUES(?,?,?,?,?,?)", (sid, "completed", "pipe", str(tmp_path),
                                               "synthetic-state-record", time.time()))
        for index in range(80):
            sessions.event(db, ids[index % 3], "output", {"stream": "stdout", "text": str(index)})
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 16
    for sid in ids:
        first = service.status(sid, limit=1000)
        assert first["truncated"] and len(first["events"]) <= 8
        cursor = first["next_cursor"]
        assert cursor > 0
        assert not service.status(sid, after=cursor)["events"]
        bounded_state(service, sid)
