"""Detached single-session worker. No shell and no persisted launch/environment."""
from __future__ import annotations

import codecs
import ctypes
import errno
import fcntl
import json
import os
import pty
import selectors
import signal
import socket
import subprocess
import sys
import termios
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codex_harness_connect.sessions import (
    MAX_INPUT_BYTES,
    MAX_TRACKED_PROCESSES,
    connect_db,
    event,
    process_identity,
    secure_db_files,
    socket_path,
    update,
)
from codex_harness_connect.storage import bounded_outcome, encoded


def _descendants(parent: int, group: int | None = None) -> dict[int, str]:
    parents = {}
    groups = {}
    if sys.platform.startswith("linux"):
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                    parents[int(entry.name)] = int(fields[1])
                    groups[int(entry.name)] = int(fields[2])
                except (OSError, ValueError, IndexError):
                    pass
    else:
        # libproc exposes the parent PID without executing ps or scanning commands.
        from codex_harness_connect.sessions import _BSDInfo
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        count = lib.proc_listallpids(None, 0)
        pids = (ctypes.c_int * (count + 128))()
        count = lib.proc_listallpids(pids, ctypes.sizeof(pids))
        for pid in pids[:max(0, count)]:
            info = _BSDInfo()
            if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) > 0:
                parents[pid] = info.ppid
                groups[pid] = info.pgid
    # Group membership survives immediate parent exit and reparenting to init.
    found = {pid: identity for pid, pgid in groups.items() if pgid == group
             and (identity := process_identity(pid))}
    frontier = {parent, *found}
    while frontier:
        frontier = {pid for pid, ppid in parents.items() if ppid in frontier and pid not in found}
        for pid in frontier:
            identity = process_identity(pid)
            if identity:
                found[pid] = identity
    return found


def _signal_group(group: int | None, sig: int, tracked: dict[int, str]) -> None:
    # A finished group with only zombies can yield EPERM on macOS. Do not signal
    # a recycled group after every process identity we observed has disappeared.
    def member_is_live(pid, identity):
        if process_identity(pid) != identity:
            return False
        try:
            return os.getpgid(pid) == group
        except ProcessLookupError:
            return False

    if group and any(member_is_live(pid, identity) for pid, identity in tracked.items()):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            if any(member_is_live(pid, identity) for pid, identity in tracked.items()):
                raise


def _signal_tracked(tracked: dict[int, str], sig: int) -> None:
    for pid, identity in tuple(tracked.items()):
        if process_identity(pid) == identity:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass


def _reap() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if not pid:
                return
        except ChildProcessError:
            return


def _tty_setup(slave: int) -> None:
    os.setsid()
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)


def main() -> None:
    os.umask(0o077)
    root, session_id = Path(sys.argv[1]), sys.argv[2]
    db = connect_db(root)
    control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = socket_path(root, session_id)
    selector = selectors.DefaultSelector()
    proc = None
    master = slave = None
    input_fd = None
    outputs = {}
    pending = bytearray()
    close_requested = False
    eof_queued = False
    tty_eof = b"\x04"
    input_closed = False
    stopping = None
    stop_deadline = None
    tracked = {}
    decoders = {}
    signal_stop = False
    native_parser = None

    def requested_signal(_sig, _frame):
        nonlocal signal_stop
        signal_stop = True

    signal.signal(signal.SIGTERM, requested_signal)
    signal.signal(signal.SIGINT, requested_signal)
    if sys.platform.startswith("linux"):
        # Adopt and reap grandchildren even if a harness daemonizes its children.
        ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER

    def output(stream: str, data: bytes, final: bool = False):
        text = decoders[stream].decode(data, final=final)
        if not text:
            return
        with db:
            event(db, session_id, "output", {"stream": stream, "text": text})
            if stream == "stdout" and native_parser is not None:
                for item in native_parser.feed(text):
                    event(db, session_id, "native_protocol", item)
                update(db, session_id, native_session_id=native_parser.native_session_id)

    def begin_stop(reason: str):
        nonlocal stopping, stop_deadline
        if stopping:
            return
        stopping = reason
        stop_deadline = time.monotonic() + 0.35
        tracked.update(_descendants(os.getpid(), proc.pid))
        _signal_group(proc.pid, signal.SIGTERM, tracked)
        _signal_tracked(tracked, signal.SIGTERM)
        with db:
            update(db, session_id, status="cancelling" if reason == "cancelled" else "stopping")
            event(db, session_id, "stop_requested", {"reason": reason})

    def handle_control():
        nonlocal close_requested, tty_eof, signal_stop
        conn, _ = control.accept()
        with conn:
            conn.settimeout(0.25)
            payload = bytearray()
            response = {"accepted": False}
            try:
                while b"\n" not in payload and len(payload) <= MAX_INPUT_BYTES:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    payload.extend(chunk)
                if len(payload) > MAX_INPUT_BYTES or not payload.endswith(b"\n"):
                    raise ValueError("Invalid control request")
                item = json.loads(payload)
                command = item["command"]
                if proc is None:
                    if command == "cancel":
                        signal_stop = True
                        with db:
                            update(db, session_id, status="cancelling", heartbeat=time.time())
                            event(db, session_id, "stop_requested", {"reason": "cancelled"})
                        conn.sendall(json.dumps({"accepted": True, "status": "cancelling"}).encode() + b"\n")
                        return
                    raise ValueError("Native session is still checking authorization")
                if command == "cancel" and (proc.poll() is not None or stopping):
                    response = {"accepted": False, "status": "stopping"}
                    conn.sendall(json.dumps(response).encode() + b"\n")
                    return
                if proc.poll() is not None or stopping:
                    raise ValueError("Session is terminating")
                if command == "cancel":
                    begin_stop("cancelled")
                elif command == "close_input":
                    if master is not None:
                        settings = termios.tcgetattr(master)
                        if not settings[3] & termios.ICANON:
                            raise ValueError("PTY close_input requires canonical terminal mode")
                        tty_eof = settings[6][termios.VEOF]
                        if not tty_eof or tty_eof == b"\0":
                            raise ValueError("PTY EOF is disabled")
                    close_requested = True
                elif command == "send":
                    if close_requested or input_closed:
                        raise ValueError("Session input is closed")
                    data = item["text"].encode("utf-8")
                    if len(pending) + len(data) > MAX_INPUT_BYTES:
                        raise ValueError("Input queue exceeds one MiB")
                    pending.extend(data)
                else:
                    raise ValueError("Unknown control command")
                response = {"accepted": True, "status": "cancelling" if stopping else "running"}
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                response = {"error": str(exc), "accepted": False}
            try:
                conn.sendall(json.dumps(response).encode() + b"\n")
            except OSError:
                pass

    try:
        bootstrap = json.loads(sys.stdin.buffer.read(256 * 1024 + 1))
        if bootstrap.get("protocol") == "claude-stream-json":
            if bootstrap["mode"] != "pipe":
                raise ValueError("Claude protocol requires a pipe stdout channel")
            from codex_harness_connect.protocols import ClaudeStreamParser
            native_parser = ClaudeStreamParser()
        control.bind(str(path))
        path.chmod(0o600)
        control.listen(8)
        control.setblocking(False)
        selector.register(control, selectors.EVENT_READ, "control")
        if bootstrap.get("auth_preflight") is not None:
            from codex_harness_connect.auth import require_subscription_route
            guard = bootstrap["auth_preflight"]
            if guard["kind"] != "claude-own-subscription":
                raise ValueError("Unknown native auth preflight")
            def preflight_cancelled():
                for key, _ in selector.select(0):
                    if key.data == "control":
                        handle_control()
                return signal_stop

            observation = require_subscription_route(
                bootstrap["argv"][0], bootstrap["cwd"], guard["expected_sha256"],
                cancel_requested=preflight_cancelled)
            with db:
                event(db, session_id, "auth_preflight", observation)
            # Drain cancellation queued during final identity/JSON/database work.
            preflight_cancelled()
        if signal_stop:
            with db:
                update(db, session_id, status="cancelled", finished_at=time.time(),
                       heartbeat=time.time(), input_closed=1)
                event(db, session_id, "exit", {"status": "cancelled", "exit_code": None})
            return
        if bootstrap["mode"] == "pty":
            master, slave = pty.openpty()
            proc = subprocess.Popen(bootstrap["argv"], cwd=bootstrap["cwd"],
                stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                preexec_fn=lambda: _tty_setup(slave))
            os.close(slave)
            slave = None
            input_fd = master
            outputs[master] = "pty"
        else:
            proc = subprocess.Popen(bootstrap["argv"], cwd=bootstrap["cwd"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, close_fds=True, bufsize=0)
            input_fd = proc.stdin.fileno()
            outputs = {proc.stdout.fileno(): "stdout", proc.stderr.fileno(): "stderr"}
        for fd, stream in outputs.items():
            os.set_blocking(fd, False)
            selector.register(fd, selectors.EVENT_READ, stream)
            decoders[stream] = codecs.getincrementaldecoder("utf-8")("replace")
        os.set_blocking(input_fd, False)
        with db:
            child_start = process_identity(proc.pid)
            update(db, session_id, status="running", worker_pid=os.getpid(),
                worker_start=process_identity(os.getpid()), heartbeat=time.time(),
                child_pid=proc.pid, child_start=child_start,
                process_members=json.dumps({str(proc.pid): child_start} if child_start else {}),
                process_group=proc.pid, started_at=time.time())
            event(db, session_id, "started", {"child_pid": proc.pid})
        secure_db_files(root)
        expires = time.monotonic() + bootstrap["timeout_seconds"]
        heartbeat_at = 0
        while True:
            now = time.monotonic()
            if now >= heartbeat_at:
                tracked.update(_descendants(os.getpid(), proc.pid))
                tracked = {pid: identity for pid, identity in tracked.items()
                           if process_identity(pid) == identity}
                with db:
                    update(db, session_id, heartbeat=time.time(), process_members=json.dumps(
                        {str(pid): identity for pid, identity in
                         tuple(tracked.items())[:MAX_TRACKED_PROCESSES]}),
                         process_members_truncated=int(len(tracked) > MAX_TRACKED_PROCESSES))
                heartbeat_at = now + 0.2
            if signal_stop:
                begin_stop("cancelled")
            if not stopping and now >= expires:
                begin_stop("timed_out")
            exit_code = proc.poll()
            if exit_code is not None and not stopping:
                begin_stop("completed" if exit_code == 0 else "failed")
            if stopping and now >= stop_deadline:
                tracked.update(_descendants(os.getpid(), proc.pid))
                _signal_group(proc.pid, signal.SIGKILL, tracked)
                _signal_tracked(tracked, signal.SIGKILL)
                proc.wait(timeout=2)
                break
            if pending and not input_closed and not stopping:
                try:
                    count = os.write(input_fd, pending[:16384])
                    del pending[:count]
                except BlockingIOError:
                    pass
                except OSError:
                    pending.clear()
                    input_closed = True
            if close_requested and not pending and not input_closed:
                if master is not None and not eof_queued:
                    # Canonical tty EOF; two EOFs also flush an unterminated line.
                    pending.extend(tty_eof * 2)
                    eof_queued = True
                else:
                    if master is None:
                        proc.stdin.close()
                    input_closed = True
                    with db:
                        update(db, session_id, input_closed=1)
            for key, _ in selector.select(0.02):
                if key.data == "control":
                    handle_control()
                    continue
                try:
                    data = os.read(key.fd, 4096)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    data = b""
                if data:
                    output(key.data, data)
                else:
                    selector.unregister(key.fd)
                    output(key.data, b"", final=True)
        # Drain bytes produced before termination and then flush incremental UTF-8.
        for fd, stream in outputs.items():
            while True:
                try:
                    data = os.read(fd, 4096)
                    if not data:
                        break
                    output(stream, data)
                except (OSError, BlockingIOError):
                    break
            output(stream, b"", final=True)
        for _ in range(20):
            _reap()
            if not _descendants(os.getpid()):
                break
            time.sleep(0.01)
        code = proc.returncode
        with db:
            if native_parser is not None:
                outcome = native_parser.finish(code)
                for item in outcome.pop("final_events"):
                    event(db, session_id, "native_protocol", item)
                if stopping in {"cancelled", "timed_out"}:
                    outcome["semantic_status"] = "unknown"
                update(db, session_id,
                       native_session_id=outcome["native_session_id"]
                       if outcome["identity_verified"] else None,
                       semantic_status=outcome["semantic_status"],
                       native_outcome=encoded(bounded_outcome(outcome)))
                event(db, session_id, "native_outcome", outcome)
            update(db, session_id, status=stopping, finished_at=time.time(),
                exit_code=code if code is not None and code >= 0 else None,
                exit_signal=-code if code is not None and code < 0 else None,
                heartbeat=time.time(), input_closed=1)
            event(db, session_id, "exit", {"status": stopping, "exit_code": code})
    except BaseException as exc:
        if proc is not None:
            tracked.update(_descendants(os.getpid(), proc.pid))
            _signal_group(proc.pid, signal.SIGKILL, tracked)
            _signal_tracked(tracked, signal.SIGKILL)
            proc.wait()
            _reap()
        with db:
            cancelled_before_launch = proc is None and signal_stop
            update(db, session_id, status="cancelled" if cancelled_before_launch else "failed",
                   error=None if cancelled_before_launch else f"{type(exc).__name__}: {exc}",
                   finished_at=time.time(), heartbeat=time.time(), input_closed=1)
            if cancelled_before_launch:
                event(db, session_id, "exit", {"status": "cancelled", "exit_code": None})
            else:
                event(db, session_id, "error", {"message": str(exc), "phase": "runtime" if proc else "startup"})
    finally:
        selector.close()
        control.close()
        for fd in (master, slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if proc is not None:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
        path.unlink(missing_ok=True)
        db.close()


if __name__ == "__main__":
    main()
