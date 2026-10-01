"""Non-inference CLI inventory. Help is evidence, never executable instructions."""
from __future__ import annotations

import errno
import hashlib
import os
import pty
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

MAX_OUTPUT = 256_000
PROBE_TIMEOUT_SECONDS = 15
STOP_GRACE_SECONDS = 0.2
STOP_KILL_SECONDS = 1
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024


def file_fingerprint(path: Path, max_bytes: int = MAX_EXECUTABLE_BYTES) -> dict:
    """Hash one bounded regular file and reject replacement/change while reading."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ValueError("Fingerprint requires a bounded regular file")
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(min(1024 * 1024, max_bytes + 1 - size)):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("File exceeds the fingerprint size limit")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_mode)
    if identity(before) != identity(after) or identity(after) != identity(path.stat()):
        raise ValueError("File identity changed while fingerprinting; inventory again explicitly")
    return {"resolved_path": str(path), "sha256": digest.hexdigest(), "size_bytes": size,
            "device": after.st_dev, "inode": after.st_ino,
            "mtime_ns": after.st_mtime_ns, "ctime_ns": after.st_ctime_ns,
            "mode": stat.S_IMODE(after.st_mode)}


def resolve_executable(executable: str) -> Path:
    if not executable or "\x00" in executable or len(executable) > 4096:
        raise ValueError("Invalid executable")
    candidate = shutil.which(executable)
    if not candidate:
        raise FileNotFoundError(f"Executable not found: {executable}")
    resolved = Path(candidate).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("Executable must be an executable regular file")
    return resolved


def _probe(path: Path, flag: str, *, transport: str = "pipe") -> dict:
    # A bounded pipe avoids both unbounded RAM and unbounded temporary files.
    if not isinstance(transport, str) or transport not in {"pipe", "pty"}:
        raise ValueError("Unknown inventory transport")
    master = slave = None
    try:
        if transport == "pty":
            master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(path), flag], stdin=subprocess.DEVNULL,
            stdout=slave if slave is not None else subprocess.PIPE,
            stderr=slave if slave is not None else subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    except BaseException:
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)
        raise
    if slave is not None:
        os.close(slave)
    output_fd = master if master is not None else process.stdout.fileno()
    raw = bytearray()
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS

    def kill_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can report EPERM for an already finished group.
            if process.poll() is None:
                raise

    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(output_fd, False)
            selector.register(output_fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{flag} probe exceeded {PROBE_TIMEOUT_SECONDS} seconds")
                if not selector.select(min(remaining, 0.05)):
                    continue
                try:
                    chunk = os.read(output_fd, min(65536, MAX_OUTPUT + 1 - len(raw)))
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if transport != "pty" or exc.errno != errno.EIO:
                        raise
                    chunk = b""
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_OUTPUT:
                    raise ValueError("Help/version exceeds the inventory size limit")
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"{flag} probe exceeded {PROBE_TIMEOUT_SECONDS} seconds") from None
    finally:
        try:
            kill_group(signal.SIGTERM)
            try:
                process.wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        finally:
            try:
                kill_group(signal.SIGKILL)
            finally:
                try:
                    process.wait(timeout=STOP_KILL_SECONDS)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Probe process did not exit after SIGKILL") from None
                finally:
                    if master is not None:
                        os.close(master)
                    else:
                        process.stdout.close()
    return {"exit_code": process.returncode, "text": raw.decode("utf-8", errors="replace")}


def inventory(executable: str, *, help_transport: str = "pipe") -> dict:
    """Only call for a user-designated, trusted installed CLI. No model requests."""
    if not isinstance(help_transport, str) or help_transport not in {"pipe", "pty"}:
        raise ValueError("Unknown inventory transport")
    path = resolve_executable(executable)
    identity = file_fingerprint(path)

    def assert_unchanged():
        try:
            current_path = resolve_executable(executable)
            current = file_fingerprint(current_path)
        except (OSError, ValueError) as exc:
            raise ValueError("CLI identity changed during probes; inventory again explicitly") from exc
        if current != identity:
            raise ValueError("CLI identity changed during probes; inventory again explicitly")

    version = _probe(path, "--version")
    assert_unchanged()
    help_result = (_probe(path, "--help") if help_transport == "pipe" else
                   _probe(path, "--help", transport=help_transport))
    assert_unchanged()
    help_text = help_result["text"]
    # Retain raw evidence, but terminal styling must not hide a real flag token.
    plain_help = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", help_text)
    flags = sorted(set(re.findall(r"(?<![\w-])--[A-Za-z][A-Za-z0-9_-]*", plain_help)))
    short_flags = sorted(set(re.findall(r"(?<![\w-])-[A-Za-z0-9](?![\w-])", plain_help)))
    return {
        "schema_version": 1,
        "observed_at": datetime.now(UTC).isoformat(),
        "executable": executable,
        "resolved_path": str(path),
        "binary_sha256": identity["sha256"],
        "binary_identity": identity,
        "version": version,
        "help": help_result,
        "help_transport": help_transport,
        "help_sha256": hashlib.sha256(help_text.encode()).hexdigest(),
        "flags": flags,
        "short_flags": short_flags,
        "claim": "Top-level help inventory only; not proof of complete feature coverage or permission",
    }
