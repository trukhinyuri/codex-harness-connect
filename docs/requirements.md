# Original objective and completion gates

The user requested a universal `codex-harness-connect` project at `~/Personal/Sources/codex-harness-connect`,
research of official agy/Hermes orchestration, implementation, tests, public publication, installation in
the current Codex Desktop, and creation/verification of Claude, Claude+GLM/zcode, Grok Build and agy
plugins. The requested end state includes complete capability preservation and production readiness.
This objective is not replaced by an alpha scaffold or synthetic-only testing.

| Gate | Evidence required | State |
| --- | --- | --- |
| R1 agy/Hermes research | Current Google docs/terms, pinned Hermes source, installed CLI probes | Docs/probes obtained |
| R2 Universal discovery | Installed binary identity, recursive command/feature map, official docs dossier and contradictions | Top-level inventory only |
| R3 Adapter authoring | Research-driven packages, repo destination handling, repeatable validation | Five packages generated with guarded, transactional authoring; incomplete recursive dossiers/code generation |
| R4 Claude | Native login, stream parsing, PTY approvals, resume, cancellation, teams, skills/plugins/MCP | Native reply/resume/history proved on 2.1.286; approvals/teams/file changes pending |
| R5 Claude+GLM | Existing approved profile, provider/model evidence, auth isolation, same lifecycle gates | Pending configuration/legal evidence |
| R6 Grok Build | Native auth entitlement, ACP capabilities/approvals, streams, resume, cancellation/subagents | Pending |
| R7 agy | Applicable Google permission plus NDJSON/PTY/teams/session lifecycle acceptance | Legal hold, live tests pending |
| R8 Codex feature continuity | AGENTS.md, skills, explicit memory context, plugins/MCP, worktrees, permissions, review | Design boundaries documented; live checks pending |
| R9 Native Desktop experience | Progress, questions, approvals, stop, continuation, changes and native-team integration | No UI parity established |
| R10 Reliability | Durable live state, timeout, reconnect, cancellation descendants, bounded storage, startup/auth/limit/drift handling | 186 tests and 74 subtests passed; full macOS daemon containment failed |
| R11 Publication | Secret review, independent code review, passing CI, public GitHub authoritative readback | Public alpha/review/readback and four-job CI passed at f203b8a; synchronized fault fixture awaits CI |
| R12 Install | Supported marketplace install, current Desktop readback, fresh-session tool/skill use | All five installed; native backend skills/tools discovered; Desktop chat/UI pending |
| R13 Production readiness | All requested gates proven, limitations resolved or explicitly incompatible requirements addressed by user | Not achieved |
| R14 Preserve defaults/budget | Native quota reads; no auth/payment/security/model/speed changes; 20pp reserve | Preserved so far |

## Boundaries that cannot be declared solved by passing tests

No documented MCP mechanism automatically imports Codex local memory or ChatGPT memory into an external
harness, turns its tools into native Codex subagent events, or transfers Codex permission enforcement.
External native CLI teams and Codex's own agent team are distinct. Hosted Cloud does not obtain a local
CLI simply because its plugin appears in a catalog. Full 100% parity is unproven and cannot be promised.

Google terms §6 versus native headless automation is a material legal ambiguity. A test cannot create
vendor permission. Existing account access must be established without inspecting credential files,
changing login/billing, adding subscriptions/credits or bypassing restrictions.

## Acceptance procedure

For each permitted profile, use a disposable trusted git workspace. Inspect native auth through documented
status commands, then run a bounded no-write prompt. Parse final native result and session id, continue
with a second prompt, verify real denial/approval, cancel a deliberately long harmless task and confirm
native/local termination, reconnect the MCP client, and run parallel isolated workspaces. Test native
teams only where documented and enabled by existing policy. Inspect resulting changes in Desktop.
Do not infer production readiness from process exit, a manifest, a passing fake CLI or source claims.
