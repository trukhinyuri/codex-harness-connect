"""Full containment acceptance gate: known failing on macOS, not a passing unit test.

Run explicitly: python -m pytest -q validation/test_daemon_containment.py
The test safely cleans its captured synthetic daemon in finally. It is kept outside
the passing regression suite because it represents an unimplemented requirement,
not a capability this alpha claims to provide. Do not mark it xfail or remove it.
"""
import json
import os
import signal
import sys
import time

from codex_harness_connect import sessions
from codex_harness_connect.sessions import SessionService, connect_db, process_identity

TERMINAL = {"completed", "failed", "cancelled", "timed_out", "lost"}


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
        "[os.write(1,b'x'*4096) for _ in range(1800)]; time.sleep(60)"
    )
    job = service.start([sys.executable, "-c", code], str(tmp_path), timeout_seconds=20)
    descendant = wait_for(lambda: captured(capture))
    assert descendant["start"] and process_identity(descendant["pid"]) == descendant["start"]
    return job, descendant


def bounded_state(service, sid):
    with connect_db(service.state_root) as db:
        count = db.execute("SELECT COUNT(*) FROM events WHERE session_id=?", (sid,)).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count <= sessions.MAX_EVENTS and total <= sessions.MAX_TOTAL_EVENTS
    assert service.state_root.stat().st_mode & 0o777 == 0o700
    for file in service.state_root.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600


def test_immediate_setsid_descendant_does_not_escape_when_native_parent_exits(tmp_path):
    service = SessionService(tmp_path / "state")
    capture = tmp_path / "daemon.json"
    code = (
        "import json,os,signal,time\n"
        "from codex_harness_connect.sessions import process_identity\n"
        "pid=os.fork()\n"
        "if pid: os._exit(0)\n"
        "os.setsid()\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        "null=os.open('/dev/null',os.O_RDWR)\n"
        "for fd in (0,1,2): os.dup2(null,fd)\n"
        f"open({str(capture)!r},'w').write(json.dumps(dict(pid=os.getpid(),"
        "start=process_identity(os.getpid()),group=os.getpgrp(),parent=os.getppid())))\n"
        "time.sleep(60)\n"
    )
    job = service.start([sys.executable, "-c", code], str(tmp_path), timeout_seconds=10)
    daemon = None
    try:
        daemon = wait_for(lambda: captured(capture))
        assert daemon["start"]
        final = wait_for(lambda: service.status(job["session_id"])["session"] if
                         service.status(job["session_id"])["session"]["status"] in TERMINAL else None)
        live = process_identity(daemon["pid"]) == daemon["start"]
        print("DAEMON_OBSERVATION", json.dumps({"platform": sys.platform, "session_id": job["session_id"],
              "status": final["status"], "native_group": job["process_group"], "daemon": daemon,
              "captured_in_members": str(daemon["pid"]) in final["process_members"], "daemon_live": live}))
        bounded_state(service, job["session_id"])
        assert not live, f"Escaped daemon remains live: {daemon}; session status={final['status']}"
    finally:
        kill_exact(daemon)
        kill_exact({"pid": job["child_pid"], "start": job["child_start"]})
        kill_exact({"pid": job["worker_pid"], "start": job["worker_start"]})
