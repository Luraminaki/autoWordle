#!/usr/bin/env python3
"""Tests for `autoWordle.modules.helpers`."""

#===================================================================================================
import pathlib

from autoWordle.modules import helpers

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
