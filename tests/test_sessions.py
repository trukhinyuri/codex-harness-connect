import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from codex_harness_connect.sessions import (
    MAX_EVENTS,
    STARTUP_GRACE_SECONDS,
    SessionService,
    connect_db,
    process_identity,
    socket_path,
)

FAKE = Path(__file__).parent / "fixtures" / "fake_harness.py"
TERMINAL = {"completed", "failed", "cancelled", "timed_out", "lost"}


def wait(service, sid, condition, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = service.status(sid, limit=1000)
        if condition(result):
            return result
        time.sleep(0.02)
    pytest.fail(f"Session did not reach expected state: {result}")


def text(result):
    return "".join(e["data"].get("text", "") for e in result["events"])


def launch(service, harness_mode, **kwargs):
    return service.start([sys.executable, "-u", str(FAKE), harness_mode], str(FAKE.parent), **kwargs)


@pytest.fixture
def service(tmp_path):
    service = SessionService(tmp_path / "state")
    yield service
    for job in service.list():
        if job["status"] not in TERMINAL and job["worker_alive"]:
            service.cancel(job["session_id"])
            wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)


@pytest.mark.parametrize("mode", ["pipe", "pty"])
def test_input_output_and_terminal_rejection(service, mode):
    job = launch(service, "echo", mode=mode)
    sid = job["session_id"]
    initial = wait(service, sid, lambda r: "TTY:" in text(r))
    assert initial["session"]["live"]
    assert f"TTY:{int(mode == 'pty')}" in text(initial)
    assert initial["session"]["native_session_id"] is None
    assert service.send(sid, "hello\n")["accepted"]
    echoed = wait(service, sid, lambda r: "ECHO:hello" in text(r))
    service.close_input(sid)
    final = wait(service, sid, lambda r: r["session"]["status"] in TERMINAL)
    assert final["session"]["status"] == "completed"
    assert final["session"]["exit_code"] == 0
    assert "STDERR" in text(final)
    assert "�" not in text(echoed)
    with pytest.raises(RuntimeError, match="Terminal"):
        service.send(sid, "late\n")
    assert not service.cancel(sid)["accepted"]


@pytest.mark.parametrize("mode", ["pipe", "pty"])
def test_incremental_utf8(service, mode):
    job = launch(service, "unicode", mode=mode)
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert "héllo 🌍" in text(result)
    assert "�" not in text(result)


def test_pty_has_controlling_terminal(service):
    job = launch(service, "tty", mode="pty")
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert result["session"]["status"] == "completed"
    assert "CONTROLLING_TTY" in text(result)


@pytest.mark.parametrize("reason", ["cancel", "timeout", "exit"])
def test_descendants_are_terminated(service, reason):
    job = launch(service, "exit-tree" if reason == "exit" else "tree",
                 timeout_seconds=0.8 if reason == "timeout" else 10)
    sid = job["session_id"]
    result = wait(service, sid, lambda r: "DESCENDANT:" in text(r))
    child = int(text(result).split("DESCENDANT:")[1].split()[0])
    if reason == "cancel":
        assert service.cancel(sid)["accepted"]
    final = wait(service, sid, lambda r: r["session"]["status"] in TERMINAL)
    assert final["session"]["status"] == {"cancel": "cancelled", "timeout": "timed_out", "exit": "completed"}[reason]
    assert process_identity(child) is None
    assert process_identity(job["child_pid"]) is None
    if reason != "exit":
        assert final["session"]["exit_signal"] == 9


def test_reconnect_and_monotonic_cursors(service):
    job = launch(service, "echo")
    sid = job["session_id"]
    initial = wait(service, sid, lambda r: "TTY:" in text(r))
    cursor = initial["next_cursor"]
    reconnected = SessionService(service.state_root)
    reconnected.send(sid, "reconnected\n")
    wait(reconnected, sid, lambda r: "ECHO:reconnected" in text(r))
    new = reconnected.status(sid, after=cursor)
    assert new["next_cursor"] > cursor
    assert all(e["cursor"] > cursor for e in new["events"])
    assert "ECHO:reconnected" in text(new)
    reconnected.close_input(sid)
    wait(reconnected, sid, lambda r: r["session"]["status"] in TERMINAL)


def test_request_recovers_same_job_without_duplicate_launch(service):
    request_id = uuid.uuid4().hex
    job = launch(service, "echo", request_id=request_id)
    reconnected = SessionService(service.state_root)
    assert reconnected.lookup_request(request_id)["session_id"] == job["session_id"]
    duplicate = launch(reconnected, "echo", request_id=request_id)
    assert duplicate["session_id"] == job["session_id"]
    assert duplicate["child_pid"] == job["child_pid"]
    assert len(service.list()) == 1
    with pytest.raises(ValueError, match="different launch"):
        launch(reconnected, "unicode", request_id=request_id)
    reconnected.close_input(job["session_id"])
    wait(reconnected, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)


def test_concurrent_duplicate_requests_have_one_launch(service):
    request_id = uuid.uuid4().hex
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda _: launch(service, "echo", request_id=request_id), range(2)))
    assert len({job["session_id"] for job in jobs}) == 1
    assert len(service.list()) == 1
    service.close_input(jobs[0]["session_id"])
    wait(service, jobs[0]["session_id"], lambda r: r["session"]["status"] in TERMINAL)


@pytest.mark.parametrize("mode,protocol,expected", [
    ("pipe", "claude-stream-json", "succeeded"),
    ("pipe", None, "unknown"),
    ("pty", None, "unknown"),
])
def test_typed_protocol_is_used_only_for_declared_stdout_pipe(service, mode, protocol, expected):
    native_id = str(uuid.uuid4())
    init = {"type": "system", "subtype": "init", "session_id": native_id}
    result = {"type": "result", "subtype": "success", "is_error": False,
              "session_id": native_id, "duration_ms": 1, "duration_api_ms": 1,
              "num_turns": 1, "result": "SYNTHETIC_PROTOCOL_OK"}
    code = (f"import json,sys; print(json.dumps({init!r})); "
            f"print(json.dumps({result!r})); print('{{\"session_id\":\"stderr-spoof\"}}',file=sys.stderr)")
    job = service.start([sys.executable, "-c", code], str(FAKE.parent), mode=mode, protocol=protocol)
    final = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert final["session"]["semantic_status"] == expected
    assert final["session"]["native_session_id"] == (native_id if protocol else None)
    assert any(e["kind"] == "native_outcome" for e in final["events"]) is bool(protocol)


def test_survives_launching_service_process_exit(tmp_path):
    root = tmp_path / "detached"
    source = Path(__file__).parents[1] / "src"
    code = (
        "from pathlib import Path; from codex_harness_connect.sessions import SessionService; "
        f"s=SessionService(Path({str(root)!r})); "
        f"print(s.start({[sys.executable, '-u', str(FAKE), 'echo']!r}, {str(FAKE.parent)!r})['session_id'])"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source)
    sid = subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
    service = SessionService(root)
    try:
        assert service.status(sid)["session"]["worker_alive"]
        service.send(sid, "after-parent-exit\n")
        wait(service, sid, lambda r: "ECHO:after-parent-exit" in text(r))
        service.close_input(sid)
        wait(service, sid, lambda r: r["session"]["status"] in TERMINAL)
    finally:
        if service.status(sid)["session"]["status"] not in TERMINAL:
            service.cancel(sid)


def test_startup_and_nonzero_exit_are_honest(service):
    missing = service.start(["/definitely/no/executable"], str(FAKE.parent))
    assert missing["status"] == "failed"
    assert "No such file" in missing["error"]
    badcwd = service.start([sys.executable, "-c", "pass"], "/definitely/no/directory")
    assert badcwd["status"] == "failed"
    job = launch(service, "nonzero")
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert result["session"]["status"] == "failed"
    assert result["session"]["exit_code"] == 7


def test_ids_validation_private_files_and_environment(service):
    for bad in ("../escape", "not-an-id", "A" * 32, "", None):
        with pytest.raises(ValueError):
            service.status(bad)
    with pytest.raises(KeyError):
        service.status("0" * 32)
    with pytest.raises(ValueError):
        service.start([], str(FAKE.parent))
    with pytest.raises(ValueError):
        service.start([sys.executable], str(FAKE.parent), timeout_seconds=0)
    secret = "synthetic-only-unguessable-secret"
    job = launch(service, "env", env_overrides={"SYNTHETIC_SECRET": secret})
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert secret in text(result)
    assert service.state_root.stat().st_mode & 0o777 == 0o700
    # Child output can contain anything; launch configuration never persists env.
    session = result["session"]
    assert secret not in json.dumps(session)
    assert list(service.state_root.iterdir())
    for path in service.state_root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    assert socket_path(service.state_root, job["session_id"]).parent.stat().st_mode & 0o777 == 0o700


def test_concurrent_sessions_and_status_read_latency(service):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: launch(service, "sleep"), range(4)))
    assert len({job["session_id"] for job in jobs}) == 4
    started = time.monotonic()
    for job in jobs:
        assert service.status(job["session_id"])["session"]["live"]
    assert time.monotonic() - started < 0.5
    assert len(service.list()) == 4


def test_admission_waits_for_writer_without_duplicate_launch(service):
    request_id = uuid.uuid4().hex
    blocker = connect_db(service.state_root)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(launch, service, "sleep", request_id=request_id)
            try:
                with pytest.raises(concurrent.futures.TimeoutError):
                    future.result(timeout=0.3)
            finally:
                blocker.rollback()
            job = future.result(timeout=5)
    finally:
        blocker.close()
    replay = launch(service, "sleep", request_id=request_id)
    assert replay["session_id"] == job["session_id"]
    assert len(service.list()) == 1
    with connect_db(service.state_root) as db:
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 100


def test_bounded_events(service):
    job = launch(service, "burst")
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL, seconds=15)
    assert len(result["events"]) <= MAX_EVENTS
    assert result["earliest_cursor"] > 1
    assert service.status(job["session_id"], after=1)["truncated"]
    with connect_db(service.state_root) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE session_id=?",
                          (job["session_id"],)).fetchone()[0] <= MAX_EVENTS


def test_global_cursor_gaps_are_not_claimed_as_truncation(service):
    first = launch(service, "unicode")
    wait(service, first["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    second = launch(service, "unicode")
    result = wait(service, second["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert result["earliest_cursor"] > 1
    assert not service.status(second["session_id"], after=1)["truncated"]


def test_worker_identity_is_checked_not_trusted_from_database(service):
    sid = uuid.uuid4().hex
    with connect_db(service.state_root) as db:
        db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at,"
                   "started_at,worker_pid,worker_start,heartbeat) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (sid, "running", "pipe", str(FAKE.parent), "synthetic", time.time(),
                    time.time(), os.getpid(), "wrong-start-identity", time.time()))
    result = service.status(sid)
    assert not result["session"]["worker_alive"]
    assert not result["session"]["live"]
    assert result["session"]["status"] == "lost"
    assert any(e["kind"] == "worker_lost" for e in result["events"])
    assert service.status(sid)["session"]["status"] == "lost"


@pytest.mark.parametrize("kill_native_leader", [False, True])
@pytest.mark.parametrize("tree_mode", ["tree", "soft-tree"])
def test_lost_worker_can_cancel_confirmed_native_tree(service, kill_native_leader, tree_mode):
    from codex_harness_connect.worker import _descendants
    job = launch(service, tree_mode)
    sid = job["session_id"]
    result = wait(service, sid, lambda r: "DESCENDANT:" in text(r))
    descendant = int(text(result).split("DESCENDANT:")[1].split()[0])
    if kill_native_leader:
        wait(service, sid, lambda r: str(descendant) in r["session"]["process_members"])
    os.kill(job["worker_pid"], signal.SIGKILL)
    lost = wait(service, sid, lambda r: r["session"]["status"] == "lost")
    assert not lost["session"]["worker_alive"]
    assert process_identity(job["child_pid"]) == job["child_start"]
    if kill_native_leader:
        os.kill(job["child_pid"], signal.SIGKILL)
        deadline = time.monotonic() + 2
        while process_identity(job["child_pid"]) and time.monotonic() < deadline:
            time.sleep(0.01)
    assert service.cancel(sid)["accepted"]
    final = service.status(sid)["session"]
    assert final["status"] == "cancelled"
    assert final["exit_code"] is None and final["exit_signal"] is None
    assert process_identity(job["child_pid"]) is None
    assert process_identity(descendant) is None
    assert not _descendants(-1, job["process_group"])


def test_lost_cancel_refuses_reused_child_pid_and_unconfirmed_group(service):
    sid = uuid.uuid4().hex
    current_identity = process_identity(os.getpid())
    with connect_db(service.state_root) as db:
        db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at,"
                   "started_at,child_pid,child_start,process_group) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (sid, "lost", "pipe", str(FAKE.parent), "synthetic", time.time(),
                    time.time(), os.getpid(), "replaced-process-start", os.getpgrp()))
    result = service.cancel(sid)
    assert not result["accepted"]
    assert result["status"] == "lost"
    assert process_identity(os.getpid()) == current_identity


def test_startup_exit_is_recovered_without_premature_lost(service):
    sid = uuid.uuid4().hex
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    identity = process_identity(worker.pid)
    assert identity
    with connect_db(service.state_root) as db:
        db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at,"
                   "worker_pid,worker_start) VALUES(?,?,?,?,?,?,?,?)",
                   (sid, "starting", "pipe", str(FAKE.parent), "synthetic-bootstrap",
                    time.time(), worker.pid, identity))
    try:
        initial = service.status(sid)["session"]
        assert initial["status"] == "starting" and initial["worker_alive"]
        assert initial["started_at"] is None
        worker.wait(timeout=2)
        assert service.status(sid)["session"]["status"] == "lost"
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait()
    unregistered = uuid.uuid4().hex
    with connect_db(service.state_root) as db:
        db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at) "
                   "VALUES(?,?,?,?,?,?)", (unregistered, "starting", "pipe", str(FAKE.parent),
                                           "synthetic-bootstrap", time.time()))
    assert service.status(unregistered)["session"]["status"] == "starting"
    with connect_db(service.state_root) as db:
        db.execute("UPDATE sessions SET created_at=? WHERE session_id=?",
                   (time.time() - STARTUP_GRACE_SECONDS - 1, unregistered))
    assert service.status(unregistered)["session"]["status"] == "lost"


@pytest.mark.parametrize("mode", ["pipe", "pty"])
def test_generic_json_output_cannot_set_native_session_id(service, mode):
    job = launch(service, "spoof-id", mode=mode)
    result = wait(service, job["session_id"], lambda r: r["session"]["status"] in TERMINAL)
    assert "stdout-spoof" in text(result) and "stderr-spoof" in text(result)
    assert result["session"]["native_session_id"] is None
