#!/usr/bin/env python3
"""Tests for `autoWordle.modules.wordle`."""

#===================================================================================================
import pathlib

from autoWordle.modules import computing, helpers, statics, wordle

#===================================================================================================


def _build_launcher(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> helpers.LangLauncher:
    words_file = tmp_path / 'mini.txt'
    _ = words_file.write_text(mini_words_file.read_text(encoding='utf-8'), encoding='utf-8')
    return helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)


def test_submit_guess_rejects_invalid_word(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    assert game.submit_guess((1, 2, 3, 4, 5)) is None


def test_submit_guess_matches_reference_pattern(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    guess = next(word for word in launcher.words if word != game.word)
    pattern = game.submit_guess(guess)

    assert pattern == computing.compute_pattern(guess=guess, word=game.word)


def test_submit_guess_correct_word_is_all_exact(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    pattern = game.submit_guess(game.word)

    assert pattern == computing.compute_pattern(guess=game.word, word=game.word)


def test_submit_guess_and_pattern_narrows_pool_matches_brute_force(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    # Regression test for the get_couples_from_compendium -> get_matching_words
    # rewrite: the narrowed pool must match a brute-force filter over the
    # *original* pool exactly - no more, no less (the old code's dropped
    # `elif` branch could have spuriously kept extra, unrelated words).
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    original_pool = game.pool_words.copy()
    guess = next(word for word in launcher.words if word != game.word)
    pattern = computing.compute_pattern(guess=guess, word=game.word)

    result = game.submit_guess_and_pattern(guess, pattern)

    expected_pool = {word for word in original_pool if computing.compute_pattern(guess=guess, word=word) == pattern}
    assert game.pool_words == expected_pool
    assert game.word in game.pool_words
    assert result is not None
    assert {word for word, _ in result} == expected_pool


def test_submit_guess_and_pattern_rejects_invalid_word(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    assert game.submit_guess_and_pattern((1, 2, 3, 4, 5), (1, 1, 1, 1, 1)) is None


def test_submit_guess_and_pattern_rejects_invalid_pattern(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    guess = next(iter(launcher.words))
    assert game.submit_guess_and_pattern(guess, (9, 9, 9, 9, 9)) is None


def test_submit_guess_and_pattern_impossible_combo_empties_pool(tmp_path: pathlib.Path, mini_words_file: pathlib.Path) -> None:
    launcher = _build_launcher(tmp_path, mini_words_file)
    game = wordle.Wordle(launcher)

    guess = next(iter(launcher.words))
    # A pattern this guess never actually produces against any pool word -
    # guaranteed to exist since a 20-word pool produces at most 20 distinct
    # patterns out of 3**5 = 243 possible ones.
    produced_patterns = {computing.compute_pattern(guess=guess, word=word) for word in launcher.words}
    impossible_pattern = next(tuple(int(status) for status in candidate)
                             for candidate in statics.pattern_permutations(5)
                             if tuple(int(status) for status in candidate) not in produced_patterns)

    assert game.submit_guess_and_pattern(guess, impossible_pattern) is None
    assert game.pool_words == set()
