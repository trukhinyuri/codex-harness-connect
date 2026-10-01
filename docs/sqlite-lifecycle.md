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
passed 39 tests locally. A new hosted run is still required before claiming the CI symptom is resolved.
This correction does not solve the separately documented macOS daemon-containment limitation.
