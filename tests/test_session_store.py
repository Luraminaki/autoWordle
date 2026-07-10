#!/usr/bin/env python3
"""Tests for `autoWordle.app.session_store`."""

#===================================================================================================
import pathlib
import time

from autoWordle.app import models, schemas, session_store
from autoWordle.modules import computing, helpers, statics

#===================================================================================================


def _build_app_sources(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> schemas.AppSources:
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')

    lang_launcher = helpers.LangLauncher(words_file, compute_best_opening=False, word_length=5)
    pre_computed = schemas.PrecomputedEntry(path=words_file, length=5, lang_launcher=lang_launcher)
    lang_source = schemas.LangSource(path=words_file, pre_computed={'5': pre_computed})
    conf = schemas.AppConfig.model_validate({
        'service_id': 'wordle-test', 'logging_level': 'INFO', 'data_folder': 'data/',
        'MAX_SESSIONS': 5, 'SESSION_TTL_SECONDS': 1800,
    })

    return schemas.AppSources(config=conf, langs={'mini': lang_source}, game_modes={})


def test_save_and_load_round_trip(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)
    word_str = ''.join(chr(letter + session.game.shift) for letter in next(iter(session.game.language_launcher.words)))
    _ = models.submit_guess(session, word_str)  # mutates game.pool_words/letter_extractor via the real solver

    store.save(session)
    loaded = store.load(session.meta.session_uuid)

    assert loaded is not None
    assert loaded.meta == session.meta
    assert loaded.game.word == session.game.word
    assert loaded.game.pool_words == session.game.pool_words
    assert loaded.game.information == session.game.information
    assert loaded.game.letter_extractor == session.game.letter_extractor

    store.close()


def test_save_and_load_round_trip_preserves_populated_letter_extractor(tmp_path: pathlib.Path,
                                                                       mini_words_file: pathlib.Path) -> None:
    # Regression test for the LetterExtractor dict -> dataclass conversion:
    # `test_save_and_load_round_trip` above only ever exercises an *empty*
    # extractor (GAME_MODE_PLAY's submit_guess never populates it) - this
    # uses GAME_MODE_SOLVE's get_guess_stats, which does, so the JSON
    # round-trip (dataclasses.asdict -> json.dumps, then json.loads ->
    # LetterExtractor(...)) actually gets exercised with real incl/excl data.
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')
    lang_launcher = helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)
    pre_computed = schemas.PrecomputedEntry(path=words_file, length=5, lang_launcher=lang_launcher)
    lang_source = schemas.LangSource(path=words_file, pre_computed={'5': pre_computed})
    conf = schemas.AppConfig.model_validate({
        'service_id': 'wordle-test', 'logging_level': 'INFO', 'data_folder': 'data/',
        'MAX_SESSIONS': 5, 'SESSION_TTL_SECONDS': 1800,
    })
    app_sources = schemas.AppSources(config=conf, langs={'mini': lang_source}, game_modes={})
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_SOLVE, max_tries=6)
    guess = next(word for word in lang_launcher.words if word != session.game.word)
    guess_str = ''.join(chr(letter + session.game.shift) for letter in guess)
    pattern = statics.pattern_to_emoji(computing.compute_pattern(guess=guess, word=session.game.word))
    _ = models.get_guess_stats(session, guess_str, pattern)

    assert session.game.letter_extractor.incl or session.game.letter_extractor.excl  # actually populated

    store.save(session)
    loaded = store.load(session.meta.session_uuid)

    assert loaded is not None
    assert loaded.game.letter_extractor == session.game.letter_extractor
    assert isinstance(loaded.game.letter_extractor, computing.LetterExtractor)

    store.close()


def test_load_missing_session_returns_none(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    assert store.load('does-not-exist') is None
    store.close()


def test_load_unavailable_language_returns_none(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)
    store.save(session)

    # Same store, but a different app_sources with no languages at all -
    # simulates the (lang, word_length) no longer being available.
    empty_sources = schemas.AppSources(config=app_sources.config, langs={}, game_modes={})
    store_without_lang = session_store.SessionStore(tmp_path / 'sessions.sqlite', empty_sources)

    assert store_without_lang.load(session.meta.session_uuid) is None
    store.close()
    store_without_lang.close()


def test_delete_removes_session(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)
    store.save(session)
    assert store.count() == 1

    store.delete(session.meta.session_uuid)

    assert store.count() == 0
    assert store.load(session.meta.session_uuid) is None
    store.close()


def test_delete_expired(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)
    session.meta.last_active_timestamp = int(time.time()) - 10000
    store.save(session)

    deleted = store.delete_expired(ttl_seconds=1800)

    assert deleted == 1
    assert store.count() == 0
    store.close()


def test_save_overwrites_existing_session(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    app_sources = _build_app_sources(tmp_path, mini_words_file)
    lang_launcher = app_sources.langs['mini'].pre_computed['5'].lang_launcher
    store = session_store.SessionStore(tmp_path / 'sessions.sqlite', app_sources)

    session = models.create_game_session('mini', 5, lang_launcher, statics.GameMode.GAME_MODE_PLAY, max_tries=6)
    store.save(session)

    session.meta.current_tries = 3
    session.meta.guesses = ['crane', 'slate']
    store.save(session)

    assert store.count() == 1
    loaded = store.load(session.meta.session_uuid)
    assert loaded is not None
    assert loaded.meta.current_tries == 3
    assert loaded.meta.guesses == ['crane', 'slate']
    store.close()
