#!/usr/bin/env python3
"""Tests for `autoWordle.app.models`."""

#===================================================================================================
import pathlib

import pytest
from pydantic import ValidationError

from autoWordle.app import models, schemas
from autoWordle.modules import helpers, statics

#===================================================================================================


def test_app_config_rejects_malformed_shape() -> None:
    with pytest.raises(ValidationError):
        _ = schemas.AppConfig.model_validate({'service_id': 'wordle'})  # missing required keys


def test_app_config_defaults_default_word_lengths() -> None:
    conf = schemas.AppConfig.model_validate({
        'service_id': 'wordle', 'logging_level': 'INFO', 'data_folder': 'data/',
        'MAX_SESSIONS': 5, 'SESSION_TTL_SECONDS': 1800,
    })
    assert conf.default_word_lengths == [5]


def test_init_app_sources_from_test_root(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)

    assert 'mini' in app_sources.langs
    assert '5' in app_sources.langs['mini'].pre_computed


def test_init_app_sources_client_view_validates(test_app_root: pathlib.Path) -> None:
    # `client=True` returns a distinct `AppSourcesClientView` (string
    # placeholders throughout, no live `LangLauncher` objects) rather than
    # reusing `AppSources`, so this must be validated directly.
    client_sources = models.init_app_sources(app_root=test_app_root, client=True)

    assert client_sources.langs['mini'].pre_computed['5'].lang_launcher == 'LangLauncher'


def test_create_game_session_rejects_missing_lang_launcher() -> None:
    with pytest.raises(models.GameSessionNotAllowedError):
        _ = models.create_game_session('mini', 5, None, statics.GameMode.GAME_MODE_PLAY)


def test_create_game_session_rejects_solve_mode_without_exhaustive_data(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    # Regression test for the original bug: this used to silently return `{}`
    # instead of raising, which then blew up as an opaque KeyError downstream.
    with pytest.raises(models.GameSessionNotAllowedError):
        _ = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_SOLVE)


def test_create_game_session_allows_play_mode_without_exhaustive_data(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)

    assert session.meta.game_mode == statics.GameMode.GAME_MODE_PLAY
    assert session.meta.current_tries == 0


def test_submit_guess_rejects_solve_mode(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Regression test: GAME_MODE_SOLVE is for solving an *external* puzzle -
    # the pattern comes from outside (passed to get_guess_stats), not from
    # comparison against the session's internal random word. Without this
    # guard, calling submit_guess in this mode would compute a meaningless
    # pattern and double-record the guess alongside get_guess_stats.
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')

    lang_launcher = helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)
    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_SOLVE, max_tries=6)

    with pytest.raises(models.GameSessionNotAllowedError):
        _ = models.submit_guess(session, 'crane')

    assert session.meta.guesses == []
    assert session.meta.current_tries == 0


def test_refresh_lang_launcher_if_stale_picks_up_build_from_another_worker(test_app_root: pathlib.Path) -> None:
    # Simulates two uvicorn workers sharing the same data folder: app_sources
    # is a plain in-memory structure, not SQLite-backed like SESSION_STORE/
    # PRECOMPUTE_STORE, so a build finished by run_precompute_job against a
    # *different* AppSources instance (a different worker) never updates this
    # one on its own - refresh_lang_launcher_if_stale is what closes that gap
    # on next use.
    from autoWordle.app import precompute_store

    worker_a_sources = models.init_app_sources(app_root=test_app_root)
    worker_b_sources = models.init_app_sources(app_root=test_app_root)

    # Neither worker sees exhaustive data for mini/5 yet (no `*_info.csv`
    # marker exists for it in the test data folder).
    assert not worker_a_sources.langs['mini'].pre_computed['5'].lang_launcher.words_information
    assert not worker_b_sources.langs['mini'].pre_computed['5'].lang_launcher.words_information

    # "Worker A" builds it - writes the real *_info.csv/cache sidecars to
    # disk and updates worker_a_sources in place.
    job_store = precompute_store.PrecomputeJobStore(test_app_root / 'jobs.sqlite')
    result = models.request_precompute(worker_a_sources, job_store, 'mini', 5)
    assert result.should_start is True
    models.run_precompute_job(worker_a_sources, job_store, 'mini', 5)
    assert worker_a_sources.langs['mini'].pre_computed['5'].lang_launcher.words_information

    # "Worker B" still doesn't know, until asked to refresh.
    assert not worker_b_sources.langs['mini'].pre_computed['5'].lang_launcher.words_information
    refreshed = models.refresh_lang_launcher_if_stale(worker_b_sources, 'mini', 5)

    assert refreshed is not None
    assert refreshed.words_information
    # And it's now reflected in worker_b_sources itself, not just the return value.
    assert worker_b_sources.langs['mini'].pre_computed['5'].lang_launcher.words_information
    job_store.close()


def test_refresh_lang_launcher_if_stale_returns_none_for_unknown_lang(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)
    assert models.refresh_lang_launcher_if_stale(app_sources, 'does-not-exist', 5) is None


def test_build_client_view_reflects_current_state(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)

    client_view = models.build_client_view(app_sources)

    assert 'mini' in client_view.langs
    assert client_view.langs['mini'].pre_computed['5'].lang_launcher == 'LangLauncher'
    assert client_view.langs['mini'].pre_computed['5'].has_exhaustive_data is False


def test_build_client_view_does_not_leak_the_server_filesystem_path(test_app_root: pathlib.Path) -> None:
    # Regression test: the client view's `path` fields must be just the
    # filename (e.g. "mini.txt"), matching init_app_sources(client=True)'s
    # own convention - not the full absolute server-side path, which would
    # leak the server's filesystem layout (directory structure, OS username
    # on Windows, etc.) to any caller of GET /get_app_sources.
    app_sources = models.init_app_sources(app_root=test_app_root)

    client_view = models.build_client_view(app_sources)

    assert client_view.langs['mini'].path == 'mini.txt'
    assert client_view.langs['mini'].pre_computed['5'].path == 'mini.txt'
    assert str(test_app_root) not in client_view.langs['mini'].path


def test_build_client_view_picks_up_build_from_another_worker(test_app_root: pathlib.Path) -> None:
    from autoWordle.app import precompute_store

    worker_a_sources = models.init_app_sources(app_root=test_app_root)
    worker_b_sources = models.init_app_sources(app_root=test_app_root)

    job_store = precompute_store.PrecomputeJobStore(test_app_root / 'jobs.sqlite')
    _ = models.request_precompute(worker_a_sources, job_store, 'mini', 5)
    models.run_precompute_job(worker_a_sources, job_store, 'mini', 5)

    client_view = models.build_client_view(worker_b_sources)

    assert client_view.langs['mini'].pre_computed['5'].has_exhaustive_data is True
    assert client_view.langs['mini'].pre_computed['5'].lang_launcher == 'LangLauncher'
    job_store.close()


def test_build_client_view_reports_exhaustive_data_right_after_its_own_build(test_app_root: pathlib.Path) -> None:
    # Regression test: run_precompute_job used to construct the fresh
    # PrecomputedEntry without has_exhaustive_data=True (defaulting to
    # False), even though it had just built real exhaustive data. This never
    # surfaced while /get_app_sources always re-derived the flag fresh from
    # disk on every call - but build_client_view instead trusts this
    # in-memory flag directly (to avoid redoing that scan), so the bug
    # became directly observable: the "Build solver data" button's own
    # worker would report has_exhaustive_data=False for the very combo it
    # just finished building, leaving Start disabled forever after a
    # same-worker build (no second "different worker" involved at all,
    # unlike the cross-worker discovery test above).
    from autoWordle.app import precompute_store

    app_sources = models.init_app_sources(app_root=test_app_root)
    job_store = precompute_store.PrecomputeJobStore(test_app_root / 'jobs.sqlite')

    _ = models.request_precompute(app_sources, job_store, 'mini', 5)
    models.run_precompute_job(app_sources, job_store, 'mini', 5)

    client_view = models.build_client_view(app_sources)

    assert client_view.langs['mini'].pre_computed['5'].has_exhaustive_data is True
    job_store.close()


def test_submit_guess_raises_when_no_tries_remaining(test_app_root: pathlib.Path) -> None:
    # Regression test: this used to return None, indistinguishable from an
    # invalid word - webapp.api_views.submit_guess then always reported both
    # as INVALID_WORD, telling a player who was simply out of tries that
    # their (possibly valid) word was invalid.
    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=1)
    word_str = ''.join(chr(letter + session.game.shift) for letter in next(iter(session.game.language_launcher.words)))

    _ = models.submit_guess(session, word_str)  # uses up the only try
    assert session.meta.current_tries == 1

    with pytest.raises(models.NoTriesRemainingError):
        _ = models.submit_guess(session, word_str)


def test_submit_guess_and_get_stats_round_trip(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)

    word_str = ''.join(chr(letter + session.game.shift) for letter in next(iter(session.game.language_launcher.words)))
    pattern = models.submit_guess(session, word_str)

    assert pattern is not None
    assert len(pattern) == 5
    assert session.meta.current_tries == 1
    assert session.meta.guesses == [word_str]

    stats = models.get_game_session_stats(session)
    assert stats.current_tries == 1
    assert stats.guesses == [word_str]


def test_get_initial_hints_reports_best_opening_before_any_guess(test_app_root: pathlib.Path) -> None:
    from autoWordle.app import precompute_store

    app_sources = models.init_app_sources(app_root=test_app_root)
    job_store = precompute_store.PrecomputeJobStore(test_app_root / 'jobs.sqlite')
    _ = models.request_precompute(app_sources, job_store, 'mini', 5)
    models.run_precompute_job(app_sources, job_store, 'mini', 5)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_ASSISTED, max_tries=6)

    hints = models.get_initial_hints(session)

    assert hints is not None
    assert hints.best_guess is not None
    assert len(hints.pool_words) == 20  # the whole mini.txt list - nothing guessed yet
    assert hints.information > 0
    # Nothing was actually guessed - get_initial_hints must not mutate session state.
    assert session.meta.guesses == []
    assert session.meta.current_tries == 0
    job_store.close()


def test_get_initial_hints_returns_none_for_play_mode(test_app_root: pathlib.Path) -> None:
    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)

    assert models.get_initial_hints(session) is None


def test_get_initial_hints_returns_none_without_exhaustive_data(test_app_root: pathlib.Path) -> None:
    # Defensive guard: create_game_session already refuses to create an
    # ASSISTED session without exhaustive data, so this shouldn't be
    # reachable via the normal flow - constructs the session directly to
    # confirm get_initial_hints doesn't assume that invariant blindly.
    from autoWordle.modules import wordle

    app_sources = models.init_app_sources(app_root=test_app_root)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    assert not lang_launcher.words_information  # no `*_info.csv` marker for mini/5 in the test data folder

    meta = schemas.GameSessionMeta(session_uuid='test', lang='mini', word_length=5,
                                   game_mode=statics.GameMode.GAME_MODE_ASSISTED, max_tries=6,
                                   created_timestamp=0, last_active_timestamp=0)
    session = models.GameSession(meta=meta, game=wordle.Wordle(lang_launcher))

    assert models.get_initial_hints(session) is None
