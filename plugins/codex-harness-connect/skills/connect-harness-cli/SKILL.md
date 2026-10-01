---
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
Choose the session deadline for the requested workload, including CLI startup and hooks. Keep wait
deadlines separate from the native session timeout; poll progress without shortening a long task.
Follow the provider skill for workload-specific guidance; a timeout is not a native permission denial.
Use native interactive mode for native terminal/teams features;
TTY text is not the Codex internal subagent UI. Never add yolo or permission-bypass options, extract
auth tokens, read hidden memory, introduce a paid fallback or share credentials. Observing an existing
native bypass mode does not prove the connector enabled it. Follow with_claude_cli for scoped mode
selection and actual tool observation. Current policy holds require owning vendor evidence.
