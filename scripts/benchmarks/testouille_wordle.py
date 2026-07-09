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

from autoWordle.app import logging_utils
from autoWordle.modules import helpers, statics, wordle

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


def run_test(language_launcher: helpers.LangLauncher, word: tuple[int, ...],
             best_opening: bool, max_tries: int, cptr_games: int) -> int:
    guess, _, game = init_game(language_launcher, word, best_opening, cptr_games)
    win_p = tuple([statics.StatusLetter.EXACT.value] * len(word))

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

        if game.submit_guess_and_pattern(guess, pattern) is None:
            break

        # `best_guesses` already reflects the current pool - pool-only entropy
        # while it's still large, full-dictionary-vs-current-pool entropy once
        # it's small enough that a same-family cluster is plausible (see
        # `wordle._FULL_SCAN_POOL_THRESHOLD`).
        guess = game.best_guesses[0][0]
        cptr_tries = cptr_tries + 1

    return cptr_tries


def show_stats(nb_guesses: list[int], max_tries: int, cptr_games: int, tac: float) -> None:
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

    logger.info("END -- Played %d games in %s second(s) (%s second(s) / game)",
               cptr_games, round(tac, 2), round(round(tac, 2) / cptr_games, 2))
    logger.info("END -- Average tries is %s", round(sum(nb_guesses) / cptr_games, 2))
    logger.info("END -- Median tries is %s", median_guesses)
    logger.info("END -- (Min, Max) tries are (%d, %d)", min(nb_guesses), max(nb_guesses))
    logger.info("END -- %d Lucky guess (1st try)", nb_guesses.count(1))
    logger.info("END -- %d Game Over (More than %d tries)", failed_games, max_tries)


def main() -> None:
    file_path = 'data/wordle.txt'
    best_opening = True
    max_chars = 5
    max_tries = 6
    threads = 0

    language_launcher = helpers.LangLauncher(file_path, best_opening, max_chars, threads)
    max_games = 5  # len(language_launcher.words) # 0 and 1 are forbidden !

    if max_games <= 1:
        logger.error("ABORTING -- Not enough max_games: %d (Must be greater than 1)", max_games)
        return

    nb_guesses: list[int] = []

    tic = time.perf_counter()

    cptr_games = 0
    for word in language_launcher.words:

        cptr_tries = run_test(language_launcher, word, best_opening, max_tries, cptr_games)

        if cptr_tries == max_tries:
            logger.warning("FAIL -- autoWordle failed to find a solution in %d (or less) attempts", max_tries)

        logger.info('##############################################################')

        nb_guesses.append(cptr_tries + 1)

        cptr_games = cptr_games + 1

        if cptr_games == max_games:
            break

    tac = time.perf_counter() - tic

    show_stats(nb_guesses, max_tries, cptr_games, tac)


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
