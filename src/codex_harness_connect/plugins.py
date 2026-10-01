"""Generate local Codex packages from explicit, reviewed adapter evidence."""
from __future__ import annotations

import json
from pathlib import Path

from .adapters import ADAPTERS, get_adapter

RESEARCH_SKILL = """---
name: connect-harness
description: Research an installed agent CLI, review its vendor terms and create a Codex harness plugin.
---

Use this workflow when the user asks to connect a harness. Keep Codex as the parent agent.
1. Get the executable the user intends to connect. Never install or log in on their behalf implicitly.
2. Call inventory_cli for a registered adapter, or inventory_candidate for the user-designated trusted
   executable. Inventory is only top-level help and version evidence; unknown adapters are not executable.
3. Read the vendor's current official docs, terms, release notes and source when available. Enumerate
   subcommands, flags, interactive commands, output schemas, approvals, auth/billing, resume, cancellation,
   teams, skills, MCP, worktrees and version drift. Do not treat CLI help or an OSS license as permission.
4. Produce a capability dossier: each capability needs a source, installed-version evidence, test result
   and status (documented / detected / tested / blocked / unavailable). Preserve contradictory evidence.
5. Explain host boundaries: Codex memory, plugins, context and skills stay with Codex; only explicitly
   supplied task context reaches the child. Codex sandbox/approvals are not automatically inherited.
6. If the repository destination is absent, ask for it before publishing; local reversible work can continue.
   Use the user-requested repository/name when already provided. Never publish transcripts or credentials.
7. Generate and test the adapter package. Unknown CLIs require reviewed code, not guessed flag translation.
   Do not mark an adapter ready from a generated manifest or passing synthetic test.
8. Validate actual vendor results, denial/approval, resume, cancellation, reconnect, concurrent worktrees,
   native teams and the Desktop user experience. Record each gap; do not claim 100% integration.
9. Install through the documented marketplace mechanism only when authorized. Start a fresh Codex session
   to load tools/skills. Preserve model, speed, reasoning, auth, payment and security defaults.

For long-running jobs, start once, retain the returned job id and consume events with cursors. A tool timeout
does not prove the child exited. Confirm cancellation with authoritative state. Never automatically retry a
model request after an uncertain outcome. Choose a fresh 32-character lowercase hex request_id before
start_session or resume_session; retain it before calling. Use lookup_request after an uncertain response.
The same request id and identical launch returns the existing job, never another inference process.
Batch requires the exact resolved workspace path explicitly acknowledged by the user as trusted because
Claude --print skips its trust dialog. Never invent that acknowledgement or treat it as tool approval.
Use native interactive mode for native terminal/teams features;
TTY text is not the Codex internal subagent UI. No yolo, bypass permissions, auth-token extraction, hidden
paid fallback or sharing credentials. Current policy holds must be resolved through vendor evidence.
"""


def _plugin_spec(destination: Path, profile: str | None, command: str) -> tuple[dict, dict]:
    if profile:
        adapter = get_adapter(profile)
        name = f"harness-{profile}"
        description = adapter.notes
        skill_name = f"use-{profile}"
        body = f"""---
name: {skill_name}
description: Delegate authorized local work to the unmodified {profile} CLI through Harness Connect.
---

Use inventory_cli and describe_adapter before starting work. This package is for {profile} only.
Policy: {adapter.policy}. {description}
Keep the parent Codex task context and verify relevant AGENTS.md instructions. Pass required instructions,
skill results and user-approved context explicitly in the prompt. Do not read or export hidden memory,
credentials or settings. Native harness customizations are loaded by that harness itself.
For native approvals or native team features, use interactive PTY; don't claim print mode supports them.
Use start_session, then session_events with the returned id/cursor. Keep OS job id and native conversation
id separate. Choose and retain a fresh 32-character lowercase hex request_id before launching; recover an
uncertain response with lookup_request. Never automatically restart a job whose outcome is uncertain.
Use send_input for explicit user choices, cancel_session to stop and verify its final state, and
resume_session with the source_session_id of a completed known job in the same workspace. Only typed
native protocol can confirm its conversation id; arbitrary TUI text cannot. Do not invent native ids.
Batch requires the exact workspace path explicitly authorized as trusted by the user; --print skips
Claude's trust dialog. This acknowledgement does not approve tools or establish sandbox containment.
Review changed files and tests with Codex's ordinary review tools. Jobs are external tasks, not native Codex
subagents, and child tools have their own permission enforcement. Policy-held adapters cannot launch.
"""
    else:
        name = "codex-harness-connect"
        description = "Research and connect local agent CLIs with explicit capability and policy evidence."
        skill_name, body = "connect-harness", RESEARCH_SKILL
    args = ["serve"] + (["--profile", profile] if profile else [])
    manifest = {
        "name": name, "version": "0.1.0-alpha.1", "description": description,
        "skills": "./skills/", "mcpServers": "./.mcp.json",
        "interface": {"displayName": name, "shortDescription": "Local CLI sessions and reviewed delegation",
                      "longDescription": description, "developerName": "Yuri Trukhin",
                      "category": "Productivity", "capabilities": ["Read", "Write"]},
    }
    server_name = "chc_" + (profile.replace("-", "_") if profile else "router")
    files = {destination / ".codex-plugin/plugin.json": json.dumps(manifest, indent=2) + "\n",
             destination / ".mcp.json": json.dumps(
                 {"mcpServers": {server_name: {"command": command, "args": args}}}, indent=2) + "\n",
             destination / "skills" / skill_name / "SKILL.md": body}
    return ({"name": name, "path": str(destination), "profile": profile,
             "readiness": "package-generated; runtime and Desktop acceptance are separate gates"}, files)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


class _Transaction:
    def __init__(self):
        self.created = []

    def remember(self, path: Path, directory: bool):
        info = path.lstat()
        self.created.append((path, directory, info.st_dev, info.st_ino))

    def mkdir(self, path: Path):
        if _exists(path):
            if path.is_symlink() or not path.is_dir():
                raise FileExistsError(f"Refusing to write through an existing file or symlink: {path}")
            return
        self.mkdir(path.parent)
        path.mkdir()
        self.remember(path, True)

    def write(self, path: Path, content: str):
        self.mkdir(path.parent)
        # Exclusive creation also protects preflight from a later file collision.
        with path.open("x", encoding="utf-8") as stream:
            self.remember(path, False)
            stream.write(content)

    def rollback(self):
        errors = []
        for path, directory, device, inode in reversed(self.created):
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) != (device, inode):
                    continue
                path.rmdir() if directory else path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("Generation rollback could not remove owned paths: " + "; ".join(errors))


def _publish(files: dict[Path, str]):
    transaction = _Transaction()
    try:
        for path, content in files.items():
            transaction.write(path, content)
    except BaseException:
        transaction.rollback()
        raise


def write_plugin(destination: Path, profile: str | None = None, command: str = "codex-harness-connect") -> dict:
    destination = Path(destination)
    if _exists(destination):
        raise FileExistsError("Refusing to overwrite an existing plugin directory")
    result, files = _plugin_spec(destination, profile, command)
    _publish(files)
    return result


def generate_marketplace(root: Path, command: str = "codex-harness-connect") -> dict:
    root = Path(root)
    path = root / ".agents" / "plugins" / "marketplace.json"
    plugin_root = root / "plugins"
    # Preflight the entire batch before any directory or package file is created.
    if _exists(path):
        raise FileExistsError("Marketplace exists; review additions rather than replacing it")
    if _exists(plugin_root) and (plugin_root.is_symlink() or not plugin_root.is_dir()
                               or any(plugin_root.iterdir())):
        raise FileExistsError("Existing plugins must be reviewed before generating packages")
    specs = [_plugin_spec(plugin_root / "codex-harness-connect", None, command)]
    specs += [_plugin_spec(plugin_root / f"harness-{name}", name, command) for name in ADAPTERS]
    plugins = [result for result, _ in specs]
    catalog = {"name": "codex-harness-connect", "interface": {"displayName": "Harness Connect"},
               "plugins": [{"name": p["name"], "source": {"source": "local", "path": "./plugins/" + p["name"]},
                            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                            "category": "Productivity"} for p in plugins]}
    files = {path: content for _, files in specs for path, content in files.items()}
    files[path] = json.dumps(catalog, indent=2) + "\n"
    _publish(files)
    return {"marketplace": str(path), "plugins": plugins}
