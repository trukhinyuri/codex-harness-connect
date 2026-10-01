"""Private, durable local sessions. Arbitrary launch is an internal adapter API."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

TERMINAL = frozenset({"completed", "failed", "cancelled", "timed_out", "lost"})
MAX_EVENTS = 1024
MAX_TOTAL_EVENTS = 10000
MAX_INPUT_BYTES = 1024 * 1024
MAX_TRACKED_PROCESSES = 2048
STARTUP_GRACE_SECONDS = 5
_ID = re.compile(r"[0-9a-f]{32}\Z")
_DB_FILE_LOCK = threading.Lock()


class _BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
        "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        "nfiles", "pgid", "jobc", "tdev", "tpgid", "nice")]
    _fields_ += [("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


def process_identity(pid: int | None) -> str | None:
    """Check kernel process identity, including zombie state, without shell/ps."""
    if not pid:
        return None
    try:
        if sys.platform.startswith("linux"):
            parts = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return None if parts[0] == "Z" else "linux:" + parts[19]
        if sys.platform == "darwin":
            info = _BSDInfo()
            lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if size == ctypes.sizeof(info) and info.status != 5:
                return f"darwin:{info.start_sec}:{info.start_usec}"
    except (OSError, ValueError, IndexError):
        pass
    return None


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("State directory cannot be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise ValueError("State directory is owned by another user")
    path.chmod(0o700)


def socket_path(root: Path, session_id: str) -> Path:
    # macOS AF_UNIX paths are short; socket contents never leave this private dir.
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    directory = Path("/tmp") / f"chc-{os.getuid()}-{digest}"
    private_directory(directory)
    return directory / f"{session_id}.sock"


def connect_db(root: Path) -> sqlite3.Connection:
    """Open a caller-owned connection without disturbing SQLite's file locks."""
    path = root / "sessions.sqlite3"
    # Do not publish a new database to another connect_db thread until its
    # creation descriptor is closed; a close in this process also drops locks
    # acquired by a different thread. Different processes have separate locks.
    with _DB_FILE_LOCK:
        try:
            # Closing any independently opened descriptor of an existing database
            # drops every POSIX advisory lock this process holds on that inode.
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("State database must be a regular file owned by this user")
            path.chmod(0o600)
        else:
            os.close(fd)
    db = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=0.1)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=100")
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def session_db(root: Path):
    """Commit or roll back a service operation and always close its connection."""
    db = connect_db(root)
    try:
        with db:
            yield db
    finally:
        db.close()


def secure_db_files(root: Path) -> None:
    for name in ("sessions.sqlite3", "sessions.sqlite3-wal", "sessions.sqlite3-shm"):
        try:
            (root / name).chmod(0o600)
        except FileNotFoundError:
            pass


def event(db: sqlite3.Connection, session_id: str, kind: str, data: dict) -> None:
    db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,?,?,?)",
               (session_id, kind, json.dumps(data, ensure_ascii=False), time.time()))
    cutoff = db.execute("SELECT cursor FROM events WHERE session_id=? "
                        "ORDER BY cursor DESC LIMIT 1 OFFSET ?", (session_id, MAX_EVENTS)).fetchone()
    if cutoff:
        db.execute("UPDATE sessions SET discarded_until=MAX(discarded_until,?) WHERE session_id=?",
                   (cutoff[0], session_id))
        db.execute("DELETE FROM events WHERE session_id=? AND cursor<=?", (session_id, cutoff[0]))
    cutoff = db.execute("SELECT cursor FROM events ORDER BY cursor DESC LIMIT 1 OFFSET ?",
                        (MAX_TOTAL_EVENTS,)).fetchone()
    if cutoff:
        dropped = db.execute("SELECT session_id,MAX(cursor) FROM events WHERE cursor<=? "
                             "GROUP BY session_id", (cutoff[0],)).fetchall()
        db.executemany("UPDATE sessions SET discarded_until=MAX(discarded_until,?) WHERE session_id=?",
                       [(cursor, sid) for sid, cursor in dropped])
        db.execute("DELETE FROM events WHERE cursor<=?", (cutoff[0],))


def update(db: sqlite3.Connection, session_id: str, **fields) -> None:
    keys = tuple(fields)
    db.execute("UPDATE sessions SET " + ",".join(f"{key}=?" for key in keys)
               + " WHERE session_id=?", (*fields.values(), session_id))


class SessionService:
    def __init__(self, state_root: Path):
        state_root = Path(state_root).expanduser().absolute()
        private_directory(state_root)
        self.state_root = state_root.resolve()
        with session_db(self.state_root) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    mode TEXT NOT NULL, cwd TEXT NOT NULL, executable TEXT NOT NULL,
                    created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                    worker_pid INTEGER, worker_start TEXT, heartbeat REAL,
                    child_pid INTEGER, child_start TEXT, process_group INTEGER,
                    exit_code INTEGER, exit_signal INTEGER, native_session_id TEXT,
                    error TEXT, input_closed INTEGER NOT NULL DEFAULT 0,
                    discarded_until INTEGER NOT NULL DEFAULT 0,
                    process_members TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, kind TEXT NOT NULL,
                    data TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS events_session ON events(session_id,cursor);
            """)
            if "discarded_until" not in {row[1] for row in db.execute("PRAGMA table_info(sessions)")}:
                db.execute("ALTER TABLE sessions ADD COLUMN discarded_until INTEGER NOT NULL DEFAULT 0")
            if "process_members" not in {row[1] for row in db.execute("PRAGMA table_info(sessions)")}:
                db.execute("ALTER TABLE sessions ADD COLUMN process_members TEXT NOT NULL DEFAULT '{}'")
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            for column in ("request_id", "launch_fingerprint", "protocol", "semantic_status"):
                if column not in columns:
                    db.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS sessions_request ON sessions(request_id)")
        secure_db_files(self.state_root)

    @staticmethod
    def _id(session_id: str) -> str:
        if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
            raise ValueError("Invalid session ID")
        return session_id

    def _session(self, db, session_id: str) -> dict:
        row = db.execute("SELECT * FROM sessions WHERE session_id=?",
                         (self._id(session_id),)).fetchone()
        if row is None:
            raise KeyError("Unknown session ID")
        result = dict(row)
        identity = process_identity(result["worker_pid"])
        result["worker_alive"] = bool(identity and identity == result["worker_start"])
        confirmed_dead = bool(result["worker_pid"] and result["worker_start"] and
                              identity != result["worker_start"])
        startup_expired = time.time() - result["created_at"] >= STARTUP_GRACE_SECONDS
        if (result["status"] not in TERMINAL and not result["worker_alive"]
                and (confirmed_dead or result["started_at"] or startup_expired)):
            changed = db.execute("UPDATE sessions SET status='lost',error=?,finished_at=? "
                                 "WHERE session_id=? AND status NOT IN "
                                 "('completed','failed','cancelled','timed_out','lost')",
                                 ("Worker exited without recording its final state", time.time(), session_id))
            if changed.rowcount:
                event(db, session_id, "worker_lost", {"exit_unknown": True})
            result = dict(db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
            result["worker_alive"] = False
        result["heartbeat_fresh"] = bool(result["heartbeat"] and
                                          time.time() - result["heartbeat"] < 5)
        result["process_members"] = json.loads(result["process_members"])
        result["live"] = bool(result["worker_alive"] and result["heartbeat_fresh"]
                              and result["status"] not in TERMINAL)
        result["termination_scope"] = "native leader and observed descendants; not full OS containment"
        result["full_process_containment_verified"] = False
        return result

    def start(self, argv: list[str], cwd: str, mode: str = "pipe",
              env_overrides: dict[str, str] | None = None,
              timeout_seconds: int = 3600, request_id: str | None = None,
              protocol: str | None = None) -> dict:
        if (not isinstance(argv, list) or not argv or any(
                not isinstance(x, str) or not x or "\0" in x for x in argv)):
            raise ValueError("argv must be a nonempty list of nonempty strings")
        if mode not in ("pipe", "pty") or sys.platform not in ("linux", "darwin"):
            raise ValueError("Mode must be pipe or pty on Linux or macOS")
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or "\0" in cwd:
            raise ValueError("cwd must be an absolute path")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 86400):
            raise ValueError("timeout_seconds must be positive and at most 86400")
        overrides = {} if env_overrides is None else env_overrides
        if not isinstance(overrides, dict) or any(
                not isinstance(k, str) or not k or "=" in k or "\0" in k
                or not isinstance(v, str) or "\0" in v for k, v in overrides.items()):
            raise ValueError("Invalid environment overrides")
        if request_id is not None:
            self._id(request_id)
        if protocol not in (None, "claude-stream-json") or (protocol and mode != "pipe"):
            raise ValueError("Unsupported native output protocol for this mode")
        bootstrap = json.dumps({"argv": argv, "cwd": cwd, "mode": mode,
                                "timeout_seconds": timeout_seconds, "protocol": protocol}).encode()
        if len(bootstrap) > 256 * 1024:
            raise ValueError("Launch arguments are too large")
        session_id = uuid.uuid4().hex
        fingerprint = hashlib.sha256(bootstrap + json.dumps(overrides, sort_keys=True).encode()).hexdigest()
        with session_db(self.state_root) as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id:
                previous = db.execute("SELECT session_id,launch_fingerprint FROM sessions "
                                      "WHERE request_id=?", (request_id,)).fetchone()
                if previous:
                    if previous["launch_fingerprint"] != fingerprint:
                        raise ValueError("Request ID already belongs to a different launch")
                    return self._session(db, previous["session_id"])
            db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at,"
                       "request_id,launch_fingerprint,protocol,semantic_status) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (session_id, "starting", mode, cwd,
                       Path(argv[0]).name, time.time(), request_id, fingerprint, protocol, "unknown"))
            event(db, session_id, "created", {"mode": mode})
        env = os.environ.copy()
        env.update(overrides)
        worker = None
        try:
            worker = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("worker.py")),
                 str(self.state_root), session_id], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True, env=env)
            with session_db(self.state_root) as db:
                update(db, session_id, worker_pid=worker.pid,
                       worker_start=process_identity(worker.pid))
            worker.stdin.write(bootstrap)
            worker.stdin.close()
            threading.Thread(target=worker.wait, name=f"session-reaper-{session_id}",
                             daemon=True).start()
            # A bounded startup handshake reports launch failure honestly.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result = self.status(session_id)["session"]
                if result["status"] != "starting":
                    return result
                if worker.poll() is not None:
                    raise RuntimeError(f"Session worker exited during startup ({worker.returncode})")
                time.sleep(0.01)
            return self.status(session_id)["session"]
        except Exception as exc:
            if worker is not None and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
            with session_db(self.state_root) as db:
                update(db, session_id, status="failed", error=str(exc), finished_at=time.time())
                event(db, session_id, "error", {"message": str(exc), "phase": "startup"})
            return self.status(session_id)["session"]
        finally:
            # Popen's poll reaps already completed workers; running workers detach.
            if worker is not None:
                worker.poll()

    def status(self, session_id: str, after: int = 0, limit: int = 100) -> dict:
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError("after must be a nonnegative event cursor")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with session_db(self.state_root) as db:
            session = self._session(db, session_id)
            rows = db.execute("SELECT * FROM events WHERE session_id=? AND cursor>? "
                              "ORDER BY cursor LIMIT ?", (session_id, after, limit)).fetchall()
            first = db.execute("SELECT MIN(cursor) FROM events WHERE session_id=?",
                               (session_id,)).fetchone()[0]
        events = [{**dict(row), "data": json.loads(row["data"])} for row in rows]
        return {"session": session, "events": events,
                "next_cursor": events[-1]["cursor"] if events else after,
                "earliest_cursor": first, "truncated": after < session["discarded_until"]}

    def list(self) -> list[dict]:
        with session_db(self.state_root) as db:
            ids = db.execute("SELECT session_id FROM sessions ORDER BY created_at DESC").fetchall()
            return [self._session(db, row[0]) for row in ids]

    def lookup_request(self, request_id: str) -> dict:
        """Recover the durable job after an uncertain MCP response; never launch again."""
        with session_db(self.state_root) as db:
            row = db.execute("SELECT session_id FROM sessions WHERE request_id=?",
                             (self._id(request_id),)).fetchone()
            if row is None:
                raise KeyError("Unknown request ID")
            return self._session(db, row[0])

    def _control(self, session_id: str, command: str, text: str = "") -> dict:
        session = self.status(session_id)["session"]
        if session["status"] in TERMINAL:
            if command == "cancel":
                return {"session_id": session_id, "accepted": False, "status": session["status"]}
            raise RuntimeError("Terminal session does not accept input")
        if not session["worker_alive"]:
            raise RuntimeError("Session worker is not alive")
        payload = json.dumps({"command": command, "text": text}).encode() + b"\n"
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("Input exceeds one MiB")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            try:
                client.connect(str(socket_path(self.state_root, session_id)))
                client.sendall(payload)
                response = bytearray()
                while b"\n" not in response and len(response) < 4096:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
            except (OSError, TimeoutError) as exc:
                raise RuntimeError("Session worker control is unavailable") from exc
        try:
            result = json.loads(response)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Invalid worker control response") from exc
        if "error" in result:
            raise RuntimeError(result["error"])
        return {"session_id": session_id, **result}

    def send(self, session_id: str, text: str) -> dict:
        if not isinstance(text, str):
            raise ValueError("Input must be text")
        return self._control(session_id, "send", text)

    def cancel(self, session_id: str) -> dict:
        session = self.status(session_id)["session"]
        if session["status"] == "lost":
            return self._cancel_lost(session)
        return self._control(session_id, "cancel")

    def _cancel_lost(self, session: dict) -> dict:
        """Recover cancellation without relaunching the native harness."""
        from .worker import _descendants, _signal_group, _signal_tracked
        sid, group = session["session_id"], session["process_group"]
        known = {int(pid): identity for pid, identity in session["process_members"].items()}
        if session["child_pid"] and session["child_start"]:
            known[session["child_pid"]] = session["child_start"]

        def confirmed_group():
            for pid, identity in tuple(known.items()):
                if process_identity(pid) == identity:
                    try:
                        if os.getpgid(pid) == group:
                            return True
                    except ProcessLookupError:
                        pass
            return False

        def observe():
            # A saved, still-live member in this PG proves the original group has
            # not been replaced. Never infer membership from a numeric PG alone.
            if group and confirmed_group():
                known.update(_descendants(-1, group))
            return {pid: identity for pid, identity in known.items()
                    if process_identity(pid) == identity}

        live = observe()
        if not live:
            return {"session_id": sid, "accepted": False, "status": "lost",
                    "reason": "No saved process identity is live; unobserved descendants are unknown"}
        with session_db(self.state_root) as db:
            event(db, sid, "stop_requested", {"reason": "cancelled", "cleanup": "lost_worker"})
        try:
            if group and confirmed_group():
                _signal_group(group, signal.SIGTERM, known)
            _signal_tracked(live, signal.SIGTERM)
            time.sleep(0.35)
            live = observe()
            # The group signal also catches forks during cancellation. Its lease
            # is checked immediately before signaling; reused PIDs are excluded.
            if group and confirmed_group():
                _signal_group(group, signal.SIGKILL, known)
            _signal_tracked(live, signal.SIGKILL)
            deadline = time.monotonic() + 1
            while observe() and time.monotonic() < deadline:
                time.sleep(0.01)
            remaining = observe()
            if remaining:
                raise RuntimeError("Confirmed processes remain alive after cancellation")
        except (OSError, RuntimeError) as exc:
            with session_db(self.state_root) as db:
                update(db, sid, error=f"Lost-worker cleanup failed: {exc}")
                event(db, sid, "error", {"message": str(exc), "phase": "lost_worker_cleanup"})
            raise RuntimeError("Lost-worker cleanup failed") from exc
        with session_db(self.state_root) as db:
            update(db, sid, status="cancelled", finished_at=time.time(), input_closed=1,
                   error="Worker was lost; confirmed native processes were cancelled; exit is unknown")
            event(db, sid, "exit", {"status": "cancelled", "exit_unknown": True,
                                   "cleanup": "lost_worker"})
        socket_path(self.state_root, sid).unlink(missing_ok=True)
        return {"session_id": sid, "accepted": True, "status": "cancelled", "exit_unknown": True}

    def close_input(self, session_id: str) -> dict:
        return self._control(session_id, "close_input")
