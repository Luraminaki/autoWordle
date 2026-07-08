#!/usr/bin/env python3
"""Tests for `autoWordle.modules.compendium_cache.CacheDB`.

Replaces the old ad-hoc `scripts/testouille_cache.py` smoke test with real,
isolated (tmp_path-based) coverage - including a regression test for the
pragma bug where `journal_mode`/`synchronous`/`locking_mode` were "restored"
to invalid values that SQLite silently ignored, permanently leaving the
connection in unsafe/exclusive mode after any write.
"""

#===================================================================================================
import pathlib

from autoWordle.modules import compendium_cache

#===================================================================================================


def test_add_and_get_entries_round_trip(tmp_path: pathlib.Path) -> None:
    cache = compendium_cache.CacheDB(tmp_path / 'cache.sqlite', patterns=[111, 222], build_mode=True)

    assert cache.add_entries(111, guess=[1, 2, 3], word=[10, 20, 30])
    assert cache.add_entries(222, guess=[4], word=[40])

    assert sorted(cache.get_entries(111)) == [(1, 10), (2, 20), (3, 30)]
    assert cache.get_entries(222) == [(4, 40)]

    cache.close()


def test_get_entries_missing_pattern_returns_empty(tmp_path: pathlib.Path) -> None:
    cache = compendium_cache.CacheDB(tmp_path / 'cache.sqlite', patterns=[111], build_mode=True)
    assert cache.get_entries(999) == []
    cache.close()


def test_add_entries_rejects_mismatched_lengths(tmp_path: pathlib.Path) -> None:
    cache = compendium_cache.CacheDB(tmp_path / 'cache.sqlite', patterns=[111], build_mode=True)
    assert cache.add_entries(111, guess=[1, 2], word=[10]) is False
    assert cache.add_entries(111, guess=[], word=[]) is False
    cache.close()


def test_add_entries_batch_writes_every_pattern(tmp_path: pathlib.Path) -> None:
    cache = compendium_cache.CacheDB(tmp_path / 'cache.sqlite', patterns=[111, 222, 333], build_mode=True)

    assert cache.add_entries_batch({
        111: ([1, 2, 3], [10, 20, 30]),
        222: ([4], [40]),
    })

    assert sorted(cache.get_entries(111)) == [(1, 10), (2, 20), (3, 30)]
    assert cache.get_entries(222) == [(4, 40)]
    assert cache.get_entries(333) == []

    cache.close()


def test_add_entries_batch_skips_mismatched_pattern_but_writes_others(tmp_path: pathlib.Path) -> None:
    cache = compendium_cache.CacheDB(tmp_path / 'cache.sqlite', patterns=[111, 222], build_mode=True)

    assert cache.add_entries_batch({
        111: ([1, 2], [10]),  # mismatched lengths - skipped, not fatal to the whole batch
        222: ([4], [40]),
    })

    assert cache.get_entries(111) == []
    assert cache.get_entries(222) == [(4, 40)]

    cache.close()


def test_reopening_existing_cache_preserves_data(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / 'cache.sqlite'

    cache = compendium_cache.CacheDB(db_path, patterns=[111], build_mode=True)
    _ = cache.add_entries(111, guess=[1], word=[10])
    cache.close()

    reopened = compendium_cache.CacheDB(db_path)
    assert reopened.get_entries(111) == [(1, 10)]
    reopened.close()


def test_build_mode_pragmas_are_valid_and_stick(tmp_path: pathlib.Path) -> None:
    # Regression test for the invalid-pragma-value bug: after building,
    # re-opening the connection must report real, valid pragma values, not
    # a silently-ignored "ON" left over from a broken restore step.
    db_path = tmp_path / 'cache.sqlite'
    cache = compendium_cache.CacheDB(db_path, patterns=[111], build_mode=True)
    _ = cache.add_entries(111, guess=[1], word=[10])

    journal_mode = cache.db.execute('PRAGMA journal_mode').fetchone()[0]
    synchronous = cache.db.execute('PRAGMA synchronous').fetchone()[0]
    assert journal_mode.lower() == 'off'
    assert synchronous == 0  # OFF
    cache.close()


def test_read_mode_uses_wal_and_normal_synchronous(tmp_path: pathlib.Path) -> None:
    db_path = tmp_path / 'cache.sqlite'
    build_cache = compendium_cache.CacheDB(db_path, patterns=[111], build_mode=True)
    _ = build_cache.add_entries(111, guess=[1], word=[10])
    build_cache.close()

    read_cache = compendium_cache.CacheDB(db_path, build_mode=False)
    journal_mode = read_cache.db.execute('PRAGMA journal_mode').fetchone()[0]
    synchronous = read_cache.db.execute('PRAGMA synchronous').fetchone()[0]
    assert journal_mode.lower() == 'wal'
    assert synchronous == 1  # NORMAL
    assert read_cache.get_entries(111) == [(1, 10)]
    read_cache.close()
