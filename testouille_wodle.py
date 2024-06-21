#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 15 15:10:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect

import time
import random

#pylint: disable=wrong-import-position, wrong-import-order
from modules import statics, helpers, computing, wordle
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def init_game(language_launcher: helpers.LangLauncher, word: tuple[int],
              best_opening: bool, cptr_games: int) -> tuple[str, tuple[int], wordle.Wordle]:
    curr_func = inspect.currentframe().f_code.co_name

    game = wordle.Wordle(language_launcher)
    game.word = word

    print(f"{curr_func} -- Starting game n°{cptr_games + 1}")
    print(f"{curr_func} -- Word to guess is: {''.join(chr(ord_letter) for ord_letter in game.word)}")

    guess = "".join(chr(ord_letter) for ord_letter in random.choice(list(game.language_launcher.words)))
    if best_opening:
        guess = "".join(chr(ord_letter) for ord_letter in game.language_launcher.words_information[0][0])

    pattern = tuple([statics.StatusLetter.MISS.value]*len(word))

    return guess, pattern, game


def crutch_suggestion(game: wordle.Wordle, pool: list[tuple[tuple[int], float]],
                      letter_extractor: dict[str, dict[str, int]]) -> tuple[list[str], int]:
    curr_func = inspect.currentframe().f_code.co_name

    pool_letters, pool_letters_dupes = computing.gather_pool_letters(pool)
    suggestions = computing.build_suggestion(game.language_launcher.words_information,
                                             pool_letters,
                                             pool_letters_dupes,
                                             letter_extractor)

    print(f"{curr_func} -- Found {len(pool_letters)} different letters to try with {len(pool_letters_dupes)} dupes")

    for sugg_rank in range(game.language_launcher.word_lenght - 1, 0 - 1, -1):
        if suggestions[sugg_rank] is not None:
            if len(suggestions[sugg_rank]) > 0:
                print(f"{curr_func} -- Rank {sugg_rank} has {len(suggestions[sugg_rank])} suggestions")
                break

    sugg_guesses = ["".join(chr(letter) for letter in sugg[0]) for sugg in suggestions[sugg_rank]]
    # print(f"{curr_func} -- Suggestion are {sugg_guesses}")

    return sugg_guesses, sugg_rank


def crutch_guess(game: wordle.Wordle, pool: list[tuple[tuple[int], float]],
                 pattern: tuple[int],
                 sugg_guesses: list[str], sugg_rank: int) -> tuple[str, bool]:
    curr_func = inspect.currentframe().f_code.co_name

    suggestion_used = False
    thresh_sugg = (game.language_launcher.word_lenght % 2) + game.language_launcher.word_lenght // 2

    if len(pool) <= 2:
        guess = "".join(chr(ord_letter) for ord_letter in pool[0][0])

    elif len(pool) > 2 and \
    sugg_rank > game.language_launcher.word_lenght - thresh_sugg and \
    pattern.count(statics.StatusLetter.EXACT.value) >= thresh_sugg:
        guess = sugg_guesses[0]

        print(f"{curr_func} -- ⚠️  Using suggestion '{guess}' on next attemp ⚠️")

        suggestion_used = True

    else:
        guess = "".join(chr(ord_letter) for ord_letter in pool[0][0])

    return guess, suggestion_used


def fast_test(game: wordle.Wordle, pool: list[tuple[tuple[int], float]],
              pattern: tuple[int], guess: str,
              letter_extractor: dict[str, dict[str, int]]) -> tuple[str, bool]:
    # Far from being the best solver, but somewhat OK speed wise...

    letter_extractor = computing.update_letter_extractor(letter_extractor,
                                                         computing.build_letter_extractor(tuple(ord(letter) for letter in guess),
                                                                                          pattern))
    sugg_guesses, sugg_rank = crutch_suggestion(game, pool, letter_extractor)

    return crutch_guess(game, pool, pattern, sugg_guesses, sugg_rank)


def slow_test(game: wordle.Wordle, pool: list[tuple[tuple[int], float]],
              pattern: tuple[int], guess: str,
              letter_extractor: dict[str, dict[str, int]]) -> tuple[str, bool]:
    # As the name implies, it's a lot slower and cumputing intensive... Especially if ran in a single thread...

    words = [word_ord for word_ord, _ in pool]
    pattern_compendium = computing.build_pattern_compendium(words)
    updated_pool = computing.compute_words_information_faster(words, pattern_compendium, game.language_launcher.threads)

    return fast_test(game, updated_pool, pattern, guess, letter_extractor)


def run_test(language_launcher: helpers.LangLauncher, word: tuple[int],
             best_opening: bool, max_tries: int,
             cptr_games: int, func_test: callable) -> tuple[int]:
    curr_func = inspect.currentframe().f_code.co_name

    guess, pattern, game = init_game(language_launcher, word, best_opening, cptr_games)
    letter_extractor = {"incl": {}, "excl": {}}

    cptr_suggestion_used = 0
    cptr_tries = 0
    while cptr_tries < max_tries*2:
        print("-------------------------------------------------------------")
        print(f"{curr_func} -- Attempt n° {cptr_tries + 1} -- Trying word: {guess} -- {len(game.pool_words)}/{len(language_launcher.words)}")

        pattern = game.submit_guess(guess)
        if pattern == tuple([statics.StatusLetter.EXACT.value]*len(word)):
            break

        pool = game.submit_guess_and_pattern(guess, ''.join(str(p) for p in pattern))
        if pool is None:
            break

        guess, suggestion_used  = func_test(game, pool, pattern, guess, letter_extractor)

        if suggestion_used:
            cptr_suggestion_used = cptr_suggestion_used + 1

        cptr_tries = cptr_tries + 1

    return cptr_tries, cptr_suggestion_used


def show_stats(nb_suggestion_used: list[int], nb_guesses: list[int],
               max_games: int, max_tries: int, cptr_games: int, tac: float):
    curr_func = inspect.currentframe().f_code.co_name

    nb_guesses.sort()
    median_guesses = nb_guesses[cptr_games // 2] if cptr_games % 2 == 0 else (nb_guesses[cptr_games // 2] + nb_guesses[(cptr_games // 2) + 1]) / 2
    failed_games = 0

    for over_try in range(max_tries + 1, (max_tries*2) + 1, 1):
        try:
            idx = nb_guesses.index(over_try)
            failed_games = len(nb_guesses[idx:])
            break
        except:
            continue

    nb_suggestion_used.sort()
    median_suggestion_used = nb_suggestion_used[cptr_games // 2] if cptr_games % 2 == 0 else (nb_suggestion_used[cptr_games // 2] + nb_suggestion_used[(cptr_games // 2) + 1]) / 2
    game_where_sugg_used = max_games - nb_suggestion_used.count(0)

    print(f"{curr_func} -- END -- Played {cptr_games} games in {round(tac, 2)} second(s) ({round(round(tac, 2)/cptr_games, 2)} second(s) / game)")
    print(f"{curr_func} -- END -- Average tries is {round(sum(nb_guesses) / cptr_games, 2)}")
    print(f"{curr_func} -- END -- Median tries is {median_guesses}")
    print(f"{curr_func} -- END -- (Min, Max) tries are ({min(nb_guesses)}, {max(nb_guesses)})")
    print(f"{curr_func} -- END -- {nb_guesses.count(1)} Lucky guess (1st try)")
    print(f"{curr_func} -- END -- {failed_games} Game Over (More than {max_tries} tries)")

    print(f"{curr_func} -- END -- Average crutch suggestion use is {round(sum(nb_suggestion_used) / cptr_games, 2)}")
    print(f"{curr_func} -- END -- Median crutch suggestion use is {median_suggestion_used}")
    print(f"{curr_func} -- END -- Crutch suggestion used in {game_where_sugg_used} game(s)")


def main() -> None:
    curr_func = inspect.currentframe().f_code.co_name

    file_path = "data/wordle.txt"
    best_opening = True
    max_chars = 5
    max_tries = 6
    threads = 0

    func_test = fast_test
    # func_test = slow_test

    language_launcher = helpers.LangLauncher(file_path, best_opening, max_chars, threads)
    max_games = len(language_launcher.words) # 0 and 1 are forbidden !
    nb_guesses: list[int] = []
    nb_suggestion_used: list[int] = []

    tic = time.perf_counter()

    cptr_games = 0
    for word in language_launcher.words:

        cptr_tries, cptr_suggestion_used = run_test(language_launcher, word, best_opening, max_tries, cptr_games, func_test)

        if cptr_tries == max_tries:
            print(f"{curr_func} -- FAIL -- autoWordle failed to find a solution in {max_tries} (or less) attemps")

        print("##############################################################")

        nb_guesses.append(cptr_tries + 1)
        nb_suggestion_used.append(cptr_suggestion_used)

        cptr_games = cptr_games + 1

        if cptr_games == max_games:
            break

    tac = time.perf_counter() - tic

    show_stats(nb_suggestion_used, nb_guesses, max_games, max_tries, cptr_games, tac)


if __name__ == "__main__":
    main()


# 11th Gen Intel Core i7-1165G7 + SSD Samsung 990 Pro + 24Go RAM

# Test sample: wordle.txt

# SLOW : (Max RAM ~350Mo, Avg RAM ~100Mo)
# show_stats -- END -- Played 2315 games in 11926.9 second(s) (5.15 second(s) / game)
# show_stats -- END -- Average tries is 3.74
# show_stats -- END -- Median tries is 4.0
# show_stats -- END -- (Min, Max) tries are (1, 7)
# show_stats -- END -- 1 Lucky guess (1st try)
# show_stats -- END -- 1 Game Over (More than 6 tries)
# show_stats -- END -- Average crutch suggestion use is 0.11
# show_stats -- END -- Median crutch suggestion use is 0.0
# show_stats -- END -- Crutch suggestion used in 260 game(s)

# FAST : (Max RAM ~350Mo, Avg RAM ~100Mo)
# show_stats -- END -- Played 2315 games in 7121.98 second(s) (3.08 second(s) / game)
# show_stats -- END -- Average tries is 3.74
# show_stats -- END -- Median tries is 4.0
# show_stats -- END -- (Min, Max) tries are (1, 7)
# show_stats -- END -- 1 Lucky guess (1st try)
# show_stats -- END -- 1 Game Over (More than 6 tries)
# show_stats -- END -- Average crutch suggestion use is 0.11
# show_stats -- END -- Median crutch suggestion use is 0.0
# show_stats -- END -- Crutch suggestion used in 259 game(s)
