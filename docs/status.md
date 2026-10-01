# Validation status

Observed 2026-10-01, Europe/Amsterdam. Development alpha; the full completion gates in
[requirements.md](requirements.md) are not achieved. This status distinguishes actual tests from source
claims and generated artifacts.

| Layer | Actual evidence | Limit |
| --- | --- | --- |
| Main regression suite | 179 tests and 74 subtests passed in the final integrated suite on macOS/Python 3.14.7; Ruff passed | Synthetic processes and protocol fixtures; hosted CI still pending |
| Claude installed package | Built wheel installed into a clean venv with its own dependencies; console/MCP handshake succeeded | One local platform |
| Claude native roundtrip | Claude Code 2.1.286: two exact replies, same-ID resume, then original reply recalled after MCP reconnect; empty workspace stayed empty | Three no-tool prompts; no approval/teams/file-edit/UI claim |
| Claude status parser | Updated parser replayed all three recorded native stdout streams with verified identity/success, zero denials and parent-verification requirement | No new inference; actual native denial/rate-limit cases remain untested |
| Lifecycle faults | Worker loss, cancellation, SQLite contention, bounded retention, request id recovery and profile isolation tested | Only kernel-observed processes |
| Full containment | Explicit macOS setsid/reparenting acceptance gate failed; exact captured test processes were cleaned | Production blocker; not hidden by xfail or counted as passing regression |
| Grok | Official docs/source, installed 1.0.44 alpha help/inspect; prepared JSON contract | Native effective auth/model route and absence of paid fallback unproven; no inference |
| GLM | Official supported-tool docs and subscription terms read; profile isolation design | Existing usable profile and this orchestration's use classification unverified; no inference |
| agy/Hermes | Current Google docs/terms, installed1.2.14 help, pinned Hermes source | Applicable permission unresolved; no inference |
| Desktop | Backend extension mechanism documented | UI automation denied access to Codex; installation/UI acceptance not yet verified |

Local account observations, absolute home paths, conversations and raw CLI readbacks are private and
not published. No auth, payment, permission, security or model defaults were changed for these tests.
CLI auto-update changed the observed Claude version from 2.1.284 to 2.1.286; live evidence applies to
2.1.286. Future versions require a new inventory and acceptance review.

## Policy holds

Batch requires the exact resolved workspace path explicitly acknowledged by the user as trusted
because Claude --print skips its trust dialog. This is not a sandbox or native tool approval.
GLM awaits usable approved profile/use evidence. Grok's official native auth source allows API-key
fallback in some cached-session cases, so included subscription entitlement by itself does not release
this gate. Google third-party-tool terms require applicable clarification before agy launch.

## Publication and installation

Exact content review, public repository readback and Desktop installation are pending. The bundled
marketplace contains five packages, but a generated catalog entry does not prove runtime or UI readiness.

Next: final content review/publication, supported local installation/backend discovery, and unresolved
native acceptance/profile/policy/containment/UI gates. Preserve the full original objective.
