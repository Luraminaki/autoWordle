#!/usr/bin/env python3
"""End-to-end tests for the FastAPI routes in `webapp.api_views`, via the mini word list."""

#===================================================================================================
import json

import pytest
from fastapi.testclient import TestClient

from autoWordle.modules import computing, statics

#===================================================================================================


def test_version(client: TestClient) -> None:
    response = client.get('/api/app/version')
    assert response.status_code == 200
    assert response.json()['status'] == 'SUCCESS'


def test_get_app_sources_reports_mini_lang(client: TestClient) -> None:
    response = client.get('/api/app/get_app_sources')
    body = response.json()

    assert response.status_code == 200
    assert body['status'] == 'SUCCESS'
    assert 'mini' in body['app_sources']['langs']


def test_create_game_session_and_submit_guess_play_mode(client: TestClient) -> None:
    create = client.post('/api/app/create_game_session',
                         json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
    assert create.status_code == 200
    assert create.json()['status'] == 'SUCCESS'
    session_uuid = create.json()['session_uuid']

    guess = client.post('/api/app/submit_guess', json={'session_uuid': session_uuid, 'word': 'crane'})
    assert guess.status_code == 200
    assert guess.json()['status'] == 'SUCCESS'
    assert len(guess.json()['pattern']) == 5  # 5 emoji characters

    stats = client.post('/api/app/get_game_session_stats', json={'session_uuid': session_uuid})
    assert stats.json()['status'] == 'SUCCESS'
    assert stats.json()['session_stats']['current_tries'] == 1
    assert stats.json()['session_stats']['guesses'] == ['crane']


def test_submit_guess_reports_no_tries_remaining_distinctly(client: TestClient) -> None:
    # Regression test: this used to be indistinguishable from INVALID_WORD,
    # so a player simply out of tries was told their (possibly valid) word
    # was invalid.
    create = client.post('/api/app/create_game_session',
                         json={'lang': 'mini', 'word_length': 5, 'max_tries': 1, 'game_mode': 'GAME_MODE_PLAY'})
    session_uuid = create.json()['session_uuid']

    first = client.post('/api/app/submit_guess', json={'session_uuid': session_uuid, 'word': 'crane'})
    assert first.json()['status'] == 'SUCCESS'  # uses up the only try

    second = client.post('/api/app/submit_guess', json={'session_uuid': session_uuid, 'word': 'crane'})
    assert second.json()['status'] == 'ERROR'
    assert second.json()['error'] == 'NO_TRIES_REMAINING'


def test_create_game_session_rejects_unknown_session_on_submit(client: TestClient) -> None:
    response = client.post('/api/app/submit_guess', json={'session_uuid': 'does-not-exist', 'word': 'crane'})
    assert response.status_code == 200
    assert response.json()['status'] == 'ERROR'


def test_get_guess_stats_solve_mode_reports_best_guess(client: TestClient) -> None:
    trigger = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    assert trigger.json()['job_status'] in ('running', 'done')

    create = client.post('/api/app/create_game_session',
                         json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_SOLVE'})
    assert create.json()['status'] == 'SUCCESS'
    session_uuid = create.json()['session_uuid']

    # A real, guaranteed-non-empty-pool pattern: what "crane" actually
    # produces against another real mini.txt word (arbitrary hand-picked
    # emoji, unlike here, can correspond to no word at all and empty the pool).
    shift = ord('a') - 10
    guess = tuple(ord(letter) - shift for letter in 'crane')
    target = tuple(ord(letter) - shift for letter in 'table')
    pattern = statics.pattern_to_emoji(computing.compute_pattern(guess=guess, word=target))

    stats = client.post('/api/app/get_guess_stats',
                        json={'session_uuid': session_uuid, 'word': 'crane', 'pattern': pattern})
    body = stats.json()

    assert stats.status_code == 200
    assert body['status'] == 'SUCCESS'
    guess_stats = body['guess_stats']

    assert guess_stats['best_guess'] is not None
    assert len(guess_stats['best_guess']) == 1  # a single {word: entropy} entry
    best_word = next(iter(guess_stats['best_guess']))
    assert len(best_word) == 5
    # The reported best guess must be the top of pool_words/elimination_suggestions
    # combined - at minimum, its entropy should be >= every pool candidate's.
    best_entropy = guess_stats['best_guess'][best_word]
    assert all(best_entropy >= entropy for pool_word in guess_stats['pool_words'] for entropy in pool_word.values())


def test_create_game_session_solve_mode_fails_without_exhaustive_data(client: TestClient) -> None:
    response = client.post('/api/app/create_game_session',
                           json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_SOLVE'})
    assert response.status_code == 200
    assert response.json()['status'] == 'ERROR'
    assert response.json()['session_uuid'] is None
    # Regression test: this used to only be caught by a generic `except
    # Exception`, so the caller got the opaque INTERNAL_ERROR instead of the
    # specific, safe validation message - and the routine rejection was
    # logged server-side as if it were an unexpected bug.
    assert response.json()['error'] != 'INTERNAL_ERROR'
    assert 'exhaustive solver data' in response.json()['error']


def test_max_sessions_limit_is_enforced(client: TestClient) -> None:
    responses = [client.post('/api/app/create_game_session',
                             json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
                 for _ in range(6)]  # MAX_SESSIONS is 5 in the test config

    statuses = [r.json()['status'] for r in responses]
    assert statuses.count('SUCCESS') == 5
    assert statuses.count('ERROR') == 1


def test_create_game_session_purges_expired_sessions_before_counting(client: TestClient) -> None:
    from autoWordle.webapp import api_views

    responses = [client.post('/api/app/create_game_session',
                             json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
                 for _ in range(5)]  # fills MAX_SESSIONS
    assert all(r.json()['status'] == 'SUCCESS' for r in responses)

    # Backdate one session past the TTL directly in the store, without ever
    # calling get_active_games (the only other place that purges) - this is
    # exactly the scenario create_game_session must handle on its own now.
    stale_uuid = responses[0].json()['session_uuid']
    ttl_seconds = 1800  # matches conftest's SESSION_TTL_SECONDS
    with api_views.SESSION_STORE.lock, api_views.SESSION_STORE.db:
        _ = api_views.SESSION_STORE.db.execute(
            'UPDATE sessions SET last_active_timestamp = last_active_timestamp - ? WHERE session_uuid = ?',
            (ttl_seconds + 10, stale_uuid),
        )

    response = client.post('/api/app/create_game_session',
                           json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
    assert response.json()['status'] == 'SUCCESS'


def test_delete_game_session(client: TestClient) -> None:
    create = client.post('/api/app/create_game_session',
                         json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
    session_uuid = create.json()['session_uuid']

    delete = client.post('/api/app/delete_game_session', json={'session_uuid': session_uuid})
    assert delete.json()['status'] == 'SUCCESS'

    stats = client.post('/api/app/get_game_session_stats', json={'session_uuid': session_uuid})
    assert stats.json()['status'] == 'ERROR'


def test_precompute_builds_and_progress_reports_done(client: TestClient) -> None:
    # `mini` starts with `compute_best_opening=False` (see conftest's
    # test config), so GAME_MODE_SOLVE isn't allowed for it yet.
    solve_before = client.post('/api/app/create_game_session',
                               json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_SOLVE'})
    assert solve_before.json()['status'] == 'ERROR'

    trigger = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    body = trigger.json()
    assert trigger.status_code == 200
    assert body['status'] == 'SUCCESS'
    assert body['job_status'] == 'running'
    assert body['queue_position'] is None

    # `TestClient` runs scheduled `BackgroundTasks` to completion within the
    # same call that returned `trigger` above (the tiny mini.txt build is
    # well within that window), so the job should already be done by now -
    # still read the SSE stream to exercise it, not just assume this.
    with client.stream('GET', '/api/app/precompute_progress', params={'lang': 'mini', 'word_length': 5}) as stream:
        events = []
        for line in stream.iter_lines():
            if not line.startswith('data: '):
                continue
            events.append(json.loads(line[len('data: '):]))
            if events[-1]['status'] in ('done', 'failed'):
                break

    assert events
    assert events[-1]['status'] == 'done'
    assert events[-1]['fraction_done'] == 1.0

    # The swap into the shared AppSources actually took effect - GAME_MODE_SOLVE
    # should now be allowed.
    solve_after = client.post('/api/app/create_game_session',
                              json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_SOLVE'})
    assert solve_after.json()['status'] == 'SUCCESS'


def test_precompute_skips_when_already_done(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from autoWordle.webapp import api_views

    trigger = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    assert trigger.json()['job_status'] == 'running'  # already 'done' by the time this returns - see the test above

    # Prove the short-circuit happens *before* ever reaching the job store,
    # not just that the end result happens to look the same - a reclaim
    # would also converge back to 'done' by the time TestClient's synchronous
    # BackgroundTasks finish, so the response body alone can't distinguish
    # "never touched" from "touched, then finished again".
    calls = []
    original_request = api_views.PRECOMPUTE_STORE.request

    def counting_request(lang: str, word_length: int):
        calls.append((lang, word_length))
        return original_request(lang, word_length)

    monkeypatch.setattr(api_views.PRECOMPUTE_STORE, 'request', counting_request)

    response = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    body = response.json()

    assert body['status'] == 'SUCCESS'
    assert body['job_status'] == 'done'
    assert body['queue_position'] is None
    assert calls == []


def test_precompute_duplicate_request_does_not_restart(client: TestClient) -> None:
    from autoWordle.webapp import api_views

    # Simulate a build already in progress for this combo, bypassing the
    # route (TestClient runs BackgroundTasks to completion synchronously, so
    # a real request/request race can't be reproduced through the HTTP layer
    # in this test environment).
    first = api_views.PRECOMPUTE_STORE.request('mini', 5)
    assert first.should_start is True

    response = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    body = response.json()

    assert body['status'] == 'SUCCESS'
    assert body['job_status'] == 'running'


def test_precompute_failure_does_not_leak_raw_exception_detail(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: a failed build used to store repr(err) as the job's
    # error - potentially including internal file paths - and that raw text
    # was streamed verbatim to any SSE client. It must now be a safe, generic
    # message instead (the real exception is still logged server-side).
    from autoWordle.app import models

    def _boom(*_args, **_kwargs):
        raise PermissionError(13, r"Permission denied: C:\secret\internal\path\wordle_en.txt")

    monkeypatch.setattr(models.helpers, 'LangLauncher', _boom)

    # Same as test_precompute_builds_and_progress_reports_done: the trigger
    # response reflects the state at scheduling time (before the background
    # task runs), always 'running' here - the SSE stream below observes the
    # eventual outcome.
    trigger = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    assert trigger.json()['job_status'] == 'running'

    with client.stream('GET', '/api/app/precompute_progress', params={'lang': 'mini', 'word_length': 5}) as stream:
        line = next(line for line in stream.iter_lines() if line.startswith('data: '))
    payload = json.loads(line[len('data: '):])

    assert payload['status'] == 'failed'
    assert 'secret' not in payload['error']
    assert 'PermissionError' not in payload['error']
    assert payload['error'] == 'Build failed - see server logs for details'


def test_precompute_prunes_finished_jobs_before_counting(client: TestClient) -> None:
    from autoWordle.app import precompute_store
    from autoWordle.webapp import api_views

    # A finished job for an unrelated combo, backdated well past the
    # retention window - the next /precompute call (for anything) should
    # sweep it away as a lazy side effect, same pattern as
    # create_game_session's expired-session purge.
    old = api_views.PRECOMPUTE_STORE.request('mini', 9)
    assert old.should_start is True
    _ = api_views.PRECOMPUTE_STORE.mark_done('mini', 9)

    with api_views.PRECOMPUTE_STORE.lock, api_views.PRECOMPUTE_STORE.db:
        _ = api_views.PRECOMPUTE_STORE.db.execute(
            'UPDATE precompute_jobs SET updated_timestamp = updated_timestamp - ? WHERE lang = ? AND word_length = ?',
            (precompute_store.FINISHED_RETENTION_SECONDS + 10, 'mini', 9))

    assert api_views.PRECOMPUTE_STORE.get_status('mini', 9) is not None

    response = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5})
    assert response.json()['status'] == 'SUCCESS'

    assert api_views.PRECOMPUTE_STORE.get_status('mini', 9) is None


def test_precompute_second_combo_queues_behind_running_job(client: TestClient) -> None:
    from autoWordle.webapp import api_views

    first = api_views.PRECOMPUTE_STORE.request('mini', 5)
    assert first.should_start is True

    response = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 6})
    body = response.json()

    assert body['status'] == 'SUCCESS'
    assert body['job_status'] == 'queued'
    assert body['queue_position'] == 1


def test_precompute_progress_includes_current_job_when_queued(client: TestClient) -> None:
    # Deliberately not read through the live SSE stream: a queued job that
    # never resolves (mini/5 is never marked done/failed here) keeps
    # `event_stream` looping forever, and draining a non-terminating
    # StreamingResponse through TestClient hangs rather than allowing an
    # early exit - call the payload-building helper directly instead.
    from autoWordle.webapp import api_views

    first = api_views.PRECOMPUTE_STORE.request('mini', 5)
    assert first.should_start is True
    api_views.PRECOMPUTE_STORE.update_progress('mini', 5, 0.42, 17.0)

    second = api_views.PRECOMPUTE_STORE.request('mini', 6)
    assert second.should_start is False
    assert second.status.value == 'queued'

    job = api_views.PRECOMPUTE_STORE.get_status('mini', 6)
    payload = api_views._precompute_progress_payload(job)

    assert payload['status'] == 'queued'
    assert payload['current_job'] == {'lang': 'mini', 'word_length': 5, 'fraction_done': 0.42, 'eta_seconds': 17.0}


def test_precompute_route_reclaims_stale_running_job_and_schedules_the_promoted_one(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: PrecomputeJobStore.reclaim_stale_running can detect and
    # fail a crashed worker's job and promote the next queued one in the DB,
    # but it has no ability to actually *run* anything - the route calling it
    # must schedule the promoted job itself, or it would just sit as
    # 'running' with nothing ever computing it.
    from autoWordle.webapp import api_views

    first = api_views.PRECOMPUTE_STORE.request('mini', 5)
    assert first.should_start is True
    second = api_views.PRECOMPUTE_STORE.request('mini', 6)  # queued behind mini/5
    assert second.should_start is False

    with api_views.PRECOMPUTE_STORE.lock, api_views.PRECOMPUTE_STORE.db:
        _ = api_views.PRECOMPUTE_STORE.db.execute(
            'UPDATE precompute_jobs SET updated_timestamp = updated_timestamp - ? WHERE lang = ? AND word_length = ?',
            (60.0, 'mini', 5))  # older than _STALE_TIMEOUT_SECONDS

    scheduled = []
    monkeypatch.setattr(api_views.models, 'run_precompute_job',
                        lambda app_sources, job_store, lang, word_length: scheduled.append((lang, word_length)))

    # Any /precompute call opportunistically reclaims - use an unrelated,
    # already-done-style rejection (unknown lang) so this call itself doesn't
    # start yet another job and muddy the assertion.
    _ = client.post('/api/app/precompute', json={'lang': 'does-not-exist', 'word_length': 5})

    assert ('mini', 6) in scheduled
    assert api_views.PRECOMPUTE_STORE.get_status('mini', 5).status.value == 'failed'
    assert api_views.PRECOMPUTE_STORE.get_status('mini', 6).status.value == 'running'


def test_precompute_rate_limit_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from autoWordle.app import precompute_store
    from autoWordle.webapp import api_views

    # Mocked so this test is purely about the rate limiter dependency, not
    # precompute's own business logic (already covered by the other
    # precompute tests above) - keeps it fast and avoids running `limit`
    # real background builds for word lengths mini.txt doesn't actually have.
    monkeypatch.setattr(api_views.models, 'request_precompute', lambda *_a, **_kw: precompute_store.PrecomputeRequestResult(
        status=statics.PrecomputeStatus.DONE, position=None, should_start=False))

    limit = api_views.PRECOMPUTE_RATE_LIMITER.limit
    responses = [client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 5 + i}) for i in range(limit + 1)]

    assert all(r.status_code == 200 for r in responses[:limit])
    assert responses[limit].status_code == 429
    assert 'Too many requests' in responses[limit].json()['detail']


def test_precompute_rejects_unknown_language(client: TestClient) -> None:
    response = client.post('/api/app/precompute', json={'lang': 'does-not-exist', 'word_length': 5})
    body = response.json()

    assert response.status_code == 200
    assert body['status'] == 'ERROR'


def test_precompute_progress_reports_error_on_unexpected_exception(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: this generator used to have no exception handling at
    # all, unlike every other route in this module - an unexpected failure
    # just silently killed the stream with no error event and no server-side
    # log entry from this module.
    from autoWordle.webapp import api_views

    _ = api_views.PRECOMPUTE_STORE.request('mini', 5)

    def _boom(*_args, **_kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(api_views.PRECOMPUTE_STORE, 'get_status', _boom)

    with client.stream('GET', '/api/app/precompute_progress', params={'lang': 'mini', 'word_length': 5}) as stream:
        line = next(line for line in stream.iter_lines() if line.startswith('data: '))
    payload = json.loads(line[len('data: '):])

    assert payload['status'] == 'error'
    assert payload['error'] == 'INTERNAL_ERROR'


def test_precompute_progress_reports_not_found_for_unrequested_combo(client: TestClient) -> None:
    with client.stream('GET', '/api/app/precompute_progress', params={'lang': 'mini', 'word_length': 5}) as stream:
        line = next(line for line in stream.iter_lines() if line.startswith('data: '))

    assert json.loads(line[len('data: '):])['status'] == 'not_found'
