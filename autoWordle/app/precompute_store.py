#!/usr/bin/env python3
"""SQLite-backed store of precompute job state: progress, ETA, and a queue.

Mirrors `session_store.py`'s exact pattern (WAL mode, a shared
`check_same_thread=False` connection guarded by a `threading.Lock`, a
read-through/write-through table, no in-memory caching layer) for the same
reason: this app can run multiple `uvicorn` workers, so an in-memory dict
wouldn't be visible across them.

The table does triple duty:
- **Progress/ETA storage**, updated periodically from
  `vectorized_compendium.stream_pattern_compendium_to_cache`'s
  `progress_callback` - what the SSE endpoint reads from.
- **Mutual exclusion**, via the `PRIMARY KEY (lang, word_length)` plus the
  "is anything else already running" check in `request()` - never build the
  same `(lang, word_length)` twice, and cap global concurrency at 1 (two
  heavy numpy builds would just fight over the same cores).
- **A queue**, via `status='queued'` rows ordered by `created_timestamp` -
  `mark_done`/`mark_failed` atomically claim the next one, so there is no
  separate dispatcher thread/process: whichever job finishes hands off to
  the next.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import _thread
import dataclasses
import logging
import pathlib
import sqlite3
import time
from threading import Lock

from autoWordle.modules import statics

logger = logging.getLogger(__name__)

# A 'running' row untouched for longer than this is assumed abandoned (the
# worker that owned it crashed/restarted) and can be reclaimed by a fresh
# request - roughly 2x the compute loop's own progress-heartbeat interval
# (`vectorized_compendium._PROGRESS_LOG_INTERVAL_SECONDS`, 5s), with margin.
_STALE_TIMEOUT_SECONDS = 30.0

# A DONE/FAILED row untouched for longer than this is prunable - generous
# margin over any realistic SSE-client polling delay, so no client can lose
# its terminal status update, while still keeping precompute_jobs.sqlite from
# accumulating rows forever across an app's lifetime. Public: api_views.py's
# `/precompute` route calls prune_finished with this value, mirroring how
# create_game_session calls SESSION_STORE.delete_expired.
FINISHED_RETENTION_SECONDS = 3600.0


@dataclasses.dataclass
class PrecomputeJobStatus:
    """A single `(lang, word_length)` job's current state."""

    lang: str
    word_length: int
    status: statics.PrecomputeStatus
    fraction_done: float
    eta_seconds: float
    error: str
    position: int | None  # 1-indexed queue position if status is QUEUED, else None


@dataclasses.dataclass
class PrecomputeRequestResult:
    """Result of requesting a job: what the caller should do next."""

    status: statics.PrecomputeStatus
    position: int | None
    should_start: bool  # True only for the caller that should run the build itself


class PrecomputeJobStore:
    """A SQLite-backed store of precompute job state, keyed by `(lang, word_length)`."""

    def __init__(self, db_path: str | pathlib.Path) -> None:
        """Open (creating if needed) the job database.

        Args:
            db_path (str | pathlib.Path): Path to the SQLite file.
        """
        self.db_path: str = str(db_path)
        self.lock: _thread.LockType = Lock()
        self.db: sqlite3.Connection = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False)

        with self.lock:
            _ = self.db.execute('PRAGMA journal_mode=WAL')
            _ = self.db.execute('PRAGMA synchronous=NORMAL')
            _ = self.db.execute('PRAGMA busy_timeout=5000')

            with self.db:
                _ = self.db.execute('''
                    CREATE TABLE IF NOT EXISTS precompute_jobs (
                        lang TEXT NOT NULL,
                        word_length INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        fraction_done REAL NOT NULL DEFAULT 0.0,
                        eta_seconds REAL NOT NULL DEFAULT 0.0,
                        error TEXT NOT NULL DEFAULT '',
                        created_timestamp REAL NOT NULL,
                        updated_timestamp REAL NOT NULL,
                        PRIMARY KEY (lang, word_length)
                    )
                ''')

    # ---------------------------------------------------------------- internal helpers
    # None of these acquire `self.lock` themselves - every public method below
    # acquires it exactly once; `self.lock` is a plain (non-reentrant)
    # `threading.Lock`, so a helper acquiring it again from inside a public
    # method's own `with self.lock:` block would deadlock.

    def _is_stale(self, updated_timestamp: float, now: float) -> bool:
        return (now - updated_timestamp) > _STALE_TIMEOUT_SECONDS

    def _has_other_active_job(self, now: float, lang: str, word_length: int) -> bool:
        """True if some *other* `(lang, word_length)` is running and not stale."""
        rows = self.db.execute(
            'SELECT updated_timestamp FROM precompute_jobs WHERE status = ? AND NOT (lang = ? AND word_length = ?)',
            (statics.PrecomputeStatus.RUNNING.value, lang, word_length)).fetchall()
        return any(not self._is_stale(updated_timestamp, now) for (updated_timestamp,) in rows)

    def _queue_position(self, created_timestamp: float) -> int:
        """1-indexed position among queued jobs, ordered by `created_timestamp`."""
        count_ahead = self.db.execute(
            'SELECT COUNT(*) FROM precompute_jobs WHERE status = ? AND created_timestamp < ?',
            (statics.PrecomputeStatus.QUEUED.value, created_timestamp)).fetchone()[0]
        return count_ahead + 1

    def _claim_next_queued(self) -> tuple[str, int] | None:
        """Atomically claim the oldest queued job, if any, marking it running."""
        row = self.db.execute(
            'SELECT lang, word_length FROM precompute_jobs WHERE status = ? ORDER BY created_timestamp ASC LIMIT 1',
            (statics.PrecomputeStatus.QUEUED.value,)).fetchone()
        if row is None:
            return None

        lang, word_length = row
        cursor = self.db.execute(
            'UPDATE precompute_jobs SET status = ?, updated_timestamp = ? WHERE lang = ? AND word_length = ? AND status = ?',
            (statics.PrecomputeStatus.RUNNING.value, time.time(), lang, word_length, statics.PrecomputeStatus.QUEUED.value))
        if cursor.rowcount == 0:
            return None

        return lang, word_length

    # ---------------------------------------------------------------- public API

    def request(self, lang: str, word_length: int) -> PrecomputeRequestResult:
        """Request a build for `(lang, word_length)`, enqueuing or resuming as needed.

        Args:
            lang (str): Language stem.
            word_length (int): Word length.

        Returns:
            PrecomputeRequestResult: Current status/queue position, and
            whether this caller is the one that should actually run the
            build (`should_start`) - `False` means a build for this exact
            combination is already queued or running; the caller should
            subscribe to its progress instead of starting a duplicate.
        """
        now = time.time()

        with self.lock, self.db:
            row = self.db.execute(
                'SELECT status, created_timestamp, updated_timestamp FROM precompute_jobs WHERE lang = ? AND word_length = ?',
                (lang, word_length)).fetchone()

            if row is not None:
                status, created_timestamp, updated_timestamp = row
                is_reclaimable = status in (statics.PrecomputeStatus.DONE.value, statics.PrecomputeStatus.FAILED.value) or (
                    status == statics.PrecomputeStatus.RUNNING.value and self._is_stale(updated_timestamp, now))

                if not is_reclaimable:
                    position = self._queue_position(created_timestamp) if status == statics.PrecomputeStatus.QUEUED.value else None
                    return PrecomputeRequestResult(status=statics.PrecomputeStatus(status), position=position, should_start=False)

            can_run_now = not self._has_other_active_job(now, lang, word_length)
            new_status = statics.PrecomputeStatus.RUNNING if can_run_now else statics.PrecomputeStatus.QUEUED

            _ = self.db.execute('''
                INSERT INTO precompute_jobs (lang, word_length, status, fraction_done, eta_seconds, error, created_timestamp, updated_timestamp)
                VALUES (?, ?, ?, 0.0, 0.0, '', ?, ?)
                ON CONFLICT(lang, word_length) DO UPDATE SET
                    status = excluded.status, fraction_done = 0.0, eta_seconds = 0.0, error = '',
                    created_timestamp = excluded.created_timestamp, updated_timestamp = excluded.updated_timestamp
            ''', (lang, word_length, new_status.value, now, now))

            position = self._queue_position(now) if new_status == statics.PrecomputeStatus.QUEUED else None
            return PrecomputeRequestResult(status=new_status, position=position, should_start=can_run_now)


    def update_progress(self, lang: str, word_length: int, fraction_done: float, eta_seconds: float) -> None:
        """Update a running job's progress/ETA - also refreshes its staleness heartbeat.

        Args:
            lang (str): Language stem.
            word_length (int): Word length.
            fraction_done (float): Completion fraction, `0.0`-`1.0`.
            eta_seconds (float): Estimated seconds remaining.
        """
        with self.lock, self.db:
            _ = self.db.execute(
                'UPDATE precompute_jobs SET fraction_done = ?, eta_seconds = ?, updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                (fraction_done, eta_seconds, time.time(), lang, word_length))


    def mark_done(self, lang: str, word_length: int) -> tuple[str, int] | None:
        """Mark a job done, then claim the next queued job if any.

        Args:
            lang (str): Language stem.
            word_length (int): Word length.

        Returns:
            tuple[str, int] | None: The `(lang, word_length)` of the job the
            caller should run next, or `None` if the queue is empty.
        """
        with self.lock, self.db:
            _ = self.db.execute(
                'UPDATE precompute_jobs SET status = ?, fraction_done = 1.0, updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                (statics.PrecomputeStatus.DONE.value, time.time(), lang, word_length))
            return self._claim_next_queued()


    def mark_failed(self, lang: str, word_length: int, error: str) -> tuple[str, int] | None:
        """Mark a job failed, then claim the next queued job if any.

        Args:
            lang (str): Language stem.
            word_length (int): Word length.
            error (str): Error description.

        Returns:
            tuple[str, int] | None: The `(lang, word_length)` of the job the
            caller should run next, or `None` if the queue is empty.
        """
        with self.lock, self.db:
            _ = self.db.execute(
                'UPDATE precompute_jobs SET status = ?, error = ?, updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                (statics.PrecomputeStatus.FAILED.value, error, time.time(), lang, word_length))
            return self._claim_next_queued()


    def get_status(self, lang: str, word_length: int) -> PrecomputeJobStatus | None:
        """Look up a job's current status.

        Args:
            lang (str): Language stem.
            word_length (int): Word length.

        Returns:
            PrecomputeJobStatus | None: Current state, or `None` if no job
            has ever been requested for this combination.
        """
        with self.lock:
            row = self.db.execute(
                'SELECT status, fraction_done, eta_seconds, error, created_timestamp FROM precompute_jobs '
                + 'WHERE lang = ? AND word_length = ?', (lang, word_length)).fetchone()

            if row is None:
                return None

            status, fraction_done, eta_seconds, error, created_timestamp = row
            position = self._queue_position(created_timestamp) if status == statics.PrecomputeStatus.QUEUED.value else None

        return PrecomputeJobStatus(lang=lang, word_length=word_length, status=statics.PrecomputeStatus(status),
                                   fraction_done=fraction_done, eta_seconds=eta_seconds, error=error, position=position)


    def get_running_job(self) -> PrecomputeJobStatus | None:
        """Look up whichever job is currently running, if any.

        Lets a queued caller's SSE stream show *something* actively
        progressing - proof the server hasn't hung - even though it isn't
        their own job yet. Global concurrency is capped at 1 (see `request`),
        so there is at most one to find.

        Returns:
            PrecomputeJobStatus | None: The running job's status, or `None`
            if nothing is currently running (or the only 'running' row is
            stale - effectively abandoned, not real progress).
        """
        now = time.time()

        with self.lock:
            row = self.db.execute(
                'SELECT lang, word_length, fraction_done, eta_seconds, updated_timestamp FROM precompute_jobs '
                + 'WHERE status = ? LIMIT 1', (statics.PrecomputeStatus.RUNNING.value,)).fetchone()

            if row is None:
                return None

            lang, word_length, fraction_done, eta_seconds, updated_timestamp = row
            if self._is_stale(updated_timestamp, now):
                return None

        return PrecomputeJobStatus(lang=lang, word_length=word_length, status=statics.PrecomputeStatus.RUNNING,
                                   fraction_done=fraction_done, eta_seconds=eta_seconds, error='', position=None)


    def prune_finished(self, retention_seconds: float) -> int:
        """Delete DONE/FAILED rows whose last update is older than `retention_seconds`.

        Mirrors `session_store.SessionStore.delete_expired`: called
        explicitly by the route (not baked into `request()` - `self.lock`
        isn't reentrant, see the note on the internal helpers above), so
        every call to `/precompute` also lazily garbage-collects rows nobody
        will ever query the terminal status of again.

        Args:
            retention_seconds (float): Age threshold, in seconds.

        Returns:
            int: Number of rows deleted.
        """
        now = time.time()

        with self.lock, self.db:
            cursor = self.db.execute(
                'DELETE FROM precompute_jobs WHERE status IN (?, ?) AND (? - updated_timestamp) >= ?',
                (statics.PrecomputeStatus.DONE.value, statics.PrecomputeStatus.FAILED.value, now, retention_seconds))
            return cursor.rowcount


    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self.lock:
            self.db.close()
