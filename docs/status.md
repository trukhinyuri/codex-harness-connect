# Validation status

Observed 2026-10-01, Europe/Amsterdam. Development alpha; the full completion gates in
[requirements.md](requirements.md) are not achieved. This status distinguishes actual tests from source
claims and generated artifacts.

| Layer | Actual evidence | Limit |
| --- | --- | --- |
| Main regression suite | 186 tests and 74 subtests passed after the SQLite lifecycle correction on macOS/Python 3.14.7; Ruff passed | Synthetic processes/protocol fixtures; updated hosted CI pending |
| Claude installed package | Built wheel installed into a clean venv with its own dependencies; console/MCP handshake succeeded | One local platform |
| Claude native roundtrip | Claude Code 2.1.286: two exact replies, same-ID resume, then original reply recalled after MCP reconnect; empty workspace stayed empty | Three no-tool prompts; no approval/teams/file-edit/UI claim |
| Claude status parser | Updated parser replayed all three recorded native stdout streams with verified identity/success, zero denials and parent-verification requirement | No new inference; actual native denial/rate-limit cases remain untested |
| Lifecycle faults | Worker loss, cancellation, SQLite contention, bounded retention, request id recovery and profile isolation tested | Only kernel-observed processes |
| Full containment | Explicit macOS setsid/reparenting acceptance gate failed; exact captured test processes were cleaned | Production blocker; not hidden by xfail or counted as passing regression |
| Grok | Official docs/source, installed 1.0.44 alpha help/inspect; prepared JSON contract | Native effective auth/model route and absence of paid fallback unproven; no inference |
| GLM | Official supported-tool docs and subscription terms read; profile isolation design | Existing usable profile and this orchestration's use classification unverified; no inference |
| agy/Hermes | Current Google docs/terms, installed1.2.14 help, pinned Hermes source | Applicable permission unresolved; no inference |
| Local plugin installation | All five packages installed via supported CLI; app-server verified installed/enabled state, skills and 12/11 MCP tools | Fresh Desktop chat/UI acceptance remains unverified; UI automation denied access to Codex |
| Hosted CI | First four macOS/Linux and Python 3.11/3.14 jobs failed on two session tests with SQLite disk I/O errors | A separately reproduced lock/lifetime defect has a candidate fix; new hosted result required |

Local account observations, absolute home paths, conversations and raw CLI readbacks are private and
not published. Installation readback preserved all ten configuration groups outside plugins/marketplaces.
The connector did not change auth, payment, permission, security or model defaults.
CLI auto-update changed the observed Claude version from 2.1.284 to 2.1.286; live evidence applies to
2.1.286. Future versions require a new inventory and acceptance review.

## Policy holds

Batch requires the exact resolved workspace path explicitly acknowledged by the user as trusted
because Claude --print skips its trust dialog. This is not a sandbox or native tool approval.
GLM awaits usable approved profile/use evidence. Grok's official native auth source allows API-key
fallback in some cached-session cases, so included subscription entitlement by itself does not release
this gate. Google third-party-tool terms require applicable clarification before agy launch.

## Publication and installation

Exact content review passed for the initial 53-file source alpha. The public
[repository](https://github.com/trukhinyuri/codex-harness-connect) and its reviewed commit/tree were verified
through GitHub. All five local packages and their MCP servers were discovered by the native backend.
This proves installation/backend discovery; full runtime and Desktop UI acceptance remain separate gates.

Next: SQLite fix verification/CI, then unresolved native acceptance/profile/policy/containment/UI gates.
Preserve the full original objective. See [SQLite lifecycle evidence](sqlite-lifecycle.md).
