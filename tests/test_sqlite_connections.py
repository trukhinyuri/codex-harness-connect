"""Cross-process SQLite locking and deterministic connection lifetime regressions."""
import json
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import closing

import pytest

from codex_harness_connect import sessions
from codex_harness_connect.sessions import SessionService, connect_db


def exclusive_lock(path):
    # A separate process is essential: POSIX locks belong to a process, so a
    # second handle in this pytest process would not detect their cancellation.
    code = """
import errno, fcntl, json, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = {"locked": False}
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        result = {"locked": True}
    print(json.dumps(result))
finally:
    os.close(fd)
"""
    output = subprocess.check_output([sys.executable, "-c", code, str(path)],
                                     text=True, timeout=3)
    return json.loads(output)["locked"]


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_opening_existing_database_preserves_another_connection_lock(tmp_path, journal_mode):
    with closing(connect_db(tmp_path)) as holder:
        holder.execute("PRAGMA journal_mode=" + journal_mode)
        holder.execute("CREATE TABLE sample(value)")
        holder.commit()
        holder.execute("BEGIN")
        holder.execute("SELECT * FROM sample").fetchall()
        assert exclusive_lock(tmp_path / "sessions.sqlite3")
        with closing(connect_db(tmp_path)) as other:
            # No transaction on `other`: opening must preserve an already-held
            # lock even before this new connection executes its first query.
            assert exclusive_lock(tmp_path / "sessions.sqlite3")
            assert other.execute("SELECT * FROM sample").fetchall() == []
        assert exclusive_lock(tmp_path / "sessions.sqlite3")
        holder.rollback()


def test_reopening_database_does_not_admit_a_second_writer(tmp_path):
    code = """
import json, sqlite3, sys
with sqlite3.connect(sys.argv[1], timeout=0.05) as db:
    try:
        db.execute("INSERT INTO sample VALUES (2)")
        db.commit()
        print(json.dumps({"accepted": True}))
    except sqlite3.OperationalError as exc:
        print(json.dumps({"accepted": False, "code": exc.sqlite_errorcode}))
"""
    with closing(connect_db(tmp_path)) as holder:
        holder.execute("CREATE TABLE sample(value)")
        holder.commit()
        holder.execute("BEGIN IMMEDIATE")
        with closing(connect_db(tmp_path)):
            result = json.loads(subprocess.check_output(
                [sys.executable, "-c", code, str(tmp_path / "sessions.sqlite3")],
                text=True, timeout=3))
        assert result == {"accepted": False, "code": sqlite3.SQLITE_BUSY}
        holder.rollback()
        assert holder.execute("SELECT * FROM sample").fetchall() == []


def test_first_creation_closes_raw_descriptor_before_another_thread_opens_sqlite(tmp_path, monkeypatch):
    created = threading.Event()
    creation_closed = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()
    sqlite_opened_early = threading.Event()
    original_open = sessions.os.open
    original_close = sessions.os.close
    original_connect = sessions.sqlite3.connect
    errors = []
    first_fd = []

    def create(path, flags, mode=0o777):
        fd = original_open(path, flags, mode)
        if threading.current_thread().name == "create-first":
            first_fd.append(fd)
            created.set()
            if not release.wait(3):
                sessions.os.close(fd)
                raise RuntimeError("Creation barrier timed out")
        return fd

    def close(fd):
        original_close(fd)
        if first_fd == [fd]:
            creation_closed.set()

    def connect(*args, **kwargs):
        if threading.current_thread().name == "open-second" and not creation_closed.is_set():
            sqlite_opened_early.set()
        return original_connect(*args, **kwargs)

    def caller():
        try:
            if threading.current_thread().name == "open-second":
                second_entered.set()
            with closing(connect_db(tmp_path)) as db:
                db.execute("SELECT 1").fetchone()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(sessions.os, "open", create)
    monkeypatch.setattr(sessions.os, "close", close)
    monkeypatch.setattr(sessions.sqlite3, "connect", connect)
    first = threading.Thread(target=caller, name="create-first")
    second = threading.Thread(target=caller, name="open-second")
    try:
        first.start()
        assert created.wait(2)
        second.start()
        assert second_entered.wait(2)
        assert not sqlite_opened_early.wait(0.2)
    finally:
        release.set()
        first.join(3)
        if second.ident:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert creation_closed.is_set() and not sqlite_opened_early.is_set()
    assert not errors


def test_service_operations_close_connections_without_waiting_for_gc(tmp_path, monkeypatch):
    opened = []
    original = sessions.connect_db

    def record(root):
        db = original(root)
        opened.append(db)  # Keep a strong reference: GC cannot conceal a leak.
        return db

    monkeypatch.setattr(sessions, "connect_db", record)
    service = SessionService(tmp_path / "state")
    sid = uuid.uuid4().hex
    request = uuid.uuid4().hex
    with sessions.session_db(service.state_root) as db:
        db.execute("INSERT INTO sessions(session_id,status,mode,cwd,executable,created_at,request_id) "
                   "VALUES(?,?,?,?,?,?,?)", (sid, "completed", "pipe", str(tmp_path),
                                             "synthetic", time.time(), request))
    assert service.status(sid)["session"]["status"] == "completed"
    assert service.lookup_request(request)["session_id"] == sid
    assert len(service.list()) == 1
    with pytest.raises(KeyError, match="Unknown"):
        service.status(uuid.uuid4().hex)
    with pytest.raises(KeyError, match="Unknown"):
        service.lookup_request(uuid.uuid4().hex)
    assert len(opened) >= 7
    for db in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")


def test_session_db_commits_rolls_back_and_closes(tmp_path):
    with sessions.session_db(tmp_path) as committed:
        committed.execute("CREATE TABLE sample(value)")
        committed.execute("INSERT INTO sample VALUES(1)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        committed.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with sessions.session_db(tmp_path) as rolled_back:
            rolled_back.execute("INSERT INTO sample VALUES(2)")
            raise RuntimeError("synthetic failure")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        rolled_back.execute("SELECT 1")
    with sessions.session_db(tmp_path) as db:
        assert [row[0] for row in db.execute("SELECT * FROM sample")] == [1]


def test_private_database_creation_and_existing_symlink_rejection(tmp_path):
    with closing(connect_db(tmp_path)) as db:
        db.execute("CREATE TABLE sample(value)")
    path = tmp_path / "sessions.sqlite3"
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with closing(connect_db(tmp_path)):
        assert path.stat().st_mode & 0o777 == 0o600
    other = tmp_path / "other.sqlite3"
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(ValueError, match="regular file"):
        connect_db(tmp_path)
    assert path.is_symlink() and other.stat().st_mode & 0o777 == 0o600
