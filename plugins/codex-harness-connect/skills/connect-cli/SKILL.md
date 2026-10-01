---
name: connect-cli
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
