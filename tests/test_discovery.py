import hashlib
import os
import subprocess
import sys
import time

import pytest

from codex_harness_connect import discovery
from codex_harness_connect.sessions import process_identity


def executable(tmp_path, code):
    path = tmp_path / "trusted-synthetic-cli"
    path.write_text(f"#!{sys.executable}\n" + code)
    path.chmod(0o700)
    return path


@pytest.mark.parametrize("mode", ["noisy", "hung"])
def test_probe_bounded_output_timeout_and_process_group_cleanup(tmp_path, monkeypatch, mode):
    pid_file = tmp_path / "descendant.pid"
    child_code = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
    body = (
        "import os,signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}])\n"
        f"open({str(pid_file)!r},'w').write(str(child.pid))\n"
    )
    body += "while True: os.write(1,b'x'*65536)\n" if mode == "noisy" else "time.sleep(60)\n"
    path = executable(tmp_path, body)
    monkeypatch.setattr(discovery, "MAX_OUTPUT", 1024)
    timeout = 5 if mode == "noisy" else 2
    monkeypatch.setattr(discovery, "PROBE_TIMEOUT_SECONDS", timeout)
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        assert kwargs["stdout"] is subprocess.PIPE
        assert kwargs["start_new_session"]
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(discovery.subprocess, "Popen", capture)
    before = time.monotonic()
    error = ValueError if mode == "noisy" else TimeoutError
    with pytest.raises(error):
        discovery._probe(path, "--help")
    assert time.monotonic() - before < timeout + 1.5
    assert processes[0].poll() is not None
    assert process_identity(processes[0].pid) is None
    descendant = int(pid_file.read_text())
    deadline = time.monotonic() + 1
    while process_identity(descendant) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert process_identity(descendant) is None
    assert {entry.name for entry in tmp_path.iterdir()} == {path.name, pid_file.name}


def test_inventory_uses_only_version_and_help_without_interpreting_text(tmp_path):
    marker = tmp_path / "must-not-exist"
    code = (
        "import sys\n"
        "if sys.argv[1]=='--version': print('synthetic-cli 1.0')\n"
        f"elif sys.argv[1]=='--help': print('--alpha --beta-value; touch {marker}')\n"
        "else: raise SystemExit(99)\n"
    )
    path = executable(tmp_path, code)
    result = discovery.inventory(str(path))
    assert result["flags"] == ["--alpha", "--beta-value"]
    assert result["version"]["exit_code"] == 0 and result["help"]["exit_code"] == 0
    assert result["binary_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["resolved_path"] == str(path.resolve())
    assert "not proof" in result["claim"]
    assert not marker.exists()


def test_executable_validation_and_nonzero_probe_result(tmp_path):
    with pytest.raises(ValueError):
        discovery.resolve_executable("bad\0path")
    with pytest.raises(FileNotFoundError):
        discovery.resolve_executable(str(tmp_path / "absent"))
    path = executable(tmp_path, "import sys; print('diagnostic'); sys.exit(7)\n")
    result = discovery._probe(path, "--version")
    assert result == {"exit_code": 7, "text": "diagnostic\n"}


def test_inventory_preserves_camel_case_and_short_flags(tmp_path):
    path = executable(tmp_path, "print('--allowedTools --XFeature --snake_case -p, -s --foo-bar')\n")
    result = discovery.inventory(str(path))
    assert result["flags"] == ["--XFeature", "--allowedTools", "--foo-bar", "--snake_case"]
    assert result["short_flags"] == ["-p", "-s"]


@pytest.mark.parametrize("changed_flag", ["--version", "--help"])
def test_inventory_rejects_binary_mutation_during_each_probe(tmp_path, changed_flag):
    calls = tmp_path / "calls"
    path = executable(tmp_path, (
        "import sys\n"
        f"with open({str(calls)!r},'a') as stream: stream.write(sys.argv[1]+'\\n')\n"
        "print('--alpha')\n"
        f"if sys.argv[1]=={changed_flag!r}:\n"
        "    with open(__file__,'a') as stream: stream.write('# changed\\n')\n"
    ))
    with pytest.raises(ValueError, match="identity changed during probes"):
        discovery.inventory(str(path))
    assert calls.read_text().splitlines() == (["--version"] if changed_flag == "--version"
                                             else ["--version", "--help"])


def test_inventory_rejects_identical_binary_replacement(tmp_path, monkeypatch):
    path = executable(tmp_path, "print('--alpha')\n")
    original_probe = discovery._probe
    calls = []

    def replace_after_probe(current, flag):
        calls.append(flag)
        result = original_probe(current, flag)
        replacement = tmp_path / "replacement"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o700)
        os.replace(replacement, path)
        return result

    monkeypatch.setattr(discovery, "_probe", replace_after_probe)
    with pytest.raises(ValueError, match="identity changed during probes"):
        discovery.inventory(str(path))
    assert calls == ["--version"]


def test_inventory_rejects_resolved_symlink_identity_change(tmp_path, monkeypatch):
    first = executable(tmp_path, "print('--alpha')\n")
    second = tmp_path / "second"
    second.write_bytes(first.read_bytes())
    second.chmod(0o700)
    alias = tmp_path / "cli"
    alias.symlink_to(first)
    original_probe = discovery._probe

    def retarget_after_probe(path, flag):
        result = original_probe(path, flag)
        alias.unlink()
        alias.symlink_to(second)
        return result

    monkeypatch.setattr(discovery, "_probe", retarget_after_probe)
    with pytest.raises(ValueError, match="identity changed during probes"):
        discovery.inventory(str(alias))


def test_file_fingerprint_is_bounded_and_refuses_nonregular_files(tmp_path):
    path = tmp_path / "oversize"
    path.write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="bounded regular file"):
        discovery.file_fingerprint(path, 50)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="bounded regular file"):
        discovery.file_fingerprint(fifo)
