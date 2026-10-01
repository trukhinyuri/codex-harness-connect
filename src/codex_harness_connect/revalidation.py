"""Fresh, bounded local compatibility observations; never acceptance or permission."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import stat
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .adapters import get_adapter
from .discovery import (
    MAX_EXECUTABLE_BYTES,
    MAX_OUTPUT,
    PROBE_TIMEOUT_SECONDS,
    file_fingerprint,
    inventory,
)

SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
LOCK_TIMEOUT_SECONDS = 5
DESKTOP_APP_PATHS = (
    Path("/Applications/Codex.app"), Path("/Applications/ChatGPT.app"),
    Path.home() / "Applications/Codex.app", Path.home() / "Applications/ChatGPT.app",
)
BUNDLED_CLI_PATHS = ("Contents/Resources/codex-cli/bin/codex",
                     "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
                     "Contents/Resources/codex-cli", "Contents/Resources/codex",
                     "Contents/Resources/bin/codex", "Contents/MacOS/codex")
SOURCE_FILES = ("__init__.py", "__main__.py", "adapters.py", "auth.py", "cli.py", "discovery.py", "grok.py", "plugins.py",
                "protocols.py", "revalidation.py", "server.py", "sessions.py", "worker.py",
                "waiting.py", "worktrees.py", "storage.py", "history.py", "elicitation.py")
DEPENDENCIES = ("mcp", "pydantic", "pydantic-settings", "anyio", "httpx", "httpx-sse",
                "starlette", "sse-starlette", "uvicorn", "jsonschema", "typing-extensions")
ACCEPTANCE_GATES = {
    "policy_billing": "Current vendor terms, effective subscription/auth route and no paid fallback",
    "native_protocol": "Actual installed CLI results and typed protocol/output schema",
    "approvals": "Native denial and explicit approval behavior without bypass",
    "resume": "Verified native conversation identity and same-workspace resume",
    "cancel_reconnect": "Cancellation, terminal state, uncertain outcomes and cursor reconnect",
    "worktrees_teams": "Concurrent worktrees and native teams in each claimed mode",
    "desktop_ui": "Actual loaded tools, skills, approval interactions and Desktop user experience",
    "host_context_memory_cloud": "Explicit task-context transfer and measured memory/Cloud boundaries",
}


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _without_timestamps(value):
    if isinstance(value, dict):
        return {key: _without_timestamps(item) for key, item in value.items()
                if key != "observed_at"}
    if isinstance(value, list):
        return [_without_timestamps(item) for item in value]
    return value


def _observe_cli(executable: str, help_transport: str = "pipe") -> dict:
    try:
        current = (inventory(executable) if help_transport == "pipe" else
                   inventory(executable, help_transport=help_transport))
    except FileNotFoundError:
        return {"status": "unavailable", "executable": executable,
                "reason": "Executable is absent or disappeared during observation"}
    except (OSError, ValueError, TimeoutError, RuntimeError) as exc:
        return {"status": "unknown", "executable": executable,
                "reason": f"{type(exc).__name__}: bounded inventory could not establish identity"}
    successful = current["version"]["exit_code"] == current["help"]["exit_code"] == 0
    version_text = current["version"]["text"]
    help_text = current["help"]["text"]
    compact = {key: value for key, value in current.items()
               if key not in {"version", "help", "flags", "short_flags"}}
    compact.update(
        version={"exit_code": current["version"]["exit_code"], "text": version_text[:256],
                 "sha256": hashlib.sha256(version_text.encode()).hexdigest(),
                 "characters": len(version_text), "text_truncated": len(version_text) > 256},
        help={"exit_code": current["help"]["exit_code"], "sha256": current["help_sha256"],
              "characters": len(help_text), "text_omitted": True},
        flags=[flag[:80] for flag in current["flags"][:48]],
        flags_sha256=_digest(current["flags"]), flags_count=len(current["flags"]),
        flags_truncated=len(current["flags"]) > 48 or any(len(flag) > 80 for flag in current["flags"]),
        short_flags=current["short_flags"],
    )
    result = {"status": "observed" if successful else "unknown", "inventory": compact,
              "reason": "Fresh local version/help evidence only" if successful else "CLI probes failed"}
    if successful:
        result["expected_sha256"] = current["binary_sha256"]
    return result


def _observe_file(path: Path, max_bytes: int = MAX_EXECUTABLE_BYTES) -> dict:
    try:
        resolved = path.resolve(strict=True)
        return {"status": "observed", **file_fingerprint(resolved, max_bytes)}
    except FileNotFoundError:
        return {"status": "unavailable", "path": str(path), "reason": "File is absent"}
    except (OSError, ValueError) as exc:
        return {"status": "unknown", "path": str(path),
                "reason": f"{type(exc).__name__}: file identity could not be established"}


def _desktop() -> dict:
    if sys.platform != "darwin":
        return {"status": "unavailable", "reason": "macOS Desktop is not observable on this host",
                "candidates": []}
    candidates = []
    for app in DESKTOP_APP_PATHS:
        entry = {"path": str(app)}
        metadata_path = app / "Contents/Info.plist"
        metadata_identity = _observe_file(metadata_path, MAX_METADATA_BYTES)
        if metadata_identity["status"] != "observed":
            candidates.append({**entry, **metadata_identity})
            continue
        try:
            # Only this public bundle metadata is read; no user configuration is inspected.
            fd = os.open(metadata_identity["resolved_path"],
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Bundle metadata must remain a regular file")
                raw = stream.read(MAX_METADATA_BYTES + 1)
            if len(raw) > MAX_METADATA_BYTES or hashlib.sha256(raw).hexdigest() != (
                    metadata_identity["sha256"]) or _observe_file(
                        metadata_path, MAX_METADATA_BYTES) != metadata_identity:
                raise ValueError("Bundle metadata changed or exceeded its bound")
            metadata = plistlib.loads(raw)
            if not isinstance(metadata, dict):
                raise ValueError("Bundle metadata is not a dictionary")
            keys = ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion",
                    "CFBundleExecutable", "CFBundleName")
            public = {key: metadata[key] for key in keys if key in metadata
                      and isinstance(metadata[key], str) and len(metadata[key]) <= 256}
            if public.get("CFBundleIdentifier") != "com.openai.codex":
                candidates.append({**entry, "status": "unavailable", "metadata": public,
                                   "reason": "Known path does not identify a Codex Desktop bundle"})
                continue
            entry.update(status="observed", metadata=public, metadata_identity=metadata_identity)
            executable = public.get("CFBundleExecutable", "")
            if executable and Path(executable).name == executable and executable not in {".", ".."}:
                entry["main_executable"] = _observe_file(app / "Contents/MacOS" / executable)
            else:
                entry["main_executable"] = {"status": "unknown",
                                            "reason": "Bundle executable metadata is unavailable"}
            bundled = next((app / relative for relative in BUNDLED_CLI_PATHS
                            if (app / relative).is_file()), None)
            entry["bundled_codex"] = (_observe_cli(str(bundled)) if bundled else
                                      {"status": "unavailable", "reason": "Known bundled CLI absent"})
        except (OSError, ValueError, plistlib.InvalidFileException) as exc:
            entry = {**entry, "status": "unknown",
                     "reason": f"{type(exc).__name__}: bounded bundle metadata could not be read"}
        candidates.append(entry)
    matching = any(item["status"] == "observed" for item in candidates)
    return {"status": "observed" if matching else "unavailable", "candidates": candidates,
            "claim": "Installed bundle evidence only; updater/latest state and running UI not observed"}


def _runtime() -> dict:
    source_root = Path(__file__).parent
    sources = {name: _observe_file(source_root / name, MAX_SOURCE_BYTES) for name in SOURCE_FILES}
    versions = {}
    for name in ("codex-harness-connect", *DEPENDENCIES):
        try:
            version = importlib.metadata.version(name)
            versions[name] = {"status": "observed", "version": version[:256]}
        except importlib.metadata.PackageNotFoundError:
            versions[name] = {"status": "unavailable", "reason": "Distribution metadata absent"}
    return {
        "claim": "On-disk connector source hashes and distribution versions; loaded code is not attested",
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation(),
                   "executable": _observe_file(Path(sys.executable)), "platform": sys.platform,
                   "system_release": platform.release(), "machine": platform.machine()},
        "package": {"source_version": __version__, "distributions": versions},
        "sources": sources,
        "api_contract": {
            "verification": "Source/version observations only; loaded MCP tools and live API require host readback",
            "observation_schema": SCHEMA_VERSION,
            "transport": "Local MCP stdio through the installed Python mcp package",
            "server_source_sha256": sources["server.py"].get("sha256"),
            "adapter_source_sha256": sources["adapters.py"].get("sha256"),
            "mcp_distribution": versions["mcp"],
            "desktop_app_server_plugin_api": "Experimental; not probed or a production client contract",
            "mandatory_acceptance_gates": list(ACCEPTANCE_GATES),
        },
    }


def _identity_gaps(target: dict, host: dict, runtime: dict) -> list[str]:
    gaps = []
    for name, item in (("target_cli", target), ("host_path_codex", host["path_codex"])):
        if item.get("status") != "observed":
            gaps.append(name)
    desktop = host["desktop"]
    if desktop.get("status") != "observed":
        gaps.append("host_desktop")
    else:
        for entry in desktop.get("candidates", []):
            if entry.get("status") == "observed":
                for name in ("main_executable", "bundled_codex"):
                    if entry.get(name, {}).get("status") != "observed":
                        gaps.append(f"host_desktop.{name}")
    if runtime.get("python", {}).get("executable", {}).get("status") != "observed":
        gaps.append("runtime_python.executable")
    for name, item in runtime.get("sources", {}).items():
        if item.get("status") != "observed":
            gaps.append(f"runtime_sources.{name}")
    for name, item in runtime.get("package", {}).get("distributions", {}).items():
        if item.get("status") != "observed":
            gaps.append(f"runtime_package.distributions.{name}")
    return sorted(set(gaps))


def _safe_info(info, *, directory: bool = False, private: bool = True) -> None:
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Ledger path must be a caller-owned regular file or directory")
    if info.st_mode & (0o077 if private else 0o022):
        raise ValueError("Ledger path permissions are unsafe")
    if not directory and (info.st_nlink != 1 or info.st_size > MAX_SNAPSHOT_BYTES):
        raise ValueError("Ledger file has unsafe links or exceeds the size limit")


def _safe_entry(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _safe_info(info)
    return info


@contextmanager
def _ledger(state_root: Path, adapter: str):
    root = Path(state_root).expanduser().absolute()
    if ".." in root.parts:
        raise ValueError("Ledger paths cannot contain parent traversal")
    directory_fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    try:
        for index, part in enumerate((*root.parts[1:], "revalidation", adapter)):
            try:
                os.mkdir(part, 0o700, dir_fd=directory_fd)
            except FileExistsError:
                pass
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
            if index >= len(root.parts) - 2:
                _safe_info(os.fstat(directory_fd), directory=True,
                           private=index >= len(root.parts) - 1)
        _safe_entry(directory_fd, "latest.json")
        _safe_entry(directory_fd, "observation.lock")
        lock_fd = os.open("observation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                          0o600, dir_fd=directory_fd)
        _safe_info(os.fstat(lock_fd))
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another revalidation holds the bounded observation lock") from None
                time.sleep(0.05)
        yield directory_fd, root / "revalidation" / adapter / "latest.json"
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


def _previous(directory_fd: int, adapter: str) -> tuple[dict | None, str]:
    if _safe_entry(directory_fd, "latest.json") is None:
        return None, "no_prior_observation"
    fd = os.open("latest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        _safe_info(os.fstat(fd))
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        value = json.loads(raw, parse_constant=lambda _: None)
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION
                or value.get("adapter") != adapter or not isinstance(value.get("observed_at"), str)):
            raise ValueError("Invalid prior observation schema")
        fingerprint = value["fingerprint"]
        if (not isinstance(fingerprint, dict) or not isinstance(fingerprint["components"], dict)
                or not fingerprint["components"]
                or any(not isinstance(value, str) or len(value) != 64
                       or any(character not in "0123456789abcdef" for character in value)
                       for value in fingerprint["components"].values())
                or fingerprint["sha256"] != _digest(fingerprint["components"])):
            raise ValueError("Invalid prior fingerprint")
        return value, "available"
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return None, "corrupt_prior_observation"
    finally:
        if fd is not None:
            os.close(fd)


def _save(directory_fd: int, value: dict) -> None:
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(raw) > min(MAX_SNAPSHOT_BYTES, MAX_REPORT_BYTES):
        raise ValueError("Observation exceeds the snapshot size limit; no snapshot was replaced")
    name = f".latest-{uuid.uuid4().hex}.tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_entry(directory_fd, "latest.json")
        os.replace(name, "latest.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def revalidate(adapter: str, state_root: Path) -> dict:
    """Always observe again; persist evidence without carrying forward any qualification."""
    selected = get_adapter(adapter)
    started = time.monotonic()
    with _ledger(state_root, adapter) as (directory_fd, snapshot_path):
        previous, previous_status = _previous(directory_fd, adapter)
        # Independent non-inference probes overlap; each inventory retains its own identity checks.
        with ThreadPoolExecutor(max_workers=3) as executor:
            target_future = executor.submit(_observe_cli, selected.executable, selected.help_transport)
            path_future = executor.submit(_observe_cli, "codex")
            desktop_future = executor.submit(_desktop)
            runtime = _runtime()
            target = target_future.result()
            path_codex = path_future.result()
            desktop = desktop_future.result()
        host = {"path_codex": path_codex, "desktop": desktop,
                "running_desktop_ui": {"status": "unknown", "reason": "Not inspected by this probe"},
                "current_host_tool_loading": {"status": "unknown", "reason": "Requires host MCP readback"}}
        policy = {"policy": selected.policy, "sources": list(selected.sources), "notes": selected.notes,
                  "hold_preserved": selected.policy != "personal-unmodified-cli"}
        components = {key: _digest(_without_timestamps(value)) for key, value in {
            "target_cli": target, "adapter_policy": policy, "host_path_codex": host["path_codex"],
            "host_desktop": host["desktop"],
            **{f"runtime_{key}": value for key, value in runtime.items()}}.items()}
        fingerprint = {"sha256": _digest(components), "components": components}
        old_components = previous["fingerprint"]["components"] if previous else {}
        changed = sorted(key for key in components.keys() | old_components.keys()
                         if components.get(key) != old_components.get(key))
        comparison_status = ("changed" if changed else "unchanged") if previous else previous_status
        identity_gaps = _identity_gaps(target, host, runtime)
        result = {
            "schema_version": SCHEMA_VERSION, "adapter": adapter,
            "observed_at": datetime.now(UTC).isoformat(), "target_inventory": target,
            "adapter_policy": policy, "host": host, "runtime": runtime, "fingerprint": fingerprint,
            "comparison": {"status": comparison_status, "changed_components": changed,
                           "previous_observed_at": previous["observed_at"] if previous else None,
                           "previous_fingerprint": previous["fingerprint"]["sha256"] if previous else None,
                           "identity_gaps": identity_gaps,
                           "prior_qualification_invalidated": bool(changed) or previous is None
                           or bool(identity_gaps)},
            "qualification": {"status": "incomplete", "production_verified": False,
                              "desktop_parity": "not established", "prior_qualification_carried_forward": False,
                              "claim": "Fresh alpha compatibility evidence only; no acceptance gate is proven"},
            "mandatory_acceptance_gates": [{"gate": gate, "required_evidence": evidence,
                                            "status": ("blocked_by_existing_policy_hold" if gate == "policy_billing"
                                                       and policy["hold_preserved"] else "required_not_tested")}
                                           for gate, evidence in ACCEPTANCE_GATES.items()],
            "bounds": {"probe_output_bytes": MAX_OUTPUT, "executable_bytes": MAX_EXECUTABLE_BYTES,
                       "snapshot_bytes": MAX_SNAPSHOT_BYTES, "report_bytes": MAX_REPORT_BYTES,
                       "probe_timeout_seconds": PROBE_TIMEOUT_SECONDS, "parallel_probe_workers": 3,
                       "desktop_candidates": len(DESKTOP_APP_PATHS),
                       "claim": "Process probes have time/output limits; file I/O has size limits"},
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "snapshot_path": str(snapshot_path),
            "limitations": ["No authentication, credential/config reads or model requests",
                            "No install, update, restart or vendor release/latest-version lookup",
                            "Help evidence does not prove policy, protocol, permissions or Desktop/Cloud parity",
                            "Compact help fingerprints/flags; use inventory_cli for complete top-level help"],
        }
        _save(directory_fd, result)
        return result
