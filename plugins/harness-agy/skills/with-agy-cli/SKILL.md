---
name: with-agy-cli
description: Delegate authorized local work to the unmodified agy CLI through Harness Connect.
---

Use inventory_cli and describe_adapter before starting work. This package is for agy only.
Policy: vendor-confirmation-required. Native headless CLI exists; Codex-to-agy service access is not confirmed permitted under the third-party-tool restriction. Discovery only for now.
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
