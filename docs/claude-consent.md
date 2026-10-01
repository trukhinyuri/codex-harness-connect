# Claude questions and consent

Observed 2026-10-01. Use the current native interactive CLI for tool confirmations and native teams.
The connector's structured SDK consent mode remains closed while its public-plugin usage classification
and native acceptance are resolved. An MCP form diagnostic cannot resolve either condition.

## Choose the correct interface

Claude's [MCP documentation](https://code.claude.com/docs/en/mcp#require-approval-for-a-specific-tool)
requires human interaction for tools marked `anthropic/requiresUserInteraction`. Since CLI 2.1.199,
an approval from a noninteractive MCP permission host is converted to denial for such tools. The
documented Agent SDK callback can handle these requests. Removing that annotation would change consent
policy; this connector does not do so. A permission-host flag alone therefore cannot satisfy full
question and approval support.

The official [Python SDK v0.2.163](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.163)
reports bundled CLI 2.1.286, matching the installed version observed during this investigation. Its source
at commit `1ef6d8c71bb0e44a6b33fe61497864f21e17fdb7` is the candidate contract. No SDK installation or model
call occurred during this investigation. Source compatibility still needs native runtime acceptance.

## Preserve the native contract

The [permission types](https://github.com/anthropics/claude-agent-sdk-python/blob/1ef6d8c71bb0e44a6b33fe61497864f21e17fdb7/src/claude_agent_sdk/types.py)
provide the original `tool_use_id` and optional `agent_id`. The
[control handler](https://github.com/anthropics/claude-agent-sdk-python/blob/1ef6d8c71bb0e44a6b33fe61497864f21e17fdb7/src/claude_agent_sdk/_internal/query.py)
matches its separate control request ID and cancels pending callbacks on native cancellation. These
identities must stay distinct from a connector nonce or a permission sidecar's MCP request ID.

A future broker must bind the live callback to its job, native conversation, tool ID and original input.
Approval may return that same input once, with no persistent permission updates. Missing identity,
stale/cross-job replies, disconnect and cancellation must never approve a tool. A dead callback cannot
be restored as live consent from a saved record. Native hooks, deny/ask/allow rules and permission modes
continue to decide whether the callback is reached; the broker must not force prompting by changing them.

The [pinned transport](https://github.com/anthropics/claude-agent-sdk-python/blob/1ef6d8c71bb0e44a6b33fe61497864f21e17fdb7/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)
supports an explicit `cli_path` to the reviewed installed executable. Select the `claude_code` system
prompt preset and `user`, `project`, `local` setting sources. Relying on the SDK's default system prompt
sends an empty prompt. Leave model, permissions, fallback, tools, sandbox and auth overrides unset.
This preserves the intended construction; runtime tests must still verify loaded behavior and drift.

## Subscription and distribution boundary

The [current plan notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
says the announced separate SDK billing change was paused. SDK, `claude -p` and third-party usage still
consume subscription limits. This project assumes no additional credits or subscription purchase.

[Claude's legal guidance](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
describes ordinary individual SDK use and permits an end user to sign into the unmodified binary with
their own subscription. It also restricts developers offering consumer login or routing usage on users'
behalf. The [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview#get-started) separately requires
approval before third-party products offer claude.ai login or rate limits. Those documents do not settle
this public plugin's optional SDK mode. Explicit local `cli_path` and absent auth handling describe its
technical design; vendor clarification of that distribution/use case is the enablement dependency.
No credentials are collected or moved, and no vendor communication has been sent.

## Acceptance before enablement

Test exact input/ID binding, duplicate and simultaneous requests, stale answers and timeout/cancellation
first. Then use an explicitly trusted disposable workspace to verify native deny/approve outcomes,
annotated MCP tools, inherited rules, `AskUserQuestion`, continuation, stop/reconnect and local changes.
Verify actual human-facing Desktop and CLI forms separately. Native teams need their own interactive
acceptance. These gates retain the full [original requirements](requirements.md).
