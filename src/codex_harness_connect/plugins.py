"""Generate local Codex packages from explicit, reviewed adapter evidence."""
from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .adapters import ADAPTERS, get_adapter

RESEARCH_SKILL = """---
name: connect-harness-cli
description: Connect or revalidate an installed harness CLI against current Codex, research vendor terms, and fix verified compatibility drift.
---

Use this workflow for BOTH first connection and EVERY repeated invocation. Keep Codex as the parent agent.
Re-running this skill is a maintenance task, not permission to reuse an old green report. Preserve the
original requested outcomes and all quality gates; a renamed/generated package is not completion.
Apply the user's research, execution, budget and outcome-decomposition instructions where available.
Establish Done and validation before editing. Retain an existing destination and evidence rather than
creating duplicate plugins. Never silently reduce the task to inventory or synthetic tests.
1. Get the executable the user intends to connect. Never install or log in on their behalf implicitly.
2. For a registered adapter call revalidate_cli on EVERY invocation, before relying on prior evidence.
   This probes the target, PATH Codex, discovered Desktop bundle/CLI, and connector/dependency identities.
   Read its comparison and mandatory acceptance gates. Changed, absent or unknown identity invalidates
   prior qualification; unchanged identity still requires a current docs/policy and acceptance review.
   It never proves latest available version or full compatibility. Check Desktop's native updater when
   available; distinguish running/installed versions from an available update. Do not update implicitly.
   For an unknown user-designated trusted executable use inventory_candidate, then implement reviewed
   discovery/adapter support. Top-level help alone is not complete command or feature coverage.
3. Read the vendor's current official docs, terms, release notes and source when available. Enumerate
   subcommands, flags, interactive commands, output schemas, approvals, auth/billing, resume, cancellation,
   teams, skills, MCP, worktrees and version drift. Do not treat CLI help or an OSS license as permission.
4. Produce a current capability dossier bound to the observation fingerprint, date, actual host and
   native versions. Each capability needs a source, installed-version evidence, test result and status
   (documented / detected / tested / blocked / unavailable). Include auth route/subscription vs API,
   recursive commands, native output/control schemas and version constraints. Preserve contradictions.
   Compare with previous evidence, identify affected contracts and implement necessary fixes and useful
   supported improvements. Review code, package/schema and dependency drift, not only version strings.
5. Explain host boundaries: Codex memory, plugins, context and skills stay with Codex; only explicitly
   supplied task context reaches the child. Codex sandbox/approvals are not automatically inherited.
   When the task needs form-based questions, use check_interaction to qualify this connected client's
   advertised standard form route. It launches no native CLI or model. An accepted check does not
   attest to a human or approve native work. Do not enable an unqualified consent bridge from it.
6. If the repository destination is absent, ask for it before publishing; local reversible work can continue.
   Use the user-requested repository/name when already provided. Never publish transcripts or credentials.
7. Implement and test the adapter/package corrections in the existing project. Use reviewed staging and
   rollback for updates; the generator refuses existing files. Unknown CLIs require reviewed code, not
   guessed flag translation. Run affected regressions, the required full checks and an independent review
   when the price of error warrants it. Never fix compatibility by relaxing sandbox or permissions.
   Do not mark an adapter ready from a generated manifest or passing synthetic test.
8. Validate startup/auth failures and limits, actual vendor results/stream semantics, denial/approval,
   resume, cancellation/descendants, reconnect/uncertain requests, long tasks, bounded storage, concurrent
   worktrees, native teams and CLI customizations. Separately check current Codex Desktop and CLI tool
   discovery/invocation, progress/questions/stop/continuation/review, skills, AGENTS.md, explicit context,
   memory boundaries, plugins/MCP and permissions. Cloud requires its own supported deployment and tests.
   Test permitted routes only. A vendor policy hold cannot be resolved by a passing synthetic test.
   Record every gap and its next action. Inaccessible UI is unverified; never bypass a denied interface.
   Stop calling the task complete if required evidence is missing; explain incompatibility/blockers.
9. Install through the documented marketplace mechanism only when authorized. Start a fresh Codex session
   to load tools/skills and invoke the installed tools, not just an editable source server. Re-observe
   identities after fixes/install and bind the final test report to that fingerprint; repeat affected
   checks on any intervening update. Preserve model, speed, reasoning, auth, payment and security defaults.
   Use documented MCP/plugin mechanisms. Experimental app-server plugin/* methods are not a production
   client dependency. Report separately documentation, inference, synthetic tests and native acceptance.

For long-running jobs, start once and retain the returned job id and acknowledged event cursor. Use
wait_sessions for 1..8 known jobs to avoid repeated empty transcript polls. It returns compact change
metadata without consuming events; drain session_events from the acknowledged cursor before advancing
it. A wait timeout or cancellation leaves the native jobs running. Request explicit cancel_session and
verify its final state to stop a job. A tool timeout
does not prove the child exited. Confirm cancellation with authoritative state. Never automatically retry a
model request after an uncertain outcome. Choose a fresh 32-character lowercase hex request_id before
start_session or resume_session; retain it before calling. Use lookup_request after an uncertain response.
The same request id and identical launch returns the existing job, never another inference process.
Use storage_status to inspect finite receipt capacity and retention gaps. At capacity recover existing
IDs; never delete receipts, rotate stores automatically or retry an uncertain request in another store.
list_sessions is a compact bounded page: retain its next_cursor while has_more is true.
Batch requires the exact resolved workspace path explicitly acknowledged by the user as trusted because
Claude --print skips its trust dialog. Never invent that acknowledgement or treat it as tool approval.
For Claude, preserve the installed CLI's current model, provider, login and settings. Do not perform
subscription/route checks as a launch gate or require plan/billing confirmation. auth_status is an
optional sanitized login diagnostic, not effective-route attestation or launch authorization.
Explicit invocation authorizes scoped native work; the CLI handles its own authentication and errors.
Do not inject a model, provider, API fallback or settings override. Native permissions remain separate.
Use native interactive mode for native terminal/teams features;
TTY text is not the Codex internal subagent UI. Never add yolo or permission-bypass options, extract
auth tokens, read hidden memory, introduce a paid fallback or share credentials. Observing an existing
native bypass mode does not prove the connector enabled it. Follow with_claude_cli for scoped mode
selection and actual tool observation. Current policy holds require owning vendor evidence.
"""


def _plugin_spec(destination: Path, profile: str | None, command: str) -> tuple[dict, dict]:
    if profile:
        adapter = get_adapter(profile)
        name = f"harness-{profile}"
        description = adapter.notes
        display_name = f"with_{adapter.executable}_cli"
        if profile != adapter.executable:
            variant = profile.removeprefix(adapter.executable + "-").replace("-", "_")
            display_name += f"_{variant}"
        skill_name = display_name.replace("_", "-")
        body = f"""---
name: {skill_name}
description: Delegate authorized local work to the unmodified {profile} CLI through Harness Connect.
---

Use revalidate_cli and describe_adapter before starting work; follow connect_harness_cli for maintenance
if identities changed or qualification is incomplete. This package is for {profile} only.
Policy: {adapter.policy}. {description}
For Claude, use the CLI's current default model/provider and existing native settings without route or
subscription launch gates. auth_status is optional diagnostic only, not a prerequisite for launching.
It does not attest to effective routing, quota or billing. Explicit invocation authorizes scoped work; do not request that action approval again
or block on subscription plan changes. Reuse exact workspace trust already confirmed by the human.
Keep unobserved billing facts unknown; never change billing/auth or introduce an API fallback.
Native tool approvals remain separate and must follow the native permission mechanism.
An observed native bypassPermissions mode or TUI label is not proof that the connector enabled it.
Do not automatically cancel a scoped no-tool review solely because that label appears. Observe actual
tool activity and respect the requested scope; a prompt restriction is not sandbox enforcement.
When the task requires native tool review, explicitly use the supported per-launch
--permission-mode=default option rather than changing global settings or requesting action approval again.
Verify the effective native mode; never claim default/auto is active from the supplied option alone.
Never inject a bypass option or weaken permissions to recover a failed or denied action.
Keep the parent Codex task context and verify relevant AGENTS.md instructions. Pass required instructions,
skill results and user-approved context explicitly in the prompt. Do not read or export hidden memory,
credentials or settings. Native harness customizations are loaded by that harness itself.
For native approvals or native team features, use interactive PTY; don't claim print mode supports them.
Use start_session once, then wait_sessions with acknowledged cursors and drain session_events when
changes are available. Use session_events(progress_only=true) for routine progress: it omits raw
transcript, result text and hook output while preserving page cursors. Drain through unchanged cursor,
even when a projected page contains no visible events. Use full transcript only for explicit scoped
verification; never publish unrelated private native context. Waiting does not consume events.
Keep OS job id and native conversation
id separate. Choose and retain a fresh 32-character lowercase hex request_id before launching; recover an
uncertain response with lookup_request. Never automatically restart a job whose outcome is uncertain.
Use send_input for explicit user choices, cancel_session to stop and verify its final state, and
resume_session with the source_session_id of a terminal known job in the same workspace. Explicitly
supply reviewed native_options (for example --effort=ultracode) when needed on resume; they are not
automatically copied from an earlier launch. Only typed
native protocol can confirm its conversation id; arbitrary TUI text cannot. Do not invent native ids.
Batch requires the exact workspace path explicitly authorized as trusted by the user; --print skips
Claude's trust dialog. This acknowledgement does not approve tools or establish sandbox containment.
Review changed files and tests with Codex's ordinary review tools. Jobs are external tasks, not native Codex
subagents, and child tools have their own permission enforcement. Policy-held adapters cannot launch.
"""
        if adapter.policy != "personal-unmodified-cli":
            body = f"""---
name: {skill_name}
description: Inspect {profile} CLI readiness and resolve documented integration gaps.
---

Use revalidate_cli and describe_adapter for this requested adapter. Current policy: {adapter.policy}.
{description}
Explicit invocation authorizes investigation and scoped fixes; never ask the human to approve the
same work again. The current adapter cannot launch. This is an integration gap, not an approval
request: another user confirmation cannot resolve missing vendor evidence or an effective-route check.
Continue independent project checks and fix the owning adapter when authoritative evidence permits.
Do not substitute another harness without user authorization or bypass the hold with direct execution.
Do not read credentials, change auth/billing/security or introduce paid fallback. Native permissions
remain native. Report exactly which gate is unresolved, its primary sources and the next check.
Claude-specific --print trust, Ultracode, resume and team features are not implied for this adapter.
"""
    else:
        name = "codex-harness-connect"
        description = "Research and connect local agent CLIs with explicit capability and policy evidence."
        display_name = "connect_harness_cli"
        skill_name, body = "connect-harness-cli", RESEARCH_SKILL
    args = ["serve"] + (["--profile", profile] if profile else [])
    manifest = {
        "name": name, "version": __version__.replace("a", "-alpha."), "description": description,
        "skills": "./skills/", "mcpServers": "./.mcp.json",
        "interface": {"displayName": display_name, "shortDescription": "Local CLI delegation",
                      "longDescription": description, "developerName": "Yuri Trukhin",
                      "category": "Productivity", "capabilities": ["Read", "Write"]},
    }
    server_name = "chc_" + (profile.replace("-", "_") if profile else "router")
    files = {destination / ".codex-plugin/plugin.json": json.dumps(manifest, indent=2) + "\n",
             destination / ".mcp.json": json.dumps(
                 {"mcpServers": {server_name: {"command": command, "args": args}}}, indent=2) + "\n",
             destination / "skills" / skill_name / "SKILL.md": body,
             destination / "skills" / skill_name / "agents/openai.yaml":
             "interface:\n"
             f"  display_name: {json.dumps(display_name)}\n"
             "  short_description: \"Local CLI delegation\"\n"}
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
    specs += [_plugin_spec(plugin_root / f"harness-{name}", name, command) for name in ADAPTERS if name != "claude-glm"]
    plugins = [result for result, _ in specs]
    catalog = {"name": "codex-harness-connect", "interface": {"displayName": "Harness Connect"},
               "plugins": [{"name": p["name"], "source": {"source": "local", "path": "./plugins/" + p["name"]},
                            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                            "category": "Productivity"} for p in plugins]}
    files = {path: content for _, files in specs for path, content in files.items()}
    files[path] = json.dumps(catalog, indent=2) + "\n"
    _publish(files)
    return {"marketplace": str(path), "plugins": plugins}
