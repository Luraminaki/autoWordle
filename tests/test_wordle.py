#!/usr/bin/env python3
"""Tests for `autoWordle.modules.wordle`."""

#===================================================================================================
import itertools
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


def test_best_guesses_escapes_same_family_trap(tmp_path: pathlib.Path) -> None:
    # Regression test for the full-dictionary entropy fallback: a pool of
    # same-family words (differ by one letter only) is indistinguishable from
    # pool-only guessing - every family member produces the identical pattern
    # against any other, so pool-only entropy can only eliminate one
    # candidate per guess. A word outside the family that tests several of
    # the differentiating letters at once should score much higher and get
    # picked instead. Confirmed via a real failure trace in a full 2315-game
    # self-play run (`wight`/`tight`/`night`/`might`/`fight`) - this is a
    # small, controlled reproduction of the same shape.
    words_file = tmp_path / 'family.txt'
    _ = words_file.write_text('aabbc\naabbd\naabbe\naabbf\nbcdea\nqqqqq\nxxxxx\nzzzzz\n', encoding='utf-8')
    launcher = helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)
    game = wordle.Wordle(launcher)

    shift = launcher.shift

    def enc(word: str) -> tuple[int, ...]:
        return tuple(ord(letter) - shift for letter in word)

    family = [enc(word) for word in ('aabbc', 'aabbd', 'aabbe', 'aabbf')]
    shared_pattern = computing.compute_pattern(guess=family[0], word=family[1])

    result = game.submit_guess_and_pattern(family[0], shared_pattern)

    assert result is not None
    assert len(game.pool_words) > 1  # still ambiguous - the actual trap scenario
    assert len(game.pool_words) <= 50  # within the fallback's size gate

    pool_only_best_entropy = max(entropy_value for _, entropy_value in result)
    best_guess, best_guess_entropy = game.best_guesses[0]

    assert best_guess == enc('bcdea')
    assert best_guess_entropy > pool_only_best_entropy


def test_best_guesses_falls_back_to_pool_above_size_threshold(tmp_path: pathlib.Path) -> None:
    # Above `wordle._FULL_SCAN_POOL_THRESHOLD`, best_guesses should just be
    # the pool-only ranking (the expensive full-dictionary scan is gated off).
    # Needs a bigger synthetic list than mini.txt (only 20 words) to clear the
    # threshold (50): generate 60 words from letters a-j, plus one guess word
    # made of entirely different letters (v-z) - since it shares no letters
    # with any of them, it produces an identical all-MISS pattern against
    # every one, so narrowing leaves the whole 60-word pool intact.
    words = [''.join(letters) for letters in itertools.islice(itertools.permutations('abcdefghij', 5), 60)]
    words_file = tmp_path / 'big.txt'
    _ = words_file.write_text('\n'.join([*words, 'vwxyz']), encoding='utf-8')
    launcher = helpers.LangLauncher(words_file, compute_best_opening=True, word_length=5)
    game = wordle.Wordle(launcher)

    assert len(game.pool_words) > wordle._FULL_SCAN_POOL_THRESHOLD  # pyright: ignore[reportPrivateUsage]

    shift = launcher.shift
    guess = tuple(ord(letter) - shift for letter in 'vwxyz')
    pattern = computing.compute_pattern(guess=guess, word=next(iter(game.pool_words)))
    result = game.submit_guess_and_pattern(guess, pattern)

    assert len(game.pool_words) > wordle._FULL_SCAN_POOL_THRESHOLD  # pyright: ignore[reportPrivateUsage]
    assert game.best_guesses == result
