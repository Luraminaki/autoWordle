#!/usr/bin/env python3
"""Tests for `autoWordle.app.precompute_store.PrecomputeJobStore`."""

#===================================================================================================
import pathlib
import time

from autoWordle.app import precompute_store
from autoWordle.modules import statics

#===================================================================================================


def test_first_request_starts_immediately(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')

    result = store.request('en', 5)

    assert result.status == statics.PrecomputeStatus.RUNNING
    assert result.position is None
    assert result.should_start is True
    store.close()


def test_duplicate_request_does_not_restart(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    result = store.request('en', 5)

    assert result.status == statics.PrecomputeStatus.RUNNING
    assert result.should_start is False
    store.close()


def test_second_different_combo_queues_behind_running_job(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    result = store.request('fr', 6)

    assert result.status == statics.PrecomputeStatus.QUEUED
    assert result.position == 1
    assert result.should_start is False
    store.close()


def test_multiple_queued_jobs_get_increasing_positions(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    second = store.request('fr', 6)
    third = store.request('wordle', 5)

    assert second.position == 1
    assert third.position == 2
    store.close()


def test_update_progress_and_get_status_round_trip(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    store.update_progress('en', 5, 0.42, 12.3)
    status = store.get_status('en', 5)

    assert status is not None
    assert status.status == statics.PrecomputeStatus.RUNNING
    assert status.fraction_done == 0.42
    assert status.eta_seconds == 12.3
    store.close()


def test_get_status_missing_job_returns_none(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    assert store.get_status('en', 5) is None
    store.close()


def test_mark_done_claims_next_queued_job(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)
    _ = store.request('fr', 6)
    _ = store.request('wordle', 5)

    next_job = store.mark_done('en', 5)

    assert next_job == ('fr', 6)
    assert store.get_status('en', 5).status == statics.PrecomputeStatus.DONE
    assert store.get_status('fr', 6).status == statics.PrecomputeStatus.RUNNING
    # The remaining queued job should have moved up to position 1.
    assert store.get_status('wordle', 5).position == 1
    store.close()


def test_mark_done_with_empty_queue_returns_none(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    assert store.mark_done('en', 5) is None
    store.close()


def test_mark_failed_records_error_and_dispatches_next(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)
    _ = store.request('fr', 6)

    next_job = store.mark_failed('en', 5, 'boom')

    assert next_job == ('fr', 6)
    status = store.get_status('en', 5)
    assert status.status == statics.PrecomputeStatus.FAILED
    assert status.error == 'boom'
    store.close()


def test_stale_running_job_is_reclaimed(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    # Simulate a worker that crashed mid-build: heartbeat far in the past.
    store.db.execute('UPDATE precompute_jobs SET updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                     (time.time() - 999, 'en', 5))

    result = store.request('en', 5)

    assert result.status == statics.PrecomputeStatus.RUNNING
    assert result.should_start is True
    store.close()


def test_reclaim_stale_running_returns_none_when_nothing_stale(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    assert store.reclaim_stale_running() is None
    assert store.get_status('en', 5).status == statics.PrecomputeStatus.RUNNING
    store.close()


def test_reclaim_stale_running_returns_none_when_nothing_running(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    assert store.reclaim_stale_running() is None
    store.close()


def test_reclaim_stale_running_fails_crashed_job_and_promotes_queue(tmp_path: pathlib.Path) -> None:
    # Regression test: a worker that crashes mid-build never calls
    # mark_failed itself (no exception ever reaches run_precompute_job's
    # except block), so without this method, its row stays 'running' forever
    # and anything queued behind it never gets a chance to run.
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)
    _ = store.request('fr', 6)  # queued behind 'en'/5

    store.db.execute('UPDATE precompute_jobs SET updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                     (time.time() - 999, 'en', 5))

    promoted = store.reclaim_stale_running()

    assert promoted == ('fr', 6)
    failed_status = store.get_status('en', 5)
    assert failed_status.status == statics.PrecomputeStatus.FAILED
    assert failed_status.error  # a real, non-empty explanation, not silently blank
    assert store.get_status('fr', 6).status == statics.PrecomputeStatus.RUNNING
    store.close()


def test_reclaim_stale_running_with_no_queue_just_fails_the_stale_job(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)

    store.db.execute('UPDATE precompute_jobs SET updated_timestamp = ? WHERE lang = ? AND word_length = ?',
                     (time.time() - 999, 'en', 5))

    assert store.reclaim_stale_running() is None  # nothing queued to promote
    assert store.get_status('en', 5).status == statics.PrecomputeStatus.FAILED
    store.close()


def test_done_job_can_be_requested_again(tmp_path: pathlib.Path) -> None:
    store = precompute_store.PrecomputeJobStore(tmp_path / 'jobs.sqlite')
    _ = store.request('en', 5)
    _ = store.mark_done('en', 5)

    result = store.request('en', 5)

    assert result.status == statics.PrecomputeStatus.RUNNING
    assert result.should_start is True
    store.close()
