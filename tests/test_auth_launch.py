import asyncio
import json
import time
from unittest.mock import patch

import pytest

from codex_harness_connect.auth import ROUTE_OVERRIDES
from codex_harness_connect.discovery import file_fingerprint
from codex_harness_connect.server import build_server
from codex_harness_connect.sessions import SessionService


@pytest.fixture
def native(tmp_path, monkeypatch):
    for key in ROUTE_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "claude"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys,time\n"
        "from pathlib import Path\n"
        "if sys.argv[1:] == ['auth','status','--json']:\n"
        " Path('auth-started').touch()\n"
        " if Path('slow-auth').exists(): time.sleep(30)\n"
        " print(Path('route.json').read_text()); sys.exit(0)\n"
        "Path('native-model-started').touch()\n"
        "print('SYNTHETIC_NATIVE_DONE')\n"
    )
    path.chmod(0o700)
    (tmp_path / "route.json").write_text(json.dumps({
        "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
        "subscriptionType": "max", "email": "NEVER_PUBLISH", "configDirectory": "PRIVATE_PATH",
    }))
    return path, {"kind": "claude-own-subscription",
                  "expected_sha256": file_fingerprint(path)["sha256"]}


def terminal(service, sid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        report = service.status(sid)
        if report["session"]["status"] in {"completed", "failed", "cancelled", "lost"}:
            return report
        time.sleep(0.03)
    pytest.fail("Synthetic auth-guard worker did not reach terminal state")


def test_worker_observes_route_in_actual_workspace_before_launch(tmp_path, native):
    path, guard = native
    service = SessionService(tmp_path / "state")
    job = service.start([str(path), "synthetic"], str(tmp_path), auth_preflight=guard,
                        request_id="1" * 32)
    report = terminal(service, job["session_id"])
    assert report["session"]["status"] == "completed"
    assert (tmp_path / "auth-started").exists()
    assert (tmp_path / "native-model-started").exists()
    preflight = next(item for item in report["events"] if item["kind"] == "auth_preflight")
    assert preflight["data"]["route_eligible"] is True
    assert preflight["data"]["billing_guarantee"] is False
    assert "NEVER_PUBLISH" not in json.dumps(report)
    assert "PRIVATE_PATH" not in json.dumps(report)
    recovered = service.start([str(path), "synthetic"], str(tmp_path), auth_preflight=guard,
                              request_id="1" * 32)
    assert recovered["session_id"] == job["session_id"]


def test_worker_api_route_is_held_before_native_model_process(tmp_path, native):
    path, guard = native
    (tmp_path / "route.json").write_text(json.dumps({
        "loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty",
        "subscriptionType": None,
    }))
    service = SessionService(tmp_path / "state")
    job = service.start([str(path), "synthetic"], str(tmp_path), auth_preflight=guard)
    report = terminal(service, job["session_id"])
    assert report["session"]["status"] == "failed"
    assert report["session"]["child_pid"] is None
    assert not (tmp_path / "native-model-started").exists()
    assert "own_subscription_route_not_observed" in json.dumps(report)


def test_pre_guard_request_receipt_stays_recoverable_without_new_launch(tmp_path, native):
    path, guard = native
    service = SessionService(tmp_path / "state")
    request_id = "e" * 32
    job = service.start([str(path), "synthetic"], str(tmp_path), request_id=request_id)
    terminal(service, job["session_id"])
    with patch("codex_harness_connect.sessions.subprocess.Popen") as spawn:
        with pytest.raises(ValueError, match="different launch"):
            service.start([str(path), "synthetic"], str(tmp_path), request_id=request_id,
                          auth_preflight=guard)
        spawn.assert_not_called()
    recovered = service.lookup_request(request_id)
    assert recovered["session_id"] == job["session_id"]


def test_cancel_during_native_auth_check_never_starts_model(tmp_path, native):
    path, guard = native
    (tmp_path / "slow-auth").touch()
    service = SessionService(tmp_path / "state")
    job = service.start([str(path), "synthetic"], str(tmp_path), auth_preflight=guard)
    assert job["status"] == "starting"
    assert (tmp_path / "auth-started").exists()
    cancelled = service.cancel(job["session_id"])
    assert cancelled["accepted"] is True
    report = terminal(service, job["session_id"])
    assert report["session"]["status"] == "cancelled"
    assert report["session"]["child_pid"] is None
    assert not (tmp_path / "native-model-started").exists()


@pytest.mark.parametrize("profile, exposed", [(None, True), ("claude", True),
                                               ("claude-glm", False), ("grok", False), ("agy", False)])
def test_auth_tool_is_only_exposed_for_reviewed_native_command(tmp_path, profile, exposed):
    server = build_server(tmp_path / "state", profile)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert ("auth_status" in tools) is exposed
    if exposed:
        assert tools["auth_status"].annotations.readOnlyHint is True
        assert set(tools["auth_status"].inputSchema["properties"]) == {
            "adapter", "cwd", "expected_sha256"}


def test_claude_preserves_current_native_route_without_auth_gate(tmp_path):
    from codex_harness_connect.adapters import launch_contract
    evidence = {"binary_sha256": "a" * 64, "resolved_path": "/trusted/claude",
                "help": {"exit_code": 0}, "version": {"exit_code": 0},
                "flags": ["--print", "--output-format", "--verbose"]}
    with patch("codex_harness_connect.adapters.inventory", return_value=evidence), \
            patch("codex_harness_connect.auth.require_subscription_route") as auth:
        contract = launch_contract("claude", "synthetic only", str(tmp_path), "batch", "a" * 64,
                                   batch_workspace_confirmation=str(tmp_path))
        auth.assert_not_called()
        assert contract["auth_preflight"] is None
        assert contract["argv"] == ["/trusted/claude", "--print", "--output-format",
                                    "stream-json", "--verbose", "synthetic only"]


@pytest.mark.parametrize("invalid", [{}, {"kind": "anything", "expected_sha256": "a" * 64},
                                   {"kind": "claude-own-subscription", "expected_sha256": "bogus"},
                                   {"kind": "claude-own-subscription", "expected_sha256": "a" * 64,
                                    "skip": True}])
def test_invalid_auth_preflight_cannot_start_worker(tmp_path, invalid):
    service = SessionService(tmp_path / "state")
    with patch("codex_harness_connect.sessions.subprocess.Popen") as spawn:
        with pytest.raises(ValueError, match="Invalid native auth preflight"):
            service.start(["/trusted/claude", "test"], str(tmp_path), auth_preflight=invalid)
        spawn.assert_not_called()


@pytest.mark.parametrize("options", [None, ["--effort=ultracode"],
                                     ["--model=opus", "--effort=xhigh",
                                      "--forward-subagent-text"]])
def test_resume_accepts_explicit_reviewed_options_without_auth_bypass(tmp_path, options):
    server = build_server(tmp_path / "state", "claude")
    source = {"native_session_id": "verified-native-id", "protocol": "claude-stream-json",
              "status": "cancelled", "cwd": str(tmp_path)}
    evidence = {"binary_sha256": "a" * 64, "resolved_path": "/trusted/claude",
                "help": {"exit_code": 0}, "version": {"exit_code": 0},
                "flags": ["--print", "--output-format", "--verbose", "--resume",
                          "--model", "--effort", "--forward-subagent-text"]}
    args = {"adapter": "claude", "source_session_id": "b" * 32, "prompt": "review",
            "cwd": str(tmp_path), "expected_sha256": "a" * 64, "request_id": "c" * 32,
            "mode": "batch", "batch_workspace_confirmation": str(tmp_path)}
    if options is not None:
        args["native_options"] = options
    with patch.object(SessionService, "status", return_value={"session": source}), \
            patch("codex_harness_connect.adapters.inventory", return_value=evidence), \
            patch("codex_harness_connect.auth.require_subscription_route") as auth, \
            patch.object(SessionService, "start", return_value={"session_id": "d" * 32}) as spawn:
        asyncio.run(server.call_tool("resume_session", args))
    auth.assert_not_called()
    argv = spawn.call_args.args[0]
    assert argv == ["/trusted/claude", "--resume", "verified-native-id", "--print",
                    "--output-format", "stream-json", "--verbose", *(options or []), "review"]
    assert spawn.call_args.kwargs["auth_preflight"] is None


@pytest.mark.parametrize("option", ["--dangerously-skip-permissions", "--effort",
                                   "--settings=private.json", "--resume=other-id",
                                   "--fallback-model=haiku", "--unknown=anything"])
def test_resume_options_still_reject_unsafe_or_unknown_flags_before_launch(tmp_path, option):
    server = build_server(tmp_path / "state", "claude")
    source = {"native_session_id": "verified-native-id", "protocol": "claude-stream-json",
              "status": "completed", "cwd": str(tmp_path)}
    evidence = {"binary_sha256": "a" * 64, "resolved_path": "/trusted/claude",
                "help": {"exit_code": 0}, "version": {"exit_code": 0},
                "flags": ["--print", "--output-format", "--verbose", "--resume", "--effort"]}
    with patch.object(SessionService, "status", return_value={"session": source}), \
            patch("codex_harness_connect.adapters.inventory", return_value=evidence), \
            patch("codex_harness_connect.auth.require_subscription_route") as auth, \
            patch.object(SessionService, "start") as spawn:
        with pytest.raises(Exception):
            asyncio.run(server.call_tool("resume_session", {
                "adapter": "claude", "source_session_id": "b" * 32, "prompt": "review",
                "cwd": str(tmp_path), "expected_sha256": "a" * 64, "request_id": "c" * 32,
                "mode": "batch", "batch_workspace_confirmation": str(tmp_path),
                "native_options": [option],
            }))
        spawn.assert_not_called()
        auth.assert_not_called()


@pytest.mark.parametrize("change,error", [
    ({"status": "running"}, "terminal state"),
    ({"status": "starting"}, "terminal state"),
    ({"native_session_id": None}, "verified native conversation"),
    ({"protocol": None}, "verified native conversation"),
    ({"cwd": "/different-workspace"}, "source job's workspace"),
])
def test_resume_rejects_invalid_source_before_inventory_or_launch(tmp_path, change, error):
    server = build_server(tmp_path / "state", "claude")
    source = {"native_session_id": "verified-id", "protocol": "claude-stream-json",
              "status": "completed", "cwd": str(tmp_path)}
    source.update(change)
    with patch.object(SessionService, "status", return_value={"session": source}), \
            patch("codex_harness_connect.adapters.inventory") as probe, \
            patch.object(SessionService, "start") as spawn:
        with pytest.raises(Exception, match=error):
            asyncio.run(server.call_tool("resume_session", {
                "adapter": "claude", "source_session_id": "b" * 32, "prompt": "review",
                "cwd": str(tmp_path), "expected_sha256": "a" * 64, "request_id": "c" * 32,
                "native_options": ["--effort=ultracode"],
            }))
        probe.assert_not_called()
        spawn.assert_not_called()
