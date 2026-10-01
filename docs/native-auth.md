# Native Claude auth preflight

The connector uses the reviewed, unmodified Claude executable's `auth status --json` before a model
launch. It runs with the intended workspace and inherited environment, without a shell or login action.
The detached worker repeats the check immediately before starting Claude. An unavailable, API,
overridden or unknown route stops the launch; it never selects another authentication method.

`auth_status` is exposed only by the router and Claude plugin. Supply `adapter: claude`, the intended
`cwd` and the SHA-256 from fresh reviewed inventory. It returns only known auth/provider/plan fields,
documented override names, timestamp, reviewed binary hash and fixed reason codes. Account identifiers,
configuration directories, credentials, raw JSON and stderr are excluded. The read-only tool does not
store its observation; the worker stores a sanitized preflight event. The host may retain tool results.

The current own-subscription condition is logged-in `claude.ai`, `firstParty` and a known Pro, Max,
Team or Enterprise plan, with no recognized auth or routing override present. Presence is a hold even
for an empty value. This is a conservative connector policy, not a claim that every such variable
necessarily causes API billing. It does not read settings to resolve overrides or erase variables.
The existing vendor-policy holds for GLM, Grok and agy remain separate.

The probe checks executable identity before and after, limits stdout to 64 KiB and nominal run time
to 10 seconds, suppresses stderr and terminates the probe's process group on failure. Cleanup adds
up to 1.2 seconds; this does not establish containment of detached daemons. Worker cancellation during
the probe prevents a later model launch. Malformed, duplicate-key, non-standard JSON, unexpected types,
unknown auth values and inconsistent exit status cannot qualify a route.

## What the observation cannot prove

`billing_guarantee` is always false. A subscription auth observation does not show remaining included
quota, whether usage credits are enabled or whether future calls will keep the same route. Native
settings, API-key helpers, hooks and concurrent account changes remain owned by Claude. Settings can
apply or change environment values during a session; the connector does not inspect credential files
or promise an immutable billing route. An inherited environment observation is not proof of all
effective settings. A terminal's status is not evidence of the Desktop MCP server's environment.

For a task restricted to included subscription usage, obtain a current confirmation that usage credits
are disabled before model calls. `/usage` or Claude Settings → Usage shows the user's current usage state;
the connector does not scrape private billing endpoints, purchase funds or change that setting.
No remaining-quota value is inferred from a successful login. Stop at a limit or ambiguous route.

## Upgrade recovery

Adding the mandatory guard changes the public launch contract and its request fingerprint. For an
uncertain alpha.6 request, recover the original job with `lookup_request`; do not retry it under a new
request ID. A guarded start using an old unguarded receipt fails as a different launch, while the
original receipt and job remain available. No receipt is deleted or silently upgraded into auth proof.

## Primary references

- [CLI reference](https://code.claude.com/docs/en/cli-reference): native auth status and subscription versus Console login.
- [Environment variables](https://code.claude.com/docs/en/env-vars): API-key precedence, provider selectors and settings environment behavior.
- [Usage and credits](https://code.claude.com/docs/en/costs#check-your-usage-credits-spend): subscription usage and usage-credit visibility.
- [Manage usage credits](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans): paid continuation and disabling credits.

Documentation, synthetic tests and current native acceptance are reported separately in
[status](status.md). This preflight is not vendor endorsement or production qualification.
