# Durable storage and recovery

Observed 2026-10-01. This is a logical retention contract for alpha.5, not a disk-space,
unlimited-availability or full process-containment guarantee. Vendor/UI acceptance remains separate.

Each harness store admits at most 4,096 permanent session receipts by default. The effective capacity
is persisted when migrating the store. Admission checks an existing request ID and launch fingerprint
first, inside the same write transaction as the new receipt. Identical replay still returns its original
job at capacity; a conflicting launch is rejected. New IDs fail before worker/native process creation
when the store is full. Failed starts, lost jobs and jobs without request IDs occupy slots too.

Receipts are never expired, deleted or automatically rotated. Exact indefinite request recovery, finite
storage and accepting infinitely many new distinct IDs cannot all be promised. Capacity exhaustion
requires an explicitly reviewed storage migration; creating a new empty store loses the old store's
deduplication scope. Do not retry an uncertain old request against another store.

| Retained data | Limit per harness store |
| --- | --- |
| Session receipts | 4,096; existing over-cap stores remain readable, new admission closes |
| One new event payload | 64 KiB of UTF-8 JSON; oversized payload replaced by explicit omission metadata |
| One job's events | 1,024 rows and 4 MiB of encoded payload |
| All retained events | 10,000 rows and 64 MiB of encoded payload |
| Durable native outcome | 32 KiB, versioned metadata; bounded error/rate/deferred summaries and truncation flags |
| Event page | 1–1,000 items, further limited by a 256 KiB event-page text budget |
| History page | 1–50 compact summaries, default 20; complete returned text content at most 64 KiB |

The budgets concern encoded content. SQLite pages, indexes, permanent metadata, DB high water and
WAL/SHM files add overhead. MCP may serialize both text and structured content, so the complete
JSON-RPC transport envelope can exceed the content budget. Launch paths and arguments have independent
byte limits; environments/launch arguments are not persisted. Error diagnostics have a bounded preview.
Recorded process identities remain available for cleanup; list pages omit this evidence and private
paths/error text. Fetch one job explicitly when detailed lifecycle evidence is needed.

New workers keep draining output when retention evicts old events. Eviction updates durable per-job
watermarks in the same transaction as payload deletion and exact byte counters. An oversized event
exposes `payload_omitted`; a page exposes `payloads_omitted`. `truncated` means the requested cursor
crosses a known retention gap. When all of a job's events are gone, `next_cursor` advances to that job's
watermark, so reconnect does not loop forever. A native success still requires parent verification.

New protocol workers persist `native_outcome` before final event retention. It preserves verified
native identity, semantic outcome, denials, deferred tool metadata and bounded errors/rate metadata.
It contains no final answer transcript or approval response. Older jobs/workers may have no durable
snapshot; absent metadata is unknown and must not be invented from process exit.

Migration is transactional, initializes counters from actual UTF-8 payload lengths and deletes no
existing history. Already-running older workers can continue writing. Their old INSERT shape is
counted correctly, but they still enforce their original count-only retention policy and cannot write
the new outcome snapshot. Legacy/mixed-version history can therefore exceed new byte budgets until
a new worker write applies retention. Oversized legacy payloads are suppressed on read; `storage_status`
reports over-budget state. This is a compatibility boundary, not full live-upgrade qualification.

`list_sessions` returns `next_cursor`, `has_more` and an explicit order: adapter ascending, then newest
`(created_at, session_id)` within that adapter. Use its cursor unchanged; optionally select one adapter.
Equal timestamps do not duplicate or skip existing jobs. Pages are not a frozen snapshot of concurrent
new launches; begin a new scan to see newly inserted earlier rows. Cursors remain scoped to their
original harness; they are not native conversation IDs or event cursors.

`storage_status(adapter)` reads admission capacity, exact retained event payload counts/bytes,
legacy over-budget state and measured DB/WAL/SHM sizes. It performs no cleanup, explicit checkpoint, cancellation
or retry. SQLite still manages its automatic checkpoints, including connection-close behavior. File-size measurements can change immediately during active writes. SQLite's
[WAL documentation](https://sqlite.org/wal.html) explains why long readers can delay checkpoint progress.
A hard database-size limit alone can deny the final writes needed for recovery; this release does not
claim a verified physical disk envelope or protect against an actually full filesystem.

Validation uses disposable stores and synthetic children: concurrent admission/replay, failed-start
receipts, interrupted migration rollback, old-worker insert compatibility, exact byte accounting and
transaction rollback, Unicode/output limits, global eviction, durable outcomes, empty-history cursors,
stable pagination and measurements with a pinned reader. Existing user history is not deleted by the
validation. Full original acceptance, native UI/teams and escaped-daemon containment remain open.
