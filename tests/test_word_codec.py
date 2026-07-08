#!/usr/bin/env python3
"""Tests for `autoWordle.modules.word_codec`."""

#===================================================================================================
import pathlib

from autoWordle.modules import word_codec

#===================================================================================================

SHIFT = 87


def test_get_words_list_filters_by_length_and_normalizes(tmp_path: pathlib.Path) -> None:
    words_file = tmp_path / 'words.txt'
    # "Étude" accented/uppercase should normalize to "etude"; "abc" and
    # "toolong" should be filtered out by length; "not-a-word" by isalpha().
    _ = words_file.write_text('crane\nÉtude\nabc\ntoolong\nnot-a-word\n', encoding='utf-8')

    words = word_codec.get_words_list(words_file, 5, SHIFT)

    decoded = {''.join(chr(letter + SHIFT) for letter in word) for word in words}
    assert decoded == {'crane', 'etude'}


def test_get_words_list_missing_file_returns_empty(tmp_path: pathlib.Path) -> None:
    assert word_codec.get_words_list(tmp_path / 'missing.txt', 5, SHIFT) == set()


def test_tord_int_round_trip() -> None:
    word = tuple(ord(letter) - SHIFT for letter in 'crane')
    packed = word_codec.tord_to_int(word, 100)
    assert word_codec.tord_from_int(packed, len(word), 100) == word


def test_get_data_paths_naming_convention(tmp_path: pathlib.Path) -> None:
    words_file = tmp_path / 'wordle.txt'
    cache_file, words_information_file = word_codec.get_data_paths(words_file, 5)

    assert cache_file.name == 'wordle_5_compendium.sqlite'
    assert words_information_file.name == 'wordle_5_info.csv'
    assert cache_file.parent == tmp_path


def test_save_and_load_words_information_round_trip(tmp_path: pathlib.Path) -> None:
    words_information = [(tuple(ord(letter) - SHIFT for letter in 'crane'), 5.87321),
                         (tuple(ord(letter) - SHIFT for letter in 'slate'), 4.12345)]
    path = tmp_path / 'info.csv'

    word_codec.save_words_information(path, words_information, SHIFT)
    loaded = word_codec.load_words_information(path, SHIFT)

    assert loaded == words_information
