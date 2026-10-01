"""Version-aware native CLI launch contracts, without API or auth interception."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .discovery import inventory

Mode = Literal["batch", "interactive"]
BLOCKED_FLAGS = {
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
    "--always-approve", "--yolo", "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust", "--oauth", "--no-plan", "--restricted",
    "--safe-mode", "--bare", "--disable-slash-commands", "--no-session-persistence",
    "--no-subagents", "--system-prompt-override", "--system-prompt", "--client-data-url",
    "--output-format", "--input-format", "--print", "--single", "--prompt-file",
    "--permission-mode", "--mode", "--sandbox", "--background", "--bg", "--cloud",
    "--environment", "--remote-control", "--leader-socket", "--cwd", "--project",
    "--new-project", "--settings", "--setting-sources", "--mcp-config",
    "--allowedTools", "--allowed-tools", "--allow", "--add-dir", "--plugin-dir",
    "--plugin-url", "--permission-prompts", "--fallback-model", "--tools", "--disallowedTools",
    "--disallowed-tools", "--strict-mcp-config", "--append-system-prompt",
    "--system-prompt-file", "--append-system-prompt-file", "--session-id", "--fork-session",
}
# These features need dedicated typed contracts; don't silently pass them through.
OWNED_FLAGS = {"--resume", "--continue", "--conversation", "--worktree", "--worktree-ref"}
VALUE_OPTIONS = {"--model", "--effort", "--reasoning-effort", "--name"}
BOOLEAN_OPTIONS = {"--verbose", "--ax-screen-reader", "--include-partial-messages",
                   "--include-hook-events", "--forward-subagent-text"}


@dataclass(frozen=True)
class Adapter:
    name: str
    executable: str
    policy: str
    sources: tuple[str, ...]
    notes: str


ADAPTERS = {
    "claude": Adapter(
        "claude", "claude", "personal-unmodified-cli",
        ("https://code.claude.com/docs/en/legal-and-compliance",
         "https://code.claude.com/docs/en/cli-reference",
         "https://code.claude.com/docs/en/agent-teams"),
        "Own-account unmodified CLI. Subscription login must stay inside Claude Code. "
        "Headless teams are not supported; use interactive sessions for native teams.",
    ),
    "claude-glm": Adapter(
        "claude-glm", "claude", "vendor-confirmation-required",
        ("https://docs.z.ai/devpack/tool/claude",
         "https://docs.z.ai/legal-agreement/subscription-terms"),
        "Claude Code + an existing GLM Coding Plan configuration is distinct from ZCode. "
        "This project's orchestration classification needs vendor confirmation.",
    ),
    "grok": Adapter(
        "grok", "grok", "subscription-route-confirmation-required",
        ("https://docs.x.ai/build/overview", "https://github.com/xai-org/grok-build"),
        "Official Grok Build CLI. Entitlement alone does not prove the effective model/auth route. "
        "Native API-key/BYOK fallback must be excluded before launch. Discovery only until then.",
    ),
    "agy": Adapter(
        "agy", "agy", "vendor-confirmation-required",
        ("https://antigravity.google/docs/cli/headless",
         "https://www.antigravity.google/terms"),
        "Native headless CLI exists; Codex-to-agy service access is not confirmed "
        "permitted under the third-party-tool restriction. Discovery only for now.",
    ),
}


def get_adapter(name: str) -> Adapter:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise ValueError("Unknown adapter; research and review it before registering") from None


def validate_options(options: list[str], known_flags: list[str]) -> list[str]:
    """Keep native feature options; refuse bypass and ambiguous positional/subcommand input."""
    result = []
    for option in options:
        if not option.startswith("--") or "\x00" in option or len(option) > 32_768:
            raise ValueError("Native options require --flag or --flag=value form")
        flag = option.split("=", 1)[0]
        if flag in BLOCKED_FLAGS | OWNED_FLAGS:
            raise ValueError(f"{flag} requires a reviewed dedicated integration or is forbidden")
        if flag not in known_flags:
            raise ValueError(f"{flag} is absent from this installed CLI's help")
        if flag in VALUE_OPTIONS:
            if "=" not in option or not option.split("=", 1)[1]:
                raise ValueError(f"{flag} requires --flag=value form")
        elif flag in BOOLEAN_OPTIONS:
            if "=" in option:
                raise ValueError(f"{flag} does not accept a value")
        else:
            raise ValueError(f"{flag} needs a dedicated reviewed capability contract")
        result.append(option)
    return result


def launch_contract(
    name: str, prompt: str, cwd: str, mode: Mode, expected_sha256: str,
    native_session_id: str | None = None, options: list[str] | None = None,
    batch_workspace_confirmation: str | None = None,
) -> dict:
    adapter = get_adapter(name)
    if adapter.policy != "personal-unmodified-cli":
        raise PermissionError(f"{name}: {adapter.policy}. {adapter.notes}")
    if not isinstance(prompt, str) or not prompt or len(prompt) > 100_000 or "\x00" in prompt:
        raise ValueError("Prompt must contain 1..100000 characters without NUL")
    directory = Path(cwd).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("cwd must be a real directory")
    if mode == "batch" and batch_workspace_confirmation != str(directory):
        raise PermissionError(
            "Claude --print skips its workspace trust dialog. Batch requires the exact resolved "
            "workspace path explicitly authorized as trusted by the user; use interactive mode "
            "when this confirmation is absent. This does not approve native tool requests."
        )
    current = inventory(adapter.executable)
    if current["binary_sha256"] != expected_sha256:
        raise ValueError("CLI identity changed; inventory and review the installed version again")
    if current["help"]["exit_code"] or current["version"]["exit_code"]:
        raise ValueError("CLI probes failed")
    extra = validate_options(options or [], current["flags"])
    argv = [current["resolved_path"]]
    if native_session_id:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", native_session_id):
            raise ValueError("Invalid native session id")
        argv += ["--resume", native_session_id]
    if mode == "batch":
        argv += ["--print", "--output-format", "stream-json", "--verbose"]
        # Native Claude decides its own tool permissions. No allow/bypass list is injected.
    elif mode != "interactive":
        raise ValueError("Invalid mode")
    argv += extra
    # A positional prompt beginning with '-' could be interpreted as a CLI option.
    if prompt.startswith("-"):
        raise ValueError("Prompt must not start with '-' (ambiguous native CLI option)")
    argv.append(prompt)
    return {
        "argv": argv, "cwd": str(directory), "mode": "pipe" if mode == "batch" else "pty",
        "adapter": name, "identity": current["binary_sha256"],
        "protocol": "claude-stream-json" if mode == "batch" else None,
        "permissions": "Native CLI policies apply; Codex sandbox is not inherited by assertion",
    }
