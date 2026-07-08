#!/usr/bin/env python3
"""Tests for `autoWordle.modules.helpers`."""

#===================================================================================================
import pathlib

from autoWordle.modules import computing, helpers

#===================================================================================================


def test_init_lang_app_data_always_builds_default_word_length(tmp_path: pathlib.Path) -> None:
    lang_file = tmp_path / 'mini.txt'
    _ = lang_file.write_text('crane\nslate\nadieu\nhouse\nmouse\n', encoding='utf-8')

    # No exhaustive marker files at all - this must still produce a bare
    # LangLauncher for the default word length (regression test for the
    # "fresh install never builds anything" bug).
    app_sources = helpers.init_lang_app_data([lang_file], [], default_word_lengths=[5], compute_best_opening=False)

    assert 'mini' in app_sources
    pre_computed = app_sources['mini']['pre_computed']
    assert '5' in pre_computed

    lang_launcher = pre_computed['5']['lang_launcher']
    assert isinstance(lang_launcher, helpers.LangLauncher)
    assert lang_launcher.words_information == []
    assert lang_launcher.cache is None


def test_init_lang_app_data_client_view_has_no_live_objects(tmp_path: pathlib.Path) -> None:
    lang_file = tmp_path / 'mini.txt'
    _ = lang_file.write_text('crane\nslate\nadieu\nhouse\nmouse\n', encoding='utf-8')

    app_sources = helpers.init_lang_app_data([lang_file], [], default_word_lengths=[5], client=True)

    pre_computed = app_sources['mini']['pre_computed']['5']
    assert pre_computed['lang_launcher'] == 'LangLauncher'
    assert isinstance(pre_computed['path'], str)


def test_get_matching_words_matches_brute_force_reference(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Regression test for the get_couples_from_compendium -> get_matching_words
    # rewrite: results must match brute-force `computing.compute_pattern`
    # exactly, including *excluding* words that only coincidentally equal
    # `guess` as some other guess's recorded target (the old code's `elif
    # cand_02 == guess` branch would have spuriously included those).
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')

    lang_launcher = helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)
    shift = lang_launcher.shift

    guess = tuple(ord(c) - shift for c in 'crane')
    target = tuple(ord(c) - shift for c in 'grape')
    pattern = computing.compute_pattern(guess=guess, word=target)

    matches = lang_launcher.get_matching_words(guess, pattern)
    expected = {word for word in lang_launcher.words if computing.compute_pattern(guess=guess, word=word) == pattern}

    assert matches == expected
    assert target in matches


def test_get_matching_words_without_cache_returns_empty(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')

    lang_launcher = helpers.LangLauncher(words_file, compute_best_opening=False, word_length=5)
    assert lang_launcher.cache is None

    guess = tuple(ord(c) - lang_launcher.shift for c in 'crane')
    assert lang_launcher.get_matching_words(guess, (1, 1, 1, 1, 1)) == set()
