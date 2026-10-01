import json
from pathlib import Path

import pytest

from codex_harness_connect import plugins


def snapshot(root):
    return {str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
            for path in root.rglob("*")}


def test_existing_marketplace_does_not_create_any_plugins(tmp_path):
    marketplace = tmp_path / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text('{"existing":"untouched"}\n')
    before = snapshot(tmp_path)
    with pytest.raises(FileExistsError, match="Marketplace exists"):
        plugins.generate_marketplace(tmp_path)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "plugins").exists()


@pytest.mark.parametrize("existing_name", ["harness-claude-glm", "unrelated-existing-package"])
def test_partial_plugin_collision_is_preflighted_before_any_mutation(tmp_path, existing_name):
    existing = tmp_path / "plugins" / existing_name
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("Keep existing content")
    before = snapshot(tmp_path)
    with pytest.raises(FileExistsError, match="Existing plugins"):
        plugins.generate_marketplace(tmp_path)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("preexisting_root", [False, True])
def test_mid_write_failure_rolls_back_all_new_packages(tmp_path, monkeypatch, preexisting_root):
    root = tmp_path / "output"
    if preexisting_root:
        root.mkdir()
        (root / "keep.txt").write_text("preserve unrelated root content")
    before = snapshot(tmp_path)
    original = plugins._Transaction.write
    calls = 0

    def fail_after_write(transaction, path, content):
        nonlocal calls
        calls += 1
        original(transaction, path, content)
        if calls == 5:
            raise OSError("synthetic injected write failure")

    monkeypatch.setattr(plugins._Transaction, "write", fail_after_write)
    with pytest.raises(OSError, match="synthetic injected"):
        plugins.generate_marketplace(root)
    assert calls == 5
    assert snapshot(tmp_path) == before


def test_single_plugin_failure_removes_its_partial_files(tmp_path, monkeypatch):
    original = plugins._Transaction.write

    def fail_after_write(transaction, path, content):
        original(transaction, path, content)
        raise OSError("synthetic plugin write failure")

    monkeypatch.setattr(plugins._Transaction, "write", fail_after_write)
    with pytest.raises(OSError, match="synthetic plugin"):
        plugins.write_plugin(tmp_path / "new-package")
    assert not list(tmp_path.iterdir())


def test_successful_batch_preserves_catalog_and_manifest_contract(tmp_path):
    result = plugins.generate_marketplace(tmp_path, command="reviewed-command")
    catalog = json.loads(Path(result["marketplace"]).read_text())
    expected = {"codex-harness-connect", *[f"harness-{name}" for name in plugins.ADAPTERS]}
    assert {item["name"] for item in result["plugins"]} == expected
    assert {item["name"] for item in catalog["plugins"]} == expected
    server_names = set()
    for item in result["plugins"]:
        directory = Path(item["path"])
        manifest = json.loads((directory / ".codex-plugin/plugin.json").read_text())
        assert manifest["name"] == item["name"]
        servers = json.loads((directory / ".mcp.json").read_text())["mcpServers"]
        assert len(servers) == 1
        server_name, config = next(iter(servers.items()))
        assert server_name not in server_names
        server_names.add(server_name)
        assert config["command"] == "reviewed-command"
        assert config["args"][0] == "serve"
        assert manifest["version"] == "0.1.0-alpha.5"
        if item["name"] == "codex-harness-connect":
            assert manifest["interface"]["displayName"] == "connect_harness_cli"
            skill = directory / "skills/connect-harness-cli/SKILL.md"
            assert skill.is_file()
            assert not (directory / "skills/connect-cli").exists()
            assert "EVERY repeated invocation" in skill.read_text()
            assert "revalidate_cli on EVERY invocation" in skill.read_text()
            assert "display_name: \"connect_harness_cli\"" in (
                skill.parent / "agents/openai.yaml").read_text()


def test_dangling_marketplace_symlink_is_not_overwritten(tmp_path):
    marketplace = tmp_path / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.symlink_to(tmp_path / "absent-target")
    with pytest.raises(FileExistsError):
        plugins.generate_marketplace(tmp_path)
    assert marketplace.is_symlink()
    assert not (tmp_path / "plugins").exists()
