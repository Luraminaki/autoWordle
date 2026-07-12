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
