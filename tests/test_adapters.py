from pathlib import Path
from unittest.mock import patch

import pytest

from codex_harness_connect.adapters import launch_contract, validate_options
from codex_harness_connect.plugins import generate_marketplace, write_plugin


def test_forbids_permission_bypass():
    for flag in ["--dangerously-skip-permissions", "--permission-mode=bypassPermissions",
                 "--always-approve", "--yolo", "--mcp-config=evil.json", "--allowed-tools=Bash",
                 "--add-dir=/outside", "--plugin-dir=unreviewed", "--fallback-model=paid-api",
                 "--permission-prompts=host"]:
        with pytest.raises(ValueError):
            validate_options([flag], [flag.split("=")[0]])


def test_native_argument_injection_is_rejected():
    for option in ["--invented", "auth", "$(touch /tmp/no)", "-p", "--model=\x00", "--model",
                   "--plugin-url=https://unsafe", "--agents=custom"]:
        with pytest.raises(ValueError):
            validate_options([option], ["--model"])
    assert validate_options(["--model=sonnet"], ["--model"]) == ["--model=sonnet"]


@pytest.mark.parametrize("profile", ["agy", "claude-glm", "grok"])
def test_policy_holds_are_not_bypassable(profile, tmp_path):
    with pytest.raises(PermissionError):
        launch_contract(profile, "test", str(tmp_path), "batch", "arbitrary")


def test_marketplace_has_every_requested_profile(tmp_path):
    result = generate_marketplace(tmp_path)
    assert {p["name"] for p in result["plugins"]} == {
        "codex-harness-connect", "harness-claude", "harness-claude-glm", "harness-grok", "harness-agy"}
    for p in result["plugins"]:
        assert (Path(p["path"]) / ".mcp.json").is_file()
    with pytest.raises(FileExistsError):
        generate_marketplace(tmp_path)


def test_existing_plugin_is_preserved(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    (directory / "keep").write_text("owned by user")
    with pytest.raises(FileExistsError):
        write_plugin(directory)
    assert (directory / "keep").read_text() == "owned by user"


def test_batch_refuses_untrusted_workspace_before_binary_probe(tmp_path):
    hooks = tmp_path / ".claude"
    hooks.mkdir()
    (hooks / "settings.json").write_text('{"hooks": {"SessionStart": []}}')
    with patch("codex_harness_connect.adapters.inventory") as probe:
        for confirmation in (None, "/different-directory"):
            with pytest.raises(PermissionError, match="workspace trust"):
                launch_contract("claude", "test", str(tmp_path), "batch", "arbitrary",
                                batch_workspace_confirmation=confirmation)
        probe.assert_not_called()


def test_batch_trust_acknowledgement_does_not_add_permission_flags(tmp_path):
    evidence = {"binary_sha256": "reviewed", "resolved_path": "/trusted/claude",
                "help": {"exit_code": 0}, "version": {"exit_code": 0}, "flags": []}
    with patch("codex_harness_connect.adapters.inventory", return_value=evidence):
        contract = launch_contract("claude", "test", str(tmp_path), "batch", "reviewed",
                                   batch_workspace_confirmation=str(tmp_path.resolve()))
    assert contract["argv"] == ["/trusted/claude", "--print", "--output-format",
                                 "stream-json", "--verbose", "test"]
