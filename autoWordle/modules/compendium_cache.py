#!/usr/bin/env python3
"""SQLite-backed cache of `pattern -> (guess, word)` pairs, one table per pattern.

One long-lived connection, pragmas set once at open time instead of toggled
around every write (see https://kerkour.com/sqlite-for-servers). The previous
implementation toggled `journal_mode`/`synchronous`/`locking_mode` to invalid
pragma values around every write (`PRAGMA journal_mode = ON` isn't a real
mode) - SQLite silently ignores unrecognized pragma values, so the "restore
to safe settings" step never took effect and every write left the connection
permanently in unsafe/exclusive mode.

Bucketing entries into one table per pattern (instead of one table with an
indexed `pattern` column) was benchmarked, not assumed: for ~900 words / 225
patterns / ~800K pairs, many-tables was both smaller (~16MB vs ~26MB) and as
fast or faster to build than a single indexed table, because a secondary
index duplicates the pattern value for every one of millions of rows, which
many-tables never needs to store at all - the "table" a row belongs to already
encodes its pattern for free.

The cache is fully regenerable from the source word list, so a best-effort
`synchronous=OFF` build mode is offered for the one-time bulk build pass,
separate from the durable `NORMAL` mode used for the long-lived connection
serving reads during gameplay.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import _thread
import logging
import pathlib
import sqlite3
from collections.abc import Iterable
from threading import Lock

logger = logging.getLogger(__name__)


class CacheDB:
    """A one-table-per-pattern SQLite cache of `(guess, word)` pairs."""

    def __init__(self, db_file_path: str | pathlib.Path, patterns: Iterable[int] = (), build_mode: bool = False) -> None:
        """Open (creating if needed) the cache database.

        Args:
            db_file_path: Path to the SQLite file.
            patterns: Pattern ints to create tables for. Pass none when
                opening an already-built cache (its tables already exist).
            build_mode: When `True`, trade durability for raw insert speed
                (`synchronous=OFF`) for a one-time bulk build. When `False`
                (default), use `synchronous=NORMAL`, appropriate for a
                long-lived connection serving reads during gameplay.
        """
        self.db_path: str = str(db_file_path)
        self.lock: _thread.LockType = Lock()
        self.db: sqlite3.Connection = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False)

        with self.lock:
            if build_mode:
                # One-time bulk build of a fully regenerable cache: avoid WAL
                # entirely. WAL's periodic auto-checkpointing (writing
                # accumulated WAL pages back to the main file) measurably
                # dominates at real data volumes even though it looked
                # faster in small-scale trials - `journal_mode=OFF` (no
                # journal at all) wins once the checkpoint threshold is
                # crossed repeatedly during a large bulk load.
                _ = self.db.execute('PRAGMA journal_mode=OFF')
                _ = self.db.execute('PRAGMA synchronous=OFF')
                _ = self.db.execute('PRAGMA locking_mode=EXCLUSIVE')
            else:
                _ = self.db.execute('PRAGMA journal_mode=WAL')
                _ = self.db.execute('PRAGMA synchronous=NORMAL')

            _ = self.db.execute('PRAGMA temp_store=MEMORY')
            _ = self.db.execute('PRAGMA busy_timeout=5000')
            _ = self.db.execute('PRAGMA cache_size=-20000')  # ~20 MB page cache, negative = KB

            with self.db:
                for pattern in patterns:
                    _ = self.db.execute(f'CREATE TABLE IF NOT EXISTS "{pattern}" (guess INTEGER NOT NULL, word INTEGER NOT NULL)')


    def add_entries(self, pattern: int, guess: list[int], word: list[int]) -> bool:
        """Insert every `(guess, word)` pair for a given pattern.

        Args:
            pattern: Pattern these pairs produce, packed as an int; must
                already have a table (see `patterns` in `__init__`).
            guess: Guess words, packed as ints, aligned with `word`.
            word: Target words, packed as ints, aligned with `guess`.

        Returns:
            bool: `True` on success.
        """
        if not guess or len(guess) != len(word):
            logger.warning("Refusing to INSERT mismatched/empty entries for pattern %s", pattern)
            return False

        try:
            with self.lock, self.db:
                _ = self.db.executemany(f'INSERT INTO "{pattern}" (guess, word) VALUES (?, ?)', list(zip(guess, word, strict=True)))

        except Exception:
            logger.exception("Failed to INSERT entries for pattern %s", pattern)
            return False

        return True


    def add_entries_batch(self, entries: dict[int, tuple[list[int], list[int]]]) -> bool:
        """Insert several patterns' `(guess, word)` pairs in a single transaction.

        Committing once per pattern (as repeatedly calling `add_entries`
        would) means as many commits as there are patterns in `entries` -
        for a real word list flushed in batches, that's thousands of
        transactions where one would do. Bulk callers (e.g. `helpers`'s
        streaming compendium builder) should use this instead.

        Args:
            entries: Pattern (packed int) -> `(guesses, words)`, aligned
                lists. Every pattern must already have a table (see
                `patterns` in `__init__`).

        Returns:
            bool: `True` on success (a mismatched/empty entry for one
            pattern is skipped with a warning, not treated as failure).
        """
        try:
            with self.lock, self.db:
                for pattern, (guess, word) in entries.items():
                    if not guess or len(guess) != len(word):
                        logger.warning("Refusing to INSERT mismatched/empty entries for pattern %s", pattern)
                        continue

                    _ = self.db.executemany(f'INSERT INTO "{pattern}" (guess, word) VALUES (?, ?)', list(zip(guess, word, strict=True)))

        except Exception:
            logger.exception("Failed to INSERT batched entries")
            return False

        return True


    def get_entries(self, pattern: int) -> list[tuple[int, int]]:
        """Fetch every `(guess, word)` pair recorded for a given pattern.

        Args:
            pattern: Pattern to look up, packed as an int.

        Returns:
            list[tuple[int, int]]: `(guess, word)` pairs for `pattern`, empty
            if that pattern has no table (never occurred in the source pool).
        """
        try:
            with self.lock:
                return list(self.db.execute(f'SELECT guess, word FROM "{pattern}"'))

        except sqlite3.OperationalError:
            # Expected/harmless: this pattern never occurred in the source
            # pool, so it has no table - not worth an ERROR-level traceback.
            logger.debug("No table for pattern %s (never occurred in the source pool)", pattern)
            return []

        except Exception:
            logger.exception("Failed to SELECT entries for pattern %s", pattern)
            return []


    def get_words_for_guess(self, pattern: int, guess: int) -> list[int]:
        """Fetch every target word recorded for a given pattern *and* guess.

        Filters server-side (`WHERE guess = ?`) instead of `get_entries`
        fetching every row for `pattern` and filtering in Python - a single
        pattern's table holds every guess's matches across the whole source
        pool (tens of thousands of rows for a real word list), of which only
        a handful ever match one specific guess. Profiled as the dominant
        cost of live per-guess pool narrowing before this method existed.

        Args:
            pattern: Pattern to look up, packed as an int.
            guess: Guess to filter by, packed as an int.

        Returns:
            list[int]: Packed target-word ints, empty if that pattern has no
            table (never occurred in the source pool) or none match `guess`.
        """
        try:
            with self.lock:
                return [row[0] for row in self.db.execute(f'SELECT word FROM "{pattern}" WHERE guess = ?', (guess,))]

        except sqlite3.OperationalError:
            logger.debug("No table for pattern %s (never occurred in the source pool)", pattern)
            return []

        except Exception:
            logger.exception("Failed to SELECT entries for pattern %s and guess %s", pattern, guess)
            return []


    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self.lock:
            self.db.close()
