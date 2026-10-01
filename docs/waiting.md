# Observing jobs without repeating transcripts

Alpha.4 adds the read-only MCP tool `wait_sessions`. It accepts 1–8 existing job IDs, each with its
own acknowledged event cursor, and a finite timeout from 0 to 45 seconds. IDs must be 32 lowercase
hexadecimal characters; cursors are integers from 0 through 2^63−1. It does not start, resume or stop jobs.

```json
{"targets":[{"session_id":"0123456789abcdef0123456789abcdef","after":27}],"timeout_seconds":30}
```

The response gives compact state and the first pending cursor. `next_cursor` stays at the supplied
acknowledged cursor: waiting never consumes events. When `changes_available` is true, read
`session_events` from that cursor and retain the returned cursor only after processing that page.
Independent readers can observe the same unread page, including after an MCP reconnect.

`reason` distinguishes `changes`, `terminal`, `retention_gap`, `unknown_status`, `error`, `timeout` and
an immediate `snapshot`. A terminal native process does not prove task acceptance. A retention gap
means some earlier events have been pruned; the parent must report that loss instead of fabricating
history. Lifecycle, semantic result and parent acceptance remain separate.

The JSON response is capped at 64 KiB. Event payloads, stderr, process-member lists, final text and
worker error text are excluded. Error presence is reported; diagnostic details require an explicit
transcript read. Scoped plugins cannot observe another adapter's jobs. Timeouts and cancellation stop
only this observation; use `cancel_session` and verify authoritative state to stop a job.

Read-only ownership and state lookups run off the event loop within the observation deadline. Cancelling
an observer cannot forcibly stop a synchronous filesystem reader thread already executing. The normal
SQLite busy timeout is bounded, but this is not a guarantee against a hung filesystem. A deadline can
return a read error; callers must not interpret it as a stopped child. Poll intervals back off from
0.2 to 0.5 seconds, so this is bounded observation rather than a push notification or guaranteed UI stream.

Acceptance includes strict-input rejection, 8-job Unicode/output bounds, retained cursors, terminal/lost
state, retention gaps, slow-reader deadlines, event-loop cancellation, scoped denial and two real stdio
MCP readers with reconnect and explicit transcript drain. Installed-wheel and current-host invocation
need their own evidence. Native Desktop approval cards, teams and Cloud deployment are separate gates.
