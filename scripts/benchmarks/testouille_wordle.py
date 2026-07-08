#!/usr/bin/env python3
"""Manual self-play benchmark harness: plays autoWordle against itself and reports win-rate stats.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import logging
import pathlib
import random
import time
from collections.abc import Callable

from autoWordle.app import logging_utils
from autoWordle.modules import computing, helpers, statics, wordle

#===================================================================================================

logger = logging.getLogger(__name__)


def init_game(language_launcher: helpers.LangLauncher, word: tuple[int, ...],
             best_opening: bool, cptr_games: int) -> tuple[tuple[int, ...], tuple[int, ...], wordle.Wordle]:
    game = wordle.Wordle(language_launcher)
    game.word = word

    word_str = ''.join(chr(ord_letter + game.shift) for ord_letter in game.word)
    logger.info("Starting game n°%d", cptr_games + 1)
    logger.info("Word to guess is: %s", word_str)

    guess = random.choice(list(game.language_launcher.words))
    if best_opening:
        guess = game.language_launcher.words_information[0][0]

    pattern = tuple([statics.StatusLetter.MISS.value] * len(word))

    return guess, pattern, game


def crutch_suggestion(game: wordle.Wordle, pool: list[tuple[tuple[int, ...], float]],
                      letter_extractor: dict[str, dict[int, int]]) -> tuple[list[tuple[int, ...]], int]:
    pool_letters, pool_letters_dupes = computing.gather_pool_letters(pool)
    suggestions = computing.build_suggestion(game.language_launcher.words_information,
                                             pool_letters,
                                             pool_letters_dupes,
                                             letter_extractor)

    logger.info("Found %d different letters to try with %d dupes", len(pool_letters), len(pool_letters_dupes))

    # `found_rank` (not `sugg_rank` reused as the loop variable) is the real
    # sentinel here: the loop variable gets reassigned every iteration
    # regardless of whether a rank actually had suggestions, so relying on it
    # to still read -1 after a loop that never broke was a bug - it reads
    # whatever the last iterated (lowest) rank was instead.
    found_rank = -1
    best_bucket: computing.WordsInformation | None = None

    for candidate_rank in range(game.language_launcher.word_length - 1, -1, -1):
        bucket = suggestions[candidate_rank]

        if bucket:
            found_rank = candidate_rank
            best_bucket = bucket
            logger.info("Rank %d has %d suggestions", candidate_rank, len(bucket))
            break

    sugg_guesses = [sugg[0] for sugg in best_bucket] if best_bucket is not None else []

    return sugg_guesses, found_rank


def crutch_guess(game: wordle.Wordle, pool: list[tuple[tuple[int, ...], float]],
                 pattern: tuple[int, ...],
                 sugg_guesses: list[tuple[int, ...]], sugg_rank: int) -> tuple[tuple[int, ...], bool]:
    suggestion_used = False
    thresh_sugg = (game.language_launcher.word_length % 2) + game.language_launcher.word_length // 2

    if len(pool) <= 2:
        guess = pool[0][0]

    elif (len(pool) > 2
          and sugg_rank > game.language_launcher.word_length - thresh_sugg
          and pattern.count(statics.StatusLetter.EXACT.value) >= thresh_sugg):
        guess = sugg_guesses[0]

        guess_str = ''.join(chr(ord_letter) for ord_letter in guess)
        logger.info("⚠️  Using suggestion '%s' on next attempt ⚠️", guess_str)

        suggestion_used = True

    else:
        guess = pool[0][0]

    return guess, suggestion_used


def fast_test(game: wordle.Wordle, pool: list[tuple[tuple[int, ...], float]],
              pattern: tuple[int, ...], guess: tuple[int, ...],
              letter_extractor: dict[str, dict[int, int]]) -> tuple[tuple[int, ...], bool]:
    """Far from being the best solver, but somewhat OK speed wise..."""
    letter_extractor = computing.update_letter_extractor(letter_extractor,
                                                         computing.build_letter_extractor(guess, pattern))

    # `crutch_suggestion` scans the *entire* word list (not just `pool`) to
    # build its suggestion - only worth paying for when `crutch_guess` could
    # actually end up using the result. Checking the part of that condition
    # that doesn't depend on `crutch_suggestion`'s own output first (see
    # `crutch_guess`) skips that scan whenever it wouldn't be used anyway -
    # observed to be ~90% of guesses in practice.
    thresh_sugg = (game.language_launcher.word_length % 2) + game.language_launcher.word_length // 2

    if len(pool) > 2 and pattern.count(statics.StatusLetter.EXACT.value) >= thresh_sugg:
        sugg_guesses, sugg_rank = crutch_suggestion(game, pool, letter_extractor)
        return crutch_guess(game, pool, pattern, sugg_guesses, sugg_rank)

    return pool[0][0], False


def run_test(language_launcher: helpers.LangLauncher, word: tuple[int, ...],
            best_opening: bool, max_tries: int,
            cptr_games: int, func_test: Callable) -> tuple[int, int]:
    guess, _, game = init_game(language_launcher, word, best_opening, cptr_games)
    win_p = tuple([statics.StatusLetter.EXACT.value] * len(word))
    letter_extractor = {'incl': {}, 'excl': {}}

    cptr_suggestion_used = 0
    cptr_tries = 0

    while cptr_tries < max_tries * 2:
        logger.info('-------------------------------------------------------------')
        guess_str = ''.join(chr(ord_letter + game.shift) for ord_letter in guess)
        logger.info("Attempt n° %d -- Trying word: %s -- %d/%d",
                   cptr_tries + 1, guess_str, len(game.pool_words), len(language_launcher.words))

        if ((pattern := game.submit_guess(guess)) == win_p
            or not pattern
            or pattern is None):
            break

        if (pool := game.submit_guess_and_pattern(guess, pattern)) is None:
            break

        guess, suggestion_used = func_test(game, pool, pattern, guess, letter_extractor)

        if suggestion_used:
            cptr_suggestion_used = cptr_suggestion_used + 1

        cptr_tries = cptr_tries + 1

    return cptr_tries, cptr_suggestion_used


def show_stats(nb_suggestion_used: list[int], nb_guesses: list[int],
              max_games: int, max_tries: int, cptr_games: int, tac: float) -> None:
    nb_guesses.sort()
    mid = cptr_games // 2
    median_guesses = nb_guesses[mid] if cptr_games % 2 == 0 else (nb_guesses[mid] + nb_guesses[mid + 1]) / 2
    failed_games = 0

    for over_try in range(max_tries + 1, (max_tries * 2) + 1, 1):
        try:
            idx = nb_guesses.index(over_try)
            failed_games = len(nb_guesses[idx:])
            break
        except ValueError:
            continue

    nb_suggestion_used.sort()
    median_suggestion_used = (nb_suggestion_used[mid] if cptr_games % 2 == 0
                             else (nb_suggestion_used[mid] + nb_suggestion_used[mid + 1]) / 2)
    game_where_sugg_used = max_games - nb_suggestion_used.count(0)

    logger.info("END -- Played %d games in %s second(s) (%s second(s) / game)",
               cptr_games, round(tac, 2), round(round(tac, 2) / cptr_games, 2))
    logger.info("END -- Average tries is %s", round(sum(nb_guesses) / cptr_games, 2))
    logger.info("END -- Median tries is %s", median_guesses)
    logger.info("END -- (Min, Max) tries are (%d, %d)", min(nb_guesses), max(nb_guesses))
    logger.info("END -- %d Lucky guess (1st try)", nb_guesses.count(1))
    logger.info("END -- %d Game Over (More than %d tries)", failed_games, max_tries)

    logger.info("END -- Average crutch suggestion use is %s", round(sum(nb_suggestion_used) / cptr_games, 2))
    logger.info("END -- Median crutch suggestion use is %s", median_suggestion_used)
    logger.info("END -- Crutch suggestion used in %d game(s)", game_where_sugg_used)


def main() -> None:
    file_path = 'data/wordle.txt'
    best_opening = True
    max_chars = 5
    max_tries = 6
    threads = 0

    func_test = fast_test

    language_launcher = helpers.LangLauncher(file_path, best_opening, max_chars, threads)
    max_games = 5  # len(language_launcher.words) # 0 and 1 are forbidden !

    if max_games <= 1:
        logger.error("ABORTING -- Not enough max_games: %d (Must be greater than 1)", max_games)
        return

    nb_guesses: list[int] = []
    nb_suggestion_used: list[int] = []

    tic = time.perf_counter()

    cptr_games = 0
    for word in language_launcher.words:

        cptr_tries, cptr_suggestion_used = run_test(language_launcher, word, best_opening, max_tries, cptr_games, func_test)

        if cptr_tries == max_tries:
            logger.warning("FAIL -- autoWordle failed to find a solution in %d (or less) attempts", max_tries)

        logger.info('##############################################################')

        nb_guesses.append(cptr_tries + 1)
        nb_suggestion_used.append(cptr_suggestion_used)

        cptr_games = cptr_games + 1

        if cptr_games == max_games:
            break

    tac = time.perf_counter() - tic

    show_stats(nb_suggestion_used, nb_guesses, max_games, max_tries, cptr_games, tac)


if __name__ == '__main__':
    logging_utils.configure_logging(log_file_stem=pathlib.Path(__file__).stem)
    main()
    # import cProfile
    # cProfile.runctx('main()',
    #                 globals=globals(), locals=locals(),
    #                 filename=pathlib.Path(f"{pathlib.Path(__file__).stem}.prof").as_posix())


# To run with PyPy
# - Download PyPy https://www.pypy.org/
# - Run `pypy -m ensurepip`
# - Run `pypy -m pip install unidecode`
# - Run `pypy -m scripts.benchmarks.testouille_wordle`
