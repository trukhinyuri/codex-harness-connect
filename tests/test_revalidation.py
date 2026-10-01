import hashlib
import json
import os
import plistlib
import sys
import threading

import pytest

from codex_harness_connect import revalidation


def write_cli(path, log, version="synthetic 1.0"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"with open({str(log)!r},'a') as stream: stream.write(sys.argv[1]+'\\n')\n"
        f"if sys.argv[1]=='--version': print({version!r})\n"
        "elif sys.argv[1]=='--help': print('--model --resume --verbose')\n"
        "else: raise SystemExit(90)\n"
    )
    path.chmod(0o700)
    return path


@pytest.fixture
def environment(tmp_path, monkeypatch):
    binary_root = tmp_path / "bin"
    claude_log, codex_log = tmp_path / "claude-calls", tmp_path / "codex-calls"
    claude = write_cli(binary_root / "claude", claude_log)
    codex = write_cli(binary_root / "codex", codex_log)
    monkeypatch.setenv("PATH", str(binary_root))
    monkeypatch.setattr(revalidation, "_desktop", lambda: {
        "status": "unavailable", "reason": "Synthetic host has no Desktop", "candidates": []})
    runtime = {"python": {"version": "test"}, "package": {"version": "test"},
               "sources": {"server.py": {"sha256": "a" * 64}},
               "api_contract": {"schema": 1}}
    monkeypatch.setattr(revalidation, "_runtime", lambda: runtime)
    return tmp_path / "state", claude, codex, claude_log, codex_log, runtime


def test_revalidation_always_probes_and_never_promotes_qualification(environment):
    root, claude, _, claude_log, codex_log, _ = environment
    first = revalidation.revalidate("claude", root)
    second = revalidation.revalidate("claude", root)
    expected = ["--version", "--help"] * 2
    assert claude_log.read_text().splitlines() == codex_log.read_text().splitlines() == expected
    assert first["comparison"]["status"] == "no_prior_observation"
    assert second["comparison"]["status"] == "unchanged"
    assert first["fingerprint"]["sha256"] == second["fingerprint"]["sha256"]
    assert first["observed_at"] != second["observed_at"]
    assert second["target_inventory"]["expected_sha256"] == hashlib.sha256(claude.read_bytes()).hexdigest()
    assert second["qualification"]["status"] == "incomplete"
    assert second["qualification"]["production_verified"] is False
    assert second["qualification"]["prior_qualification_carried_forward"] is False
    assert {gate["gate"] for gate in second["mandatory_acceptance_gates"]} == {
        "policy_billing", "native_protocol", "approvals", "resume", "cancel_reconnect",
        "worktrees_teams", "desktop_ui", "host_context_memory_cloud"}
    assert all(gate["status"] == "required_not_tested" for gate in second["mandatory_acceptance_gates"])
    snapshot = root / "revalidation/claude/latest.json"
    assert json.loads(snapshot.read_text()) == second
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert snapshot.parent.stat().st_mode & 0o777 == 0o700
    assert set(path.name for path in snapshot.parent.iterdir()) == {"latest.json", "observation.lock"}


@pytest.mark.parametrize("component", ["target_cli", "host_path_codex", "runtime_package", "runtime_api_contract"])
def test_any_full_fingerprint_change_invalidates_previous_qualification(environment, component):
    root, claude, codex, _, _, runtime = environment
    first = revalidation.revalidate("claude", root)
    snapshot = root / "revalidation/claude/latest.json"
    previous = json.loads(snapshot.read_text())
    previous["qualification"] = {"status": "qualified", "production_verified": True}
    snapshot.write_text(json.dumps(previous))
    if component == "target_cli":
        claude.write_text(claude.read_text() + "# native update\n")
    elif component == "host_path_codex":
        codex.write_text(codex.read_text() + "# host CLI update\n")
    elif component == "runtime_package":
        runtime["package"]["version"] = "new"
    else:
        runtime["api_contract"]["schema"] = 2
    second = revalidation.revalidate("claude", root)
    assert second["comparison"]["status"] == "changed"
    assert second["comparison"]["prior_qualification_invalidated"] is True
    assert component in second["comparison"]["changed_components"]
    assert second["fingerprint"]["sha256"] != first["fingerprint"]["sha256"]
    assert second["qualification"]["status"] == "incomplete"
    assert second["qualification"]["production_verified"] is False


def test_missing_host_and_native_cli_are_explicit_unknown_evidence(environment):
    root, claude, codex, _, _, _ = environment
    claude.unlink()
    codex.unlink()
    result = revalidation.revalidate("claude", root)
    assert result["target_inventory"]["status"] == "unavailable"
    assert "expected_sha256" not in result["target_inventory"]
    assert result["host"]["path_codex"]["status"] == "unavailable"
    assert result["host"]["desktop"]["status"] == "unavailable"
    assert result["host"]["current_host_tool_loading"]["status"] == "unknown"
    assert result["qualification"]["production_verified"] is False


def test_native_probe_identity_failure_does_not_supply_launch_fingerprint(environment):
    root, claude, _, _, _, _ = environment
    claude.write_text(claude.read_text() +
                      "if sys.argv[1]=='--version':\n"
                      "    with open(__file__,'a') as stream: stream.write('# drift\\n')\n")
    result = revalidation.revalidate("claude", root)
    assert result["target_inventory"]["status"] == "unknown"
    assert "expected_sha256" not in result["target_inventory"]
    assert result["qualification"]["status"] == "incomplete"


def test_existing_policy_holds_are_preserved(environment):
    result = revalidation.revalidate("claude-glm", environment[0])
    assert result["adapter_policy"]["hold_preserved"] is True
    assert result["adapter_policy"]["policy"] == "vendor-confirmation-required"
    gate = next(gate for gate in result["mandatory_acceptance_gates"] if gate["gate"] == "policy_billing")
    assert gate["status"] == "blocked_by_existing_policy_hold"


@pytest.mark.parametrize("corruption", ["invalid_json", "invalid_schema", "tampered_fingerprint"])
def test_corrupt_prior_observation_cannot_carry_qualification(environment, corruption):
    root = environment[0]
    revalidation.revalidate("claude", root)
    snapshot = root / "revalidation/claude/latest.json"
    previous = json.loads(snapshot.read_text())
    if corruption == "invalid_json":
        snapshot.write_bytes(b"\xff{broken")
    else:
        if corruption == "invalid_schema":
            previous["schema_version"] = 99
        else:
            previous["fingerprint"]["components"]["adapter_policy"] = "0" * 64
        snapshot.write_text(json.dumps(previous))
    result = revalidation.revalidate("claude", root)
    assert result["comparison"]["status"] == "corrupt_prior_observation"
    assert result["comparison"]["prior_qualification_invalidated"] is True
    assert result["qualification"]["production_verified"] is False


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "fifo", "public_file", "public_directory", "oversized"])
def test_unsafe_existing_ledger_fails_before_probes(environment, unsafe):
    root, _, _, claude_log, codex_log, _ = environment
    ledger = root / "revalidation/claude"
    root.mkdir(mode=0o700)
    ledger.parent.mkdir(mode=0o700)
    ledger.mkdir(mode=0o700)
    snapshot = ledger / "latest.json"
    if unsafe == "symlink":
        target = root / "outside"
        target.write_text("must remain untouched")
        snapshot.symlink_to(target)
    elif unsafe == "hardlink":
        target = root / "outside"
        target.write_text("must remain untouched")
        target.chmod(0o600)
        os.link(target, snapshot)
    elif unsafe == "fifo":
        os.mkfifo(snapshot, 0o600)
    elif unsafe == "public_file":
        snapshot.write_text("{}")
        snapshot.chmod(0o644)
    elif unsafe == "public_directory":
        ledger.chmod(0o755)
    else:
        snapshot.write_bytes(b"x" * (revalidation.MAX_SNAPSHOT_BYTES + 1))
        snapshot.chmod(0o600)
    with pytest.raises((ValueError, OSError)):
        revalidation.revalidate("claude", root)
    assert not claude_log.exists() and not codex_log.exists()
    if unsafe in {"symlink", "hardlink"}:
        assert target.read_text() == "must remain untouched"


def test_symlink_ancestor_is_rejected_without_creating_ledger(environment, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        revalidation.revalidate("claude", alias / "state")
    assert not (real / "state").exists()


def test_snapshot_limit_does_not_leave_partial_output(environment, monkeypatch):
    root, _, _, _, _, runtime = environment
    runtime["package"]["large"] = "x" * 5000
    monkeypatch.setattr(revalidation, "MAX_SNAPSHOT_BYTES", 4000)
    with pytest.raises(ValueError, match="snapshot size limit"):
        revalidation.revalidate("claude", root)
    ledger = root / "revalidation/claude"
    assert set(path.name for path in ledger.iterdir()) == {"observation.lock"}


def test_actual_runtime_fingerprints_sources_python_dependencies_and_contract():
    runtime = revalidation._runtime()
    assert runtime["python"]["version"]
    assert runtime["python"]["executable"]["status"] == "observed"
    assert set(runtime["sources"]) == set(revalidation.SOURCE_FILES)
    assert all(item["status"] == "observed" for item in runtime["sources"].values())
    assert runtime["sources"]["revalidation.py"]["sha256"]
    assert runtime["api_contract"]["server_source_sha256"] == runtime["sources"]["server.py"]["sha256"]
    assert runtime["api_contract"]["mcp_distribution"] == runtime["package"]["distributions"]["mcp"]
    assert "Experimental" in runtime["api_contract"]["desktop_app_server_plugin_api"]


def test_renamed_desktop_bundle_and_bundled_cli_are_observed_without_launching_ui(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    app = tmp_path / "ChatGPT.app"
    metadata_path = app / "Contents/Info.plist"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.openai.codex",
                                            "CFBundleShortVersionString": "1.0",
                                            "CFBundleVersion": "123", "CFBundleExecutable": "Codex"}))
    main = app / "Contents/MacOS/Codex"
    main.parent.mkdir()
    main.write_text("must not be executed")
    main.chmod(0o700)
    calls = tmp_path / "bundled-calls"
    bundled = write_cli(app / "Contents/Resources/codex-cli/bin/codex", calls)
    monkeypatch.setattr(revalidation, "DESKTOP_APP_PATHS", (tmp_path / "Codex.app", app))
    result = revalidation._desktop()
    assert result["status"] == "observed"
    observed = next(item for item in result["candidates"] if item["status"] == "observed")
    assert observed["metadata"]["CFBundleVersion"] == "123"
    assert observed["main_executable"]["sha256"] == hashlib.sha256(main.read_bytes()).hexdigest()
    assert observed["bundled_codex"]["inventory"]["resolved_path"] == str(bundled)
    assert calls.read_text().splitlines() == ["--version", "--help"]
    assert "latest state" not in result


def test_unrelated_app_at_known_path_is_not_probed(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    app = tmp_path / "ChatGPT.app"
    metadata_path = app / "Contents/Info.plist"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.openai.chat"}))
    log = tmp_path / "calls"
    write_cli(app / "Contents/Resources/codex-cli/bin/codex", log)
    monkeypatch.setattr(revalidation, "DESKTOP_APP_PATHS", (app,))
    result = revalidation._desktop()
    assert result["status"] == "unavailable"
    assert not log.exists()


@pytest.mark.parametrize("status", ["unavailable", "unknown"])
def test_repeated_missing_or_unknown_identity_always_invalidates(environment, monkeypatch, status):
    monkeypatch.setattr(revalidation, "_observe_cli", lambda executable: {
        "status": status, "executable": executable, "reason": "Not established"})
    first = revalidation.revalidate("claude", environment[0])
    second = revalidation.revalidate("claude", environment[0])
    assert first["comparison"]["prior_qualification_invalidated"] is True
    assert second["comparison"]["status"] == "unchanged"
    assert second["comparison"]["prior_qualification_invalidated"] is True
    assert {"target_cli", "host_path_codex"} <= set(second["comparison"]["identity_gaps"])


@pytest.mark.parametrize("status", ["unavailable", "unknown"])
def test_matching_desktop_bundle_with_unverified_child_always_invalidates(environment, monkeypatch, status):
    monkeypatch.setattr(revalidation, "_desktop", lambda: {
        "status": "observed", "candidates": [{"status": "observed",
                                                "main_executable": {"status": "observed"},
                                                "bundled_codex": {"status": status}}]})
    revalidation.revalidate("claude", environment[0])
    second = revalidation.revalidate("claude", environment[0])
    assert second["comparison"]["status"] == "unchanged"
    assert second["comparison"]["prior_qualification_invalidated"] is True
    assert "host_desktop.bundled_codex" in second["comparison"]["identity_gaps"]


def test_complete_unchanged_observation_still_does_not_prove_acceptance(environment, monkeypatch):
    root, _, _, _, _, runtime = environment
    runtime["python"]["executable"] = {"status": "observed"}
    runtime["sources"]["server.py"]["status"] = "observed"
    runtime["package"]["distributions"] = {"mcp": {"status": "observed", "version": "test"}}
    monkeypatch.setattr(revalidation, "_desktop", lambda: {
        "status": "observed", "candidates": [{"status": "unavailable"}, {"status": "observed",
            "main_executable": {"status": "observed"}, "bundled_codex": {"status": "observed"}}]})
    revalidation.revalidate("claude", root)
    second = revalidation.revalidate("claude", root)
    assert second["comparison"]["status"] == "unchanged"
    assert second["comparison"]["identity_gaps"] == []
    assert second["comparison"]["prior_qualification_invalidated"] is False
    assert second["qualification"]["status"] == "incomplete"
    assert second["qualification"]["prior_qualification_carried_forward"] is False


def test_help_is_compact_but_full_help_change_still_changes_fingerprint(environment, tmp_path):
    root, claude, _, _, _, _ = environment
    help_path = tmp_path / "help.txt"
    help_path.write_text("A" * 200_000)
    claude.write_text(claude.read_text().replace("print('--model --resume --verbose')",
                                              f"print(open({str(help_path)!r}).read())"))
    first = revalidation.revalidate("claude", root)
    help_path.write_text("B" * 200_000)
    second = revalidation.revalidate("claude", root)
    assert first["target_inventory"]["expected_sha256"] == second["target_inventory"]["expected_sha256"]
    assert first["fingerprint"]["sha256"] != second["fingerprint"]["sha256"]
    assert "target_cli" in second["comparison"]["changed_components"]
    assert second["target_inventory"]["inventory"]["help"]["text_omitted"] is True
    assert "text" not in second["target_inventory"]["inventory"]["help"]
    assert all(isinstance(item, str) and len(item) == 64
               for item in second["fingerprint"]["components"].values())
    assert len(json.dumps(second).encode()) < revalidation.MAX_REPORT_BYTES
    assert (root / "revalidation/claude/latest.json").stat().st_size < revalidation.MAX_REPORT_BYTES


def test_three_independent_local_observations_run_concurrently(environment, monkeypatch):
    barrier = threading.Barrier(3, timeout=2)

    def observe_cli(executable):
        barrier.wait()
        return {"status": "unavailable", "executable": executable}

    def observe_desktop():
        barrier.wait()
        return {"status": "unavailable", "candidates": []}

    monkeypatch.setattr(revalidation, "_observe_cli", observe_cli)
    monkeypatch.setattr(revalidation, "_desktop", observe_desktop)
    result = revalidation.revalidate("claude", environment[0])
    assert result["bounds"]["parallel_probe_workers"] == 3
    assert result["qualification"]["production_verified"] is False
