#!/usr/bin/env python3
"""End-to-end tests for the FastAPI routes in `webapp.api_views`, via the mini word list."""

#===================================================================================================
import json

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


def test_max_sessions_limit_is_enforced(client: TestClient) -> None:
    responses = [client.post('/api/app/create_game_session',
                             json={'lang': 'mini', 'word_length': 5, 'max_tries': 6, 'game_mode': 'GAME_MODE_PLAY'})
                 for _ in range(6)]  # MAX_SESSIONS is 5 in the test config

    statuses = [r.json()['status'] for r in responses]
    assert statuses.count('SUCCESS') == 5
    assert statuses.count('ERROR') == 1


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


def test_precompute_second_combo_queues_behind_running_job(client: TestClient) -> None:
    from autoWordle.webapp import api_views

    first = api_views.PRECOMPUTE_STORE.request('mini', 5)
    assert first.should_start is True

    response = client.post('/api/app/precompute', json={'lang': 'mini', 'word_length': 6})
    body = response.json()

    assert body['status'] == 'SUCCESS'
    assert body['job_status'] == 'queued'
    assert body['queue_position'] == 1


def test_precompute_rejects_unknown_language(client: TestClient) -> None:
    response = client.post('/api/app/precompute', json={'lang': 'does-not-exist', 'word_length': 5})
    body = response.json()

    assert response.status_code == 200
    assert body['status'] == 'ERROR'


def test_precompute_progress_reports_not_found_for_unrequested_combo(client: TestClient) -> None:
    with client.stream('GET', '/api/app/precompute_progress', params={'lang': 'mini', 'word_length': 5}) as stream:
        line = next(line for line in stream.iter_lines() if line.startswith('data: '))

    assert json.loads(line[len('data: '):])['status'] == 'not_found'
