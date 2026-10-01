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
Keep the parent Codex task context and verify relevant AGENTS.md instructions. Pass required instructions,
skill results and user-approved context explicitly in the prompt. Do not read or export hidden memory,
credentials or settings. Native harness customizations are loaded by that harness itself.
For native approvals or native team features, use interactive PTY; don't claim print mode supports them.
Use start_session once, then wait_sessions with acknowledged cursors and drain session_events when
changes are available. Waiting never launches/resumes/cancels native jobs and does not consume events.
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
