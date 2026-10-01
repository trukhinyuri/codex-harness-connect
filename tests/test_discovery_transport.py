import asyncio
import errno
import hashlib
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from codex_harness_connect import adapters, discovery, revalidation
from codex_harness_connect.server import build_server


def synthetic(tmp_path, body):
    path = tmp_path / "synthetic-help-cli"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return path


def capture_pty(monkeypatch):
    descriptors = []
    original = discovery.pty.openpty

    def recording_openpty():
        pair = original()
        descriptors.extend(pair)
        return pair

    monkeypatch.setattr(discovery.pty, "openpty", recording_openpty)
    return descriptors


def assert_closed(descriptors):
    assert len(descriptors) == 2
    for fd in descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(fd)
        assert error.value.errno == errno.EBADF


@pytest.mark.parametrize("transport,terminal", [("pipe", False), ("pty", True)])
def test_only_output_is_terminal_stdin_remains_closed(tmp_path, monkeypatch, transport, terminal):
    path = synthetic(tmp_path, (
        "import json,os,sys\n"
        "assert sys.argv[1:] == ['--help']\n"
        "assert sys.stdin.buffer.read() == b''\n"
        "print(json.dumps({'stdout':os.isatty(1),'stderr':os.isatty(2),'stdin':os.isatty(0)}))\n"
    ))
    original = subprocess.Popen
    calls = []

    def recording_popen(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(discovery.subprocess, "Popen", recording_popen)
    result = discovery._probe(path, "--help", transport=transport)
    assert result["exit_code"] == 0
    assert json.loads(result["text"]) == {"stdout": terminal, "stderr": terminal, "stdin": False}
    assert calls[0]["stdin"] == subprocess.DEVNULL
    assert calls[0].get("shell", False) is False
    assert calls[0]["start_new_session"] is True
    assert "env" not in calls[0] and "cwd" not in calls[0]


def test_terminal_sensitive_large_help_is_complete_and_version_stays_pipe(tmp_path):
    path = synthetic(tmp_path, (
        "import os,sys\n"
        "if sys.argv[1] == '--version':\n"
        " assert not os.isatty(1)\n"
        " print('synthetic-cli 1')\n"
        "elif sys.argv[1] == '--help':\n"
        " print('--common')\n"
        " if os.isatty(1):\n"
        "  for _ in range(400): os.write(1,b'help text beyond a small native pipe buffer\\n')\n"
        "  os.write(2,b'--last-required --output-format --verbose\\nCommands: complete\\n')\n"
        "else: raise SystemExit(99)\n"
    ))
    default = discovery.inventory(str(path))
    terminal = discovery.inventory(str(path), help_transport="pty")
    assert default["help_transport"] == "pipe"
    assert default["flags"] == ["--common"]
    assert terminal["help_transport"] == "pty"
    assert terminal["flags"] == ["--common", "--last-required", "--output-format", "--verbose"]
    assert len(terminal["help"]["text"].encode()) > 16000
    assert "Commands: complete" in terminal["help"]["text"]
    assert terminal["version"] == default["version"]
    assert terminal["binary_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_ansi_normalization_parses_flags_without_destroying_raw_evidence(tmp_path):
    styled = "--\x1b[31moutput-format\x1b[0m --allowedTools -\x1b[1mp\x1b[0m"
    path = synthetic(tmp_path, f"print({styled!r})\n")
    result = discovery.inventory(str(path), help_transport="pty")
    assert result["flags"] == ["--allowedTools", "--output-format"]
    assert result["short_flags"] == ["-p"]
    assert "\x1b[31m" in result["help"]["text"]
    assert result["help_sha256"] == hashlib.sha256(result["help"]["text"].encode()).hexdigest()


@pytest.mark.parametrize("call", ["probe", "inventory"])
@pytest.mark.parametrize("invalid", ["automatic", None, [], {}])
def test_unknown_transport_is_rejected_before_opening_or_spawning(tmp_path, monkeypatch, call, invalid):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid transport must not create descriptors or processes")

    monkeypatch.setattr(discovery.pty, "openpty", forbidden)
    monkeypatch.setattr(discovery.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="transport"):
        if call == "probe":
            discovery._probe(tmp_path / "absent", "--help", transport=invalid)
        else:
            discovery.inventory(str(tmp_path / "absent"), help_transport=invalid)


def test_success_and_terminal_eof_close_both_descriptors(tmp_path, monkeypatch):
    path = synthetic(tmp_path, "import os; os.write(1,b'--complete'); os.write(2,b' --stderr')\n")
    descriptors = capture_pty(monkeypatch)
    assert discovery._probe(path, "--help", transport="pty") == {
        "exit_code": 0, "text": "--complete --stderr",
    }
    assert_closed(descriptors)


def test_spawn_failure_closes_both_descriptors(tmp_path, monkeypatch):
    descriptors = capture_pty(monkeypatch)
    with pytest.raises(FileNotFoundError):
        discovery._probe(tmp_path / "missing", "--help", transport="pty")
    assert_closed(descriptors)


@pytest.mark.parametrize("failure", ["timeout", "oversize", "closed_output", "caller_cancel"])
def test_pty_failure_bounds_and_reaps_child_with_descriptor_cleanup(tmp_path, monkeypatch, failure):
    pid_file = tmp_path / "probe.pid"
    body = (
        "import os,signal,time\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f"open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
    )
    if failure == "oversize":
        body += "os.write(1,b'x'*8192)\n"
    elif failure == "closed_output":
        body += "os.close(1); os.close(2)\n"
    body += "time.sleep(30)\n"
    path = synthetic(tmp_path, body)
    descriptors = capture_pty(monkeypatch)
    monkeypatch.setattr(discovery, "PROBE_TIMEOUT_SECONDS", 0.75)
    monkeypatch.setattr(discovery, "MAX_OUTPUT", 1024)
    if failure == "caller_cancel":
        original = discovery.selectors.DefaultSelector

        class InterruptingSelector:
            def __init__(self):
                self.selector = original()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.selector.close()

            def register(self, *args):
                return self.selector.register(*args)

            def select(self, timeout):
                if pid_file.exists():
                    raise KeyboardInterrupt
                return self.selector.select(timeout)

        monkeypatch.setattr(discovery.selectors, "DefaultSelector", InterruptingSelector)
    error = {"timeout": TimeoutError, "closed_output": TimeoutError,
             "oversize": ValueError, "caller_cancel": KeyboardInterrupt}[failure]
    before = time.monotonic()
    with pytest.raises(error):
        discovery._probe(path, "--help", transport="pty")
    assert time.monotonic() - before < 2.5
    assert_closed(descriptors)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_unexpected_read_error_is_not_masked_as_terminal_eof(tmp_path, monkeypatch):
    path = synthetic(tmp_path, "import time; print('--help',flush=True); time.sleep(30)\n")
    descriptors = capture_pty(monkeypatch)
    original = os.read
    original_popen = subprocess.Popen
    processes = []

    def recording_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    def failing_read(fd, count):
        if descriptors and fd == descriptors[0]:
            raise OSError(errno.EBADF, "synthetic read error")
        return original(fd, count)

    monkeypatch.setattr(discovery.os, "read", failing_read)
    monkeypatch.setattr(discovery.subprocess, "Popen", recording_popen)
    with pytest.raises(OSError) as error:
        discovery._probe(path, "--help", transport="pty")
    # macOS can replace the read error with a cleanup EPERM while its group exits.
    assert (error.value.errno == errno.EBADF or
            isinstance(error.value, PermissionError)
            and isinstance(error.value.__context__, OSError)
            and error.value.__context__.errno == errno.EBADF)
    assert_closed(descriptors)
    assert processes[0].poll() is not None


@pytest.mark.parametrize("name,transport", [
    ("claude", "pty"), ("claude-glm", "pty"), ("grok", "pipe"), ("agy", "pipe"),
])
def test_registered_inventory_selects_transport_without_changing_public_arguments(tmp_path, name, transport):
    assert adapters.get_adapter(name).help_transport == transport
    server = build_server(tmp_path / "state", name)
    with patch("codex_harness_connect.server.inventory", return_value={"fixture": True}) as probe:
        asyncio.run(server.call_tool("inventory_cli", {"adapter": name}))
    probe.assert_called_once_with(adapters.get_adapter(name).executable, help_transport=transport)


def test_revalidation_observation_preserves_explicit_target_and_generic_defaults():
    evidence = {
        "version": {"exit_code": 0, "text": "synthetic 1"},
        "help": {"exit_code": 0, "text": "--synthetic"},
        "help_sha256": "a" * 64, "binary_sha256": "b" * 64,
        "flags": ["--synthetic"], "short_flags": [],
    }
    with patch("codex_harness_connect.revalidation.inventory", return_value=evidence) as probe:
        revalidation._observe_cli("claude", "pty")
        revalidation._observe_cli("codex")
    assert probe.call_args_list[0].args == ("claude",)
    assert probe.call_args_list[0].kwargs == {"help_transport": "pty"}
    assert probe.call_args_list[1].args == ("codex",)
    assert probe.call_args_list[1].kwargs == {}
