# Codex Harness Connect

Evidence-driven local Codex plugins for unmodified agent CLIs. **Development alpha: not yet production-ready.**
This repository does not claim full Codex Desktop parity, vendor endorsement, or permission to reuse
consumer subscription credentials. A generated plugin is a package, not a verified integration.

## What the project is building

Codex remains the parent harness. Plugins delegate authorized tasks to installed native CLIs, retain
durable local job state, expose progress and terminal input through MCP, and support explicitly created
worktrees. A research skill inventories the installed version and requires primary documentation,
terms review, capability evidence and real acceptance tests before a new harness is labelled ready.
The [cursor wait tool](docs/waiting.md) observes up to eight existing jobs with compact responses;
Routine updates use `session_events(progress_only=true)`: bounded native model/permission mode,
workflow agents, tool names and error flags, without raw stdout, tool inputs or final report text.
Full transcripts are read only for scoped verification. Projection preserves pagination cursors;
an empty projected page may still advance past omitted output.
The [interaction check](docs/native-interaction-contract.md) tests a connected client's standard
MCP question form without launching a model or granting native tool permission.
Claude uses its existing native model, provider, login and settings. The connector does not gate
launches on subscription type or inferred routing. [Optional auth diagnostics](docs/native-auth.md)
do not establish effective routing, billing or permission to act.
Registered Claude [help discovery](docs/native-discovery.md) uses PTY output to avoid an observed
incomplete pipe-help response; missing flags and identity changes still stop a launch.

Requested adapters are Claude Code, official Grok Build and official Antigravity `agy`.
Claude uses whichever model/provider its existing configuration selects; there is no separate GLM package.

| Adapter | Current launch policy | Verified runtime |
| --- | --- | --- |
| Claude Code | Personal use of unmodified official CLI, existing model/provider and native auth/permissions | Native reply, resume and history after MCP reconnect tested on 2.1.286; approvals/teams pending |
| Grok Build | Held for effective subscription-only route and exclusion of native paid fallback | Prepared JSON contract; no inference |
| agy | Held for clarification of Google third-party-tool restriction | Pending |

The connector never extracts auth tokens, implements a subscription API proxy, installs a CLI, chooses
a paid fallback, or adds bypass/yolo arguments. CLI updates invalidate an inventory identity and require
review. The `connect_harness_cli` skill requires the parent agent to perform a fresh observation and the
maintenance workflow on every invocation, as described in [revalidation](docs/revalidation.md). An unchanged fingerprint does
not replace current policy review or native acceptance. Native credentials/settings remain owned by each vendor CLI.

Long-running jobs use durable request receipts, cursor waits and bounded event retention. Review
[storage and recovery](docs/storage.md) for capacity exhaustion, history pagination and upgrade limits.

## Host boundaries

Codex's own skills, AGENTS.md handling, memory, plugins, project context, worktrees and review tools
continue in the parent session. Relevant instructions and task context must be passed explicitly to the
child. Native CLI customization discovery remains native. Codex memory and ChatGPT memory are not
automatically copied. The connector does not claim that a subprocess inherits Codex sandbox or that
native approvals become Codex approvals. A PTY transcript is not Codex's internal subagent UI.

Claude native agent teams require interactive mode; headless Claude does not provide teammate parity.
Grok has its own ACP and stream formats. agy multi-turn NDJSON rejects CLI control RPC. The research
found an outdated Hermes skill saying agy lacks JSON; current Google documentation contradicts that.
These differences must remain visible rather than being hidden behind a generic success flag.

## Local development

Python 3.11+ is required; the current tested environment is Python 3.14. Install into a dedicated venv:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
codex-harness-connect inventory claude
codex-harness-connect revalidate claude --state-root /path/to/private/state
codex-harness-connect generate-marketplace /path/to/new/marketplace
```

The default generated MCP command is `codex-harness-connect`; install the console script on the Codex
host's PATH or generate with `--server-command /absolute/path/to/venv/bin/codex-harness-connect`.
Packages are for local Codex hosts. Installing a local plugin does not deploy a local CLI into Cloud.

Register an authorized, reviewed marketplace with `codex plugin marketplace add /absolute/path/to/repo`,
then install the desired package through Codex's plugin browser or supported `codex plugin add` command.
Start a fresh session after installation. Do not change model/auth/security defaults to make a test pass.

Claude uses its existing native default model/provider; there is no separate GLM skill.

The bundled marketplace contains `codex-harness-connect` and `harness-claude`,
`harness-grok`, `harness-agy`. Policy-held adapters expose evidence and discovery but cannot launch.
Existing plugin directories/marketplaces are not overwritten by the generator.

The configured display labels are `connect_harness_cli`, `with_claude_cli`, `with_grok_cli`,
and `with_agy_cli`. Skill interface metadata preserves these labels literally; the host controls any
additional namespace prefix in its UI. Package identifiers
stay unchanged so existing installations can update without adding duplicate plugins. Skill identifiers
use the equivalent hyphenated form, for example `with-claude-cli`, following the agent skill format.

## Verification

Synthetic tests validate process lifecycle and MCP contracts without vendor inference. Real acceptance
must separately prove streaming result semantics, approvals/denials, continuation, cancellation,
connection recovery, concurrent workspaces and Desktop behavior for each installed CLI version.
See [requirements](docs/requirements.md), [architecture](docs/architecture.md), [status](docs/status.md)
and the vendor research references. The [quality priorities](docs/quality-roadmap.md) compare relevant
source designs and define the next acceptance scenarios. Passing process tests is not proof that a
model completed a task.

## Security and privacy

Local job transcripts may contain project information. The supervisor must store them in a private
state directory and does not publish them. Never commit credentials, local environments or transcripts.
MCP write-tool annotations aid the host; they do not themselves enforce a sandbox. See SECURITY.md.

This project is independently maintained. OpenAI's support of MCP/plugins and vendor support of their
CLI interfaces do not mean they endorse this connector or guarantee its reliability.

## Current verified limits

The passing regression suite is separate from full production acceptance. On macOS a synthetic child
that immediately forks, calls setsid and is reparented can escape the supervisor's observed process
tree. The explicit acceptance test in `validation/test_daemon_containment.py` currently fails on macOS
and safely cleans its exact captured daemon. The connector reports `full_process_containment_verified`
as false. A completed/cancelled job describes the native leader and observed descendants, not guaranteed
termination of every detached process. Do not use this alpha where full containment is required.

Run that unresolved acceptance gate explicitly:

```sh
.venv/bin/python -m pytest -q validation/test_daemon_containment.py
```

The native Claude smoke used a separately installed wheel in a clean venv, a real stdio MCP client,
three no-tool prompts and a disposable empty workspace. It proved exact replies, same-ID resume and
recall of the first reply after reconnect. It did not test tool approvals, file edits, teams, Desktop UI
parity, long vendor tasks or the other three providers. See [validation status](docs/status.md).

Protocol success is separate from task acceptance. Claude outcomes report bounded permission-denial,
deferred-tool, API-error and rate-limit summaries; `task_acceptance` always requires parent verification.
Raw local transcripts can still contain tool inputs and project data and remain private.

`requirements-runtime.lock` records exact qualified runtime versions without personal paths. These are
version pins, not artifact hashes or a security certification. For a separate local runtime, use
`python -m pip install -c requirements-runtime.lock .` inside its venv, then generate a private local
marketplace with the absolute console-script path. Keep that host-specific marketplace out of Git.
