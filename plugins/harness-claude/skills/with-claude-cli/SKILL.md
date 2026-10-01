---
name: with-claude-cli
description: Delegate authorized local work to the unmodified claude CLI through Harness Connect.
---

Use revalidate_cli and describe_adapter before starting work; follow connect_harness_cli for maintenance
if identities changed or qualification is incomplete. This package is for claude only.
Policy: personal-unmodified-cli. Own-account unmodified CLI using its current configured model and provider. Auth stays inside Claude Code. Headless teams are not supported; use interactive sessions for native teams.
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
Choose timeout_seconds for the requested workload, including native startup and hooks. A previous
Ultracode review took about 21 minutes: a 60-second deadline is unsuitable for comparable work.
For comparable long reviews allow a bounded deadline such as 1800 seconds and observe progress with
wait_sessions. This is workload guidance, not a universal minimum; honor explicit user deadlines.
A timed_out job without a typed result is incomplete, not a native denial. Verify terminal state
and never automatically relaunch a job whose outcome is uncertain.
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
