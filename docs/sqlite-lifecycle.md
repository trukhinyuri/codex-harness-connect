# SQLite connection and lock evidence

The first hosted run failed on two session tests on all four macOS/Linux and Python 3.11/3.14 jobs.
The logs report disk I/O errors but omit the extended SQLite code/library version. The exact error
was not reproduced locally; the two original tests also passed locally before the correction.

A separate cross-process regression proved that independently opening and closing an existing database
file dropped the process's SQLite locks. This allowed another writer into an active transaction.
The mechanism is documented by [SQLite](https://sqlite.org/howtocorrupt.html#posix_advisory_locks_canceled_by_a_separate_thread_doing_close).
A second defect left short service connections open: Python's connection context commits or rolls back
but does not close. [Python documentation](https://docs.python.org/3.14/library/sqlite3.html#how-to-use-the-connection-context-manager).

The correction creates a missing file exclusively with private permissions, serializes first creation
until its raw descriptor closes, and performs existing-file checks without reopening the inode.
SQLite opens the existing file with `mode=rw`. Service operations commit/roll back and close in `finally`;
the worker keeps its separately owned long-lived connection and explicit cleanup. Errors are not hidden
or retried, and no SQLite safety setting is disabled.

Four discriminating tests failed against the original code; the corrected runtime/fault/connection suite
passed 39 tests locally. The next hosted run passed both original failing tests on all four platforms.
Three complete jobs passed; macOS/Python 3.14 stopped in a different fault test before acquiring its
injected writer lock, reporting `database is locked` rather than the original disk I/O error.

The fixture only waited for retention to begin, allowing its lock attempt to overlap the output burst. It now
waits for the persisted tail marker, confirms the live native process identities, makes one bounded
lock attempt, and asserts an active transaction before checking shutdown. Only the injector's wait
increases to one second; the production worker's 100ms busy timeout is unchanged. Failure remains fatal
and reports the SQLite version and extended code.
The naming revision's subsequent run passed all four jobs before this synchronization change;
the setup failure is intermittent, so that pass does not replace qualification of the corrected fixture.
The [corrected fixture revision](https://github.com/trukhinyuri/codex-harness-connect/actions/runs/36822472887)
then passed all four macOS/Linux and Python 3.11/3.14 jobs. This is hosted regression evidence for the
corrected code and test setup, not proof of the exact original failure's cause or native vendor readiness.
This correction does not solve the separately documented macOS daemon-containment limitation.
