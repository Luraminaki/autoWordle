#!/usr/bin/env python3
"""End-to-end tests for the FastAPI routes in `webapp.api_views`, via the mini word list."""

#===================================================================================================
from fastapi.testclient import TestClient

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
