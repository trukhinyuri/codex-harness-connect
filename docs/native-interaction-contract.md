# Native questions and external consent

Observed 2026-10-01. Alpha.6 adds a standard-form diagnostic; the native consent bridge remains closed.
Durable events, cursor waiting and explicit terminal input continue to provide the current job workflow.

## Check this connected client

Call `check_interaction` during an interactive session. The connector checks the client's advertised
form capability before showing a required, non-sensitive choice. URL-only and absent capabilities return
`unsupported`. Accept requires an exact enum value; an empty or malformed answer returns `invalid_response`.
Decline, cancel and timeout remain separate outcomes. A response received after the deadline is expired.
The default timeout is 45 seconds, and callers may shorten it. Caller cancellation propagates. Async
cancellation is cooperative, so slow cancellation cleanup can extend the observed duration.

This diagnostic launches no CLI or model, changes no settings and stores no answer in connector state.
The host may retain the exchange in chat history. `form_visible` reports the received choice; it cannot
attest that a human answered. MCP agent clients can generate answers themselves. The result grants no
native tool permission and must never serve as a reusable approval or enable a held provider route.
Fixtures and real stdio protocol tests cover its wire behavior; current Desktop/CLI rendering requires
separate host acceptance. Cloud also needs its own deployed server and client test.

OpenAI documents [MCP form elicitation](https://learn.chatgpt.com/docs/app-server#mcp-server-elicitation-requests).
The installed 0.159.2 schemas expose its form requests and `item/mcpToolCall/progress`; shipped Codex
Security tool metadata also describes standard form elicitation for interactive questions. Neither
schema presence nor another plugin's metadata proves this connector's rendering or negotiated capability.
Codex's own command/file/permission approvals remain separate from external-agent consent.

The pinned [Codex 0.159.2 handler](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/session/mcp.rs)
forwards ordinary form requests through its elicitation event. Several policy paths can instead return
an empty acceptance or decline. The diagnostic requires a nonempty exact choice and therefore rejects
empty acceptance. It does not imitate private approval metadata or infer who supplied a response.
This connector keeps the qualified MCP 1.30.0 dependency. The
[2026-07-28 migration](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28)
introduces a different input-required contract; adopting that version requires separate protocol and
host acceptance rather than an automatic dependency update.

Claude documents [non-interactive MCP permission hosts](https://code.claude.com/docs/en/cli-reference)
and [SDK questions/approval callbacks](https://code.claude.com/docs/en/agent-sdk/user-input). A documented
flag is insufficient evidence for its complete payload, native request identity and cancellation
semantics on the installed version. Do not infer requests from TUI text or hand-build undocumented
CLI control RPC. [Current Claude findings](claude-consent.md) identify the official SDK callback candidate
and the permission-host limitation. Native teams still require their own interactive contract.

## Proposed broker and acceptance

1. Persist each verified native interaction with job/native identity, original request and choice scope,
   expiry and state. Keep a connector nonce separate from any native request ID. Missing identity or
   scope remains unknown; never invent it.
2. Use a separate explicit interactive broker tool, leaving `wait_sessions` read-only. Negotiate standard
   form support and confirm the client is interactive. Unsupported clients receive structured pending
   data for an ordinary parent question; headless runs must not await hidden UI.
3. Validate the answer against the still-pending request and deliver it once. Reject stale, duplicate,
   cross-job and malformed responses. User input does not grant a Codex sandbox permission. Do not
   broaden a single-call answer into persistent rules or an “always” choice with different native scope.
4. Treat progress as an optional hint during an active correlated call. Durable state/cursors must remain
   usable when hints are ignored or a connection drops. Timeout, decline, cancellation and disconnect
   never mean approval; native resolution must be checked separately.
5. Test negotiated/absent form support, exact accept/decline/cancel, stale replies and concurrent requests
   with fixtures first; then verify harmless interactive Desktop and CLI behavior through an allowed
   interface. Native provider approval mapping and Cloud need separate acceptance.

The documented [ChatGPT event integration](https://developers.openai.com/plugins/build/mcp-events) uses
webhooks; it does not prove local stdio streaming or idle-job wakeup. A [local MCP install](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
does not deploy a CLI into Cloud. Do not rely on experimental plugin APIs, unverified event-stream methods,
or bypass a denied UI interface to imitate native parity.

Consumer use stays inside the unmodified official CLI with its native sign-in. Anthropic's
[legal guidance](https://code.claude.com/docs/en/legal-and-compliance) distinguishes end-user CLI sign-in
from a developer offering login or intermediating requests. Its [current plan notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
says the announced separate SDK credit change was paused; no new credit is assumed here. A quota notice
does not authorize every product/service arrangement. Existing provider holds remain applicable.
