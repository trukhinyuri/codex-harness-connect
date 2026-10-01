# Grok Build prepared contract and route gate

Reviewed on 2026-10-01. This dossier contains public vendor documentation and source references only. The implementation prepares arguments and parses bounded output; it does not launch Grok, change authentication or permissions, or establish subscription access.

## Product and version provenance

Grok Build is an official xAI coding product. xAI links its official source repository, which contains the Rust CLI. The executable documented by the vendor is `grok`. [Product](https://x.ai/build), [documentation](https://docs.x.ai/build/overview), [official repository](https://github.com/xai-org/grok-build).

The immutable source snapshot used for the wire contract is commit `37949780c144e37df692e3d669051a21fec24f20`; its `SOURCE_REV` is `c4ea71cfdbcdb21e32e41bc25a0043d7d4836714`. The public repository is a periodically synchronized source export. This snapshot has not been established as the source of binary release 1.0.44. CLI argument construction is restricted to the separately reviewed 1.0.44 help surface; the source-supported parser remains a prepared contract until runtime compatibility and the route gate are satisfied. [Commit](https://github.com/xai-org/grok-build/commit/37949780c144e37df692e3d669051a21fec24f20), [source revision](https://raw.githubusercontent.com/xai-org/grok-build/37949780c144e37df692e3d669051a21fec24f20/SOURCE_REV).

## Argument contract

Interactive mode requires the native TUI in a PTY. Batch mode uses `--single=<prompt>` and `--output-format=json`; the vendor documents JSON as one final object, distinct from its streaming formats. Prompt values are passed as one argument; interactive positional prompts follow `--`. The builder exposes no free-form arguments, environment changes, model/provider selection or authentication controls. [Headless formats](https://docs.x.ai/build/cli/headless-scripting), [CLI reference](https://docs.x.ai/build/cli/reference).

A new session requires a caller-owned UUID passed through `--session-id=<uuid>`. Existing sessions use `--resume=<uuid>`. The reviewed native help and CLI reference make `--session-id` new-session only; the scripting page's resume example must not override that rule. `--no-auto-update` is documented as a wrapper option and is absent from the reviewed native help, so it is not passed to the native binary. An explicit `subscription_entitlement_confirmed=True` acknowledgement is required before constructing either candidate.

The builder preserves native permission settings: it injects no permission mode, allow/deny rule, trust flag, always-approve or bypass flag. In the pinned headless client, a permission request that reaches the client without its native yolo option returns `RequestPermissionOutcome::Cancelled`. Project trust and authentication must already meet native requirements; this adapter does not grant trust or start login. [Pinned headless client, `request_permission` and setup](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-pager/src/headless.rs).

## Final JSON contract

Pinned `build_json_result` emits string fields `text`, `stopReason`, `sessionId` and `requestId`. An absent response request ID becomes an empty string. Optional fields include `thought`, `usage`, `structuredOutput` and string `structuredOutputError`. Reviewed stop tokens are `end_turn`, `max_tokens`, `max_turn_requests`, `refusal` and `cancelled`. Native error output uses `type: "error"` and a string `message`, without session identity. Current public source retains these core fields. [Pinned JSON construction and stop conversion](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-pager/src/headless.rs#L278), [current headless source](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/src/headless.rs).

Adapter policy verifies the native UUID against the reviewed launch. Only `end_turn`, no structured-output error, and exit code zero count as success. A native error counts as failure without identity. Malformed, duplicate-key, nonfinite, truncated, oversized, excessively nested, unknown-stop or conflicting-identity output remains unknown. Extra JSON keys cannot replace native identity. The parser limits raw output to 32 MiB, depth to 64, containers to 100,000 and previews to 4,096 characters. It does not retain thought or usage. Exit status alone never proves semantic success; missing final JSON after termination remains unknown. Cancellation execution is outside this prepared module.

## Why the subscription route remains blocked

Acknowledged subscription entitlement does not establish which native credentials a model will use. Vendor documentation gives per-model credential priority as model API key, model environment key, active session token, then `XAI_API_KEY`. `disable_api_key_auth` rejects first-party API-key authentication and substitutes a session token for first-party xAI keys at request time, but explicitly leaves third-party BYOK endpoints working. `force_login_team_uuid` also enables that policy; neither is an entitlement verifier. [Authentication and login policy](https://docs.x.ai/build/enterprise).

The native auth selector can prefer a cached session yet fall back to `xai.api_key` when that session is absent or expired. `--oauth` only starts an auth welcome flow; it is not documented as suppressing cached API-key or per-model BYOK fallback. No subscription-only invocation flag was established in the reviewed CLI reference. [Current native auth selection](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/src/agent/auth_method.rs), [CLI reference](https://docs.x.ai/build/cli/reference).

`grok inspect --json` exposes resolved login-policy fields, including `apiKeyAuthDisabled`, but its report has no selected model, effective provider/endpoint or live auth-route field. Therefore a true policy value alone cannot release the gate. A proposed child-only `GROK_DISABLE_API_KEY_AUTH` policy would still leave BYOK coverage unresolved and would change authentication policy; it has not been run or implemented. [Inspect report and login policy source](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/src/inspect/mod.rs).

## ACP introspection conclusion

ACP `initialize` returns a default auth-method ID and model state, but it is not a read-only status operation: the pinned implementation reloads credentials, can silently refresh a cached token, starts background work and performs state cleanup. It was not executed. Creating a session cannot repair these side effects. [Pinned ACP initialization](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs#L92).

Its model state carries `currentModelId` and available model information. Pinned model serialization exposes ID, name, description, context size, agent type and reasoning metadata, without resolved endpoint, credentials or auth route. Model entries and auxiliary samplers can independently resolve endpoint and credential overrides. Thus default auth-method ID plus model ID plus API-key-disable policy cannot prove subscription-only execution, including auxiliary calls. [Pinned model state](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/mvp_agent/agent_ops.rs), [pinned model serialization and auxiliary routing](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/config.rs#L5104).

## Evidence needed to release the gate

The gate requires an official, non-inference, non-mutating native preflight contract for the exact launched version and working directory. It must attest live included-subscription authentication, the effective main and auxiliary model/provider routes, and enforced rejection of first-party API-key and third-party BYOK fallback for that same invocation, including expiry/refresh. Documentation or source establishing such enforcement and a public runtime result schema would be sufficient evidence to design verification. Current inspect and ACP metadata do not establish it. The implementation deliberately keeps `require_grok_subscription_route` closed for every policy value; candidates and parser are reviewable while launches remain disabled.

## Verification

`PYTHONPATH=src python3 -m unittest discover -s tests -v`: 20 tests passed. Tests cover safe argument boundaries, unchanged permission policy, explicit entitlement, unconditional route gating, source-defined JSON fields, identity matching, semantic outcomes and parser limits. No Grok inference, auth-policy change or installation was used for these tests.
