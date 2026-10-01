# Validation status

Observed 2026-10-01, Europe/Amsterdam. Development alpha; the full completion gates in
[requirements.md](requirements.md) are not achieved. This status distinguishes actual tests from source
claims and generated artifacts.

| Layer | Actual evidence | Limit |
| --- | --- | --- |
| Main regression suite | 400 tests and 74 subtests passed on macOS/Python 3.14.7; 94 affected interaction/generation/revalidation tests passed; Ruff passed | Synthetic processes/protocol fixtures; separate native acceptance gates remain |
| Installed runtime | Noneditable alpha.6 wheel: all 17 module hashes match source; five catalogs and four form-protocol cases passed. Alpha.5 storage/recovery checks remain recorded below | One local platform, synthetic answering client; no additional vendor inference |
| Claude native roundtrip | Claude Code 2.1.286: two exact replies, same-ID resume, then original reply recalled after MCP reconnect; empty workspace stayed empty | Three no-tool prompts; no approval/teams/file-edit/UI claim |
| Claude status parser | Updated parser replayed all three recorded native stdout streams with verified identity/success, zero denials and parent-verification requirement | No new inference; actual native denial/rate-limit cases remain untested |
| Lifecycle faults | Worker loss, cancellation, SQLite contention, bounded retention, request id recovery and profile isolation tested | Only kernel-observed processes |
| Full containment | Explicit macOS setsid/reparenting acceptance gate failed; exact captured test processes were cleaned | Production blocker; not hidden by xfail or counted as passing regression |
| Grok | Official docs/source, installed 1.0.44 alpha help/inspect; prepared JSON contract | Native effective auth/model route and absence of paid fallback unproven; no inference |
| GLM | Official supported-tool docs and subscription terms read; profile isolation design | Existing usable profile and this orchestration's use classification unverified; no inference |
| agy/Hermes | Current Google docs/terms, installed1.2.14 help, pinned Hermes source | Applicable permission unresolved; no inference |
| Local plugin installation | All five alpha.6 packages updated via installed CLI; 20 cache files match generated packages; fresh stdio catalogs expose 16 router/15 scoped tools. Current Desktop loaded all five interaction tool definitions, invoked one check and fresh revalidation | The form call returned cancel with no choice; actual rendering and native consent acceptance remain separate. UI automation denied access to Codex |
| Hosted CI | [Alpha.4 runtime revision](https://github.com/trukhinyuri/codex-harness-connect/actions/runs/36830383639) passed all four macOS/Linux and Python 3.11/3.14 jobs. Check the exact current revision in the [CI runs](https://github.com/trukhinyuri/codex-harness-connect/actions/workflows/ci.yml) | Synthetic CI is not native vendor or Desktop UI qualification |

Local account observations, absolute home paths, conversations and raw CLI readbacks are private and
not published. The earlier alpha.2 installation readback preserved all ten configuration groups outside plugins/marketplaces.
During alpha.3, nine remained identical; one global reasoning setting differed from the baseline.
The cause is not established and no automatic restoration was performed. Do not claim full default
preservation for this interval. Connector code performs no auth/payment/security/model-default writes;
installation uses the native CLI. Private configuration observations remain private.
For alpha.4, immediate before/after snapshots around each of five native installation calls preserved
all ten configuration groups outside plugins/marketplaces. This preserves that interval's starting
settings; it does not restore the earlier default or explain alpha.3's unrelated observation.
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

Current configured labels are `connect_harness_cli`, `with_claude_cli`, `with_claude_cli_glm`, `with_grok_cli` and
`with_agy_cli`. The installed alpha.6 manifests/skills match the generator and current host tool metadata uses these labels; the host controls any namespace prefix in its UI.

Next: unresolved native acceptance/profile/policy/containment/UI gates.
Preserve the full original objective. See [SQLite lifecycle evidence](sqlite-lifecycle.md).

## Alpha.6 form and consent qualification

`check_interaction` qualifies the connected client's advertised standard-form route without launching a
CLI/model or granting permission. Required enum answers have no default; empty, malformed and expired
acceptance cannot pass. Decline/cancel/timeout remain distinct; caller cancellation propagates. The
connector stores no answer, and the host may retain the exchange. Accepted content does not attest to a
human. See the [interaction contract](native-interaction-contract.md).

Independent tests found and fixed integer protocol metadata handling, null unknown capabilities and
late acceptance during timeout cleanup. Real stdio tests also found and fixed MCP 1.30's rejection of
Literal annotations. Installed wheel tests verify the required enum wire and all five scopes; no AI
requests were used. Independent review found no remaining actionable defect in this diagnostic.

The current Desktop client advertises form support and identifies as `codex-mcp-client` 0.159.2. One
actual call returned `cancelled` without a choice in 0.002 seconds of server time. This records the
protocol result; it does not establish that a person saw or closed a form. Render acceptance requires
an observed usable form and answer. Fresh revalidation detected changed source/package/API/target
evidence and kept qualification incomplete. The observed Claude version remains 2.1.286.

All five installation intervals preserved the ten configuration groups outside plugins/marketplaces.
This preserves each interval's starting settings, rather than explaining or restoring the earlier
reasoning-setting drift. The prior marketplace and wheels remain available for rollback.

Current [Claude source findings](claude-consent.md) identify the official SDK callback candidate and
the MCP permission-host limitation. Public-plugin SDK subscription classification and native
deny/approve/question/cancel tests remain enablement dependencies. No SDK or provider route was enabled.
The full original production, teams, Cloud and containment gates remain open.

## Alpha.3 compatibility maintenance

Repeated skill invocations now require fresh host/native/runtime observations, current source/terms review,
affected fixes and all original acceptance gates. The observation itself keeps qualification incomplete.
Tests cover executable replacement/symlink retargeting during probes, repeat missing/unknown evidence,
private atomic state, output bounds, full-help drift and independent probe concurrency. Launch rejects
missing mandatory stream/resume flags. See [maintenance procedure](revalidation.md).

On the local macOS/Python 3.14 host, two installed stdio MCP observations took 0.511s and 0.403s with
about 25 KiB responses; a current Desktop chat tool call completed in 5.191s. These are small observed
samples, not throughput/p95 guarantees. CLI and current-host contexts can produce different help text
and fingerprints. No new model inference was used in these checks. PATH and bundled Codex report
0.159.2; installed Desktop metadata is 26.928.21956/build12404. The native updater reported an available
26.928.31416/build12553, which was not installed or qualified. Loaded source/API, UI and newest-release
compatibility must not be inferred from disk hashes or version metadata.

## Alpha.4 cursor waiting

`wait_sessions` observes 1–8 existing jobs with compact bounded responses and retained reader cursors.
Independent review reproduced and caught an owner-lookup deadline gap and exception/error-text leakage;
both were fixed and separately rechecked. Synthetic tests now use synchronization for blocked readers
and bounded event draining rather than assuming stdout is the first event after input.

On the installed wheel, the same quiet stdin-gated synthetic child was observed in sequential windows:
12 transcript polls at 0.1-second intervals returned 15,028 bytes over 1.266s; one 1.2-second wait returned
997 bytes over 1.203s. These are single-scenario measurements, not p95, CPU, throughput or vendor/model
speed guarantees. No AI requests were made. A current Desktop chat's unavailable-ID wait took 0.028s;
its fresh revalidation took 5.589s and correctly invalidated alpha.3 runtime evidence. A valid synthetic
job was checked through separately installed stdio MCP; it was not launched in the native Desktop chat.
After host catalog refresh, all five current-chat wait tools returned the expected scoped unavailable
result in 0.039–0.064s. This tests new API loading and error handling, not a native provider task or UI card.
Native approval rendering, teams, Cloud, policy holds and full macOS containment remain open.
See [wait semantics](waiting.md) and [comparative source evidence](quality-roadmap.md).
The [next native interaction contract](native-interaction-contract.md) identifies documented form input,
provider consent boundaries and required acceptance. No native elicitation/approval broker is enabled
in alpha.4; documented interfaces are not a successful live UI test.

## Alpha.5 storage boundaries

Permanent admission capacity is checked transactionally after request replay lookup and before Popen.
Byte-aware event retention keeps exact counters and per-job gap watermarks; final native metadata
survives event eviction. History reads are compact pages with explicit scoped cursors. Independent
review found an interrupted-migration counter bug and old-worker INSERT accounting incompatibility;
both were corrected and specifically rechecked. Public source/package privacy review passed.

The clean installed wheel verified two synthetic jobs, full-capacity replay without a new launch,
complete two-job pagination, explicit cancellation, empty-workspace preservation, reconnect recovery
and native outcome after complete event eviction. All five fresh stdio catalogs expose storage_status.
No vendor inference or existing-history cleanup was used. Each of five immediate installation
intervals preserved all ten configuration groups outside plugins/marketplaces; earlier reasoning
drift remains unexplained and was not automatically restored.

Existing stores migrate without deleting history. Already-running old workers retain their old
count-only limits; oversized legacy history is counted and suppressed on read, with explicit
over-budget reporting. No unlimited admission, physical disk envelope or full upgrade parity is
promised. See [storage and recovery](storage.md). Actual local source/runtime SQLite reports 3.53.4;
the [upstream WAL-reset fix](https://sqlite.org/wal.html) applies since 3.51.3 or documented
backports. This local observation does not qualify every CI/user Python build. Native approvals/teams,
provider policy/profile routes, full native Desktop UI, Cloud and full macOS containment remain
open. The strongest-in-the-world ambition is not a proven comparative ranking.

After the initial old-schema readback, the current Desktop chat's catalog refreshed. All five
storage_status calls returned the new alpha.5 schema in 0.934–0.938s; router history returned explicit
paging metadata. Fresh router revalidation took 7.192s, observed the new runtime/API fingerprint and
kept qualification incomplete. These calls prove new API loading and read behavior in this chat, not
native provider tasks, progress/approval rendering or UI parity. The alpha.5 runtime commit's
[CI run](https://github.com/trukhinyuri/codex-harness-connect/actions/runs/36836820502) passed all four
macOS/Linux and Python 3.11/3.14 jobs; later documentation revisions have their own exact-revision CI.
