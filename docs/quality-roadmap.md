# Evidence-based quality priorities

Observed 2026-10-01. “Best in the world” is the requested quality ambition, not a proven rank.
All original [completion gates](requirements.md) remain applicable, including policy, native acceptance,
Desktop UX, default preservation and containment. Popularity is not reliability or official endorsement.

A bounded primary-source comparison read PAL clink at
[7afc7c1](https://github.com/BeehiveInnovations/pal-mcp-server/tree/7afc7c1cc96e23992c8f105f960132c657883bb1)
and Codex ACP Gateway at
[81db00d](https://github.com/mmonad/codex-acp-gateway/tree/81db00d32207c3333cd05ab6463099ae21fc0d46).
GitHub's public API reported 11,761 stars/1,043 forks for PAL and 5 stars/1 fork for Gateway at
06:54 UTC. These are repository attention counters; neither candidate was installed or runtime-tested.

| Candidate | Useful design | Constraint against the requested stack |
| --- | --- | --- |
| PAL clink | File references, role/context preparation and compact final responses | Its shipped presets relax child permissions; configure explicitly before use. Final-result orchestration does not establish native Codex progress/approval parity |
| ACP Gateway | Protocol events and permission requests mapped to a client | Replacement backend with partial handlers, not automatic preservation of the parent Codex's capabilities |
| Harness Connect | Additional parent-owned MCP workflow, durable jobs/cursors, explicit native IDs and policy holds | Development alpha; native approvals/teams, full UI/Cloud and macOS containment gates remain open |

The [PAL documentation](https://github.com/BeehiveInnovations/pal-mcp-server/blob/7afc7c1cc96e23992c8f105f960132c657883bb1/docs/tools/clink.md)
warns about its default permission flags and permits tightening them. This does not make all PAL usage
incompatible. Its [runner](https://github.com/BeehiveInnovations/pal-mcp-server/blob/7afc7c1cc96e23992c8f105f960132c657883bb1/clink/agents/base.py)
awaits a final process response; current-host streaming UX was not tested here.
Gateway's [handlers](https://github.com/mmonad/codex-acp-gateway/blob/81db00d32207c3333cd05ab6463099ae21fc0d46/src/lib.rs)
include incomplete feature implementations and hardcoded host-policy responses. Its disconnect loop
and [agent spawn](https://github.com/mmonad/codex-acp-gateway/blob/81db00d32207c3333cd05ab6463099ae21fc0d46/src/acp/spawn.rs)
do not establish full process-tree cleanup. These are bounded source findings, not measured leaks or
proof that the projects cannot be improved. OpenAI protocol support does not endorse either adapter.

## Next implementation and acceptance

1. Cursor-based waiting with compact change metadata, implemented in alpha.4: wait for 1–8 existing jobs, wake on events,
   terminal/lost state or retention gaps, and keep acknowledged cursors until the parent drains events.
   No raw transcript repetition, inference, auto-retry or child cancellation on wait cancellation.
   Two installed independent stdio clients, reconnect, output/Unicode bounds, idle timeout and measured
   tool-call/byte counts were checked on a harmless quiet-child scenario. See [status](status.md);
   native host streaming UX and comparative runtime tests remain separate evidence.
2. Typed progress/questions/approvals: preserve native request IDs and exact once/always choice scope.
   Reject stale/replayed IDs and require explicit user answers. Unknown terminal text remains unverified.
   Validate real deny/approve behavior and supported Desktop rendering on permitted provider routes.
   The [native interaction contract](native-interaction-contract.md) defines the supported route and
   remaining wire/UI evidence; it is not an enabled approval bridge.
3. Truthful ownership/cleanup: distinguish native turn completion, leader exit, observed-tree cleanup
   and full OS containment. Re-run the exact escaped-daemon acceptance plus worker loss/PID reuse and
   an unrelated sentinel. A successful cancel acknowledgement is not proof of full cleanup.

Comparative runtime superiority, p95 latency and all original production gates remain unproven.
Implementations must not trade security or vendor permission for a more native-looking interface.

## Alpha.5 reliability step

[Storage boundaries](storage.md) add finite transactional admission with permanent recovery receipts,
byte-aware payload retention, durable native outcome snapshots and compact history pagination.
Installed synthetic MCP checks and independent review verify their stated scope. Full physical disk
bounds, mixed-version worker parity, native UI/teams, escaped-daemon containment and vendor holds
remain open; this step does not close the original production gates.
