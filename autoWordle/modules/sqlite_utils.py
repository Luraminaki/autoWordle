#!/usr/bin/env python3
"""Shared SQLite connection/query helpers for the small, per-purpose stores in this package.

`session_store.SessionStore`, `precompute_store.PrecomputeJobStore`, and
`modules.compendium_cache.CacheDB` each open their own long-lived,
`check_same_thread=False` connection guarded by a `threading.Lock` - this
module holds the two pieces of that pattern that were duplicated (and, for
pragma order, had drifted) across them.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import sqlite3


def open_connection(db_path: str, *, wal: bool = True) -> sqlite3.Connection:
    """Open a `check_same_thread=False` connection with this project's standard pragmas.

    `busy_timeout` is set *before* `journal_mode`/`synchronous` deliberately:
    those can themselves hit "database is locked" if another connection to
    the same file is momentarily busy (e.g. a second process opening the
    same store around the same time), and without `busy_timeout` set yet,
    that first contended call fails immediately instead of retrying.
    `modules.compendium_cache.CacheDB` originally hit and fixed exactly this;
    `session_store`/`precompute_store` had drifted out of sync with that fix
    (setting `busy_timeout` last instead of first) until this was factored
    out into one place both can't drift from again.

    Args:
        db_path (str): Path to the SQLite file.
        wal (bool): Whether to enable WAL mode + `synchronous=NORMAL` (the
            default, appropriate for a long-lived read/write connection).
            Pass `False` to skip both and set up durability/speed pragmas
            for a different use case instead (e.g. a one-time bulk-build
            connection).

    Returns:
        sqlite3.Connection: The opened connection with these pragmas applied
        - callers still create their own tables/further pragmas.
    """
    db = sqlite3.connect(db_path, timeout=5.0, isolation_level=None, check_same_thread=False)
    _ = db.execute('PRAGMA busy_timeout=5000')

    if wal:
        _ = db.execute('PRAGMA journal_mode=WAL')
        _ = db.execute('PRAGMA synchronous=NORMAL')

    return db


def delete_older_than(db: sqlite3.Connection, table: str, timestamp_column: str,
                      threshold_seconds: float, now: float,
                      extra_where: str = '', extra_params: tuple = ()) -> int:
    """Delete every row of `table` whose `timestamp_column` is at least `threshold_seconds` old.

    Shared by `session_store.SessionStore.delete_expired` and
    `precompute_store.PrecomputeJobStore.prune_finished` - both were the same
    "DELETE ... WHERE (now - timestamp) >= threshold" shape, previously
    duplicated rather than factored out. Caller must already hold that
    store's own lock/transaction (`with self.lock, self.db:`), same as every
    other query in those classes.

    Args:
        db (sqlite3.Connection): Connection to run the DELETE against.
        table (str): Table name - not user input, always a fixed constant at each call site.
        timestamp_column (str): Column holding the timestamp to compare - same constraint as `table`.
        threshold_seconds (float): Age threshold, in seconds.
        now (float): Current time, so callers that need it consistent with
            something else they're doing can share a single `time.time()` read.
        extra_where (str): Additional ` AND ...`-style SQL condition, if any
            (e.g. `precompute_store`'s status filter) - not user input, always
            a fixed constant at each call site.
        extra_params (tuple): Parameters for `extra_where`'s placeholders, if any.

    Returns:
        int: Number of rows deleted.
    """
    cursor = db.execute(
        f'DELETE FROM {table} WHERE (? - {timestamp_column}) >= ?{extra_where}',
        (now, threshold_seconds, *extra_params))
    return cursor.rowcount
