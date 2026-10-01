# Optional native Claude auth diagnostics

From alpha.14, Claude launch and resume use the unmodified installed CLI with its current model,
provider, login and native settings. The user explicitly selected this contract. No subscription
or effective-route preflight is required or injected, and no renewed plan/billing approval is requested.
The connector neither chooses a model/provider nor changes auth, billing, native permissions or settings.
Native CLI authentication failures and limits are reported without silently restarting or adding a fallback.

`auth_status` remains an optional read-only diagnostic in the router and Claude plugin. It uses the
reviewed executable's documented `auth status --json` in the intended workspace. It retains only curated
status fields, timestamps, binary identity and fixed reason codes. It excludes credentials, account IDs,
configuration directories, raw JSON and stderr. A diagnostic `route_eligible` or `held` value is historical
classification data, not a gate for current Claude launches, tool approval or effective-route attestation.

Actual acceptance on 2026-10-01 observed OAuth firstParty login status followed by a native init model
`glm-5.3-flashx`. Login status does not prove effective request routing. This contradiction must not be
presented as proof of Anthropic subscription inference or resolved by modifying the user's native profile.
The dedicated GLM plugin was subsequently removed at the user's request.

Billing and quota remain unobserved. Anthropic documents native subscription token authentication in
[authentication](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token), and native
provider/settings behavior in [environment variables](https://code.claude.com/docs/en/env-vars).
Using native defaults does not certify that every model/provider supports the same features or auto mode.

Historical receipts retain their original launch fingerprints and preflight contract. Recover an uncertain
job with `lookup_request`; never create a new request merely because the contract changed. Existing legacy
guarded jobs are not silently reclassified or replayed as new unguarded jobs. Native autoreview acceptance
is tracked separately in [autoreview](autoreview.md).
