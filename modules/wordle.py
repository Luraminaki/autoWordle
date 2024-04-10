#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 02 10:20:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import time
import inspect

import random

from copy import deepcopy

#pylint: disable=wrong-import-position, wrong-import-order
import helpers
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


class Wordle ():
    def __init__(self, language_launcher: helpers.LangLauncher) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        self.language_launcher = language_launcher

        print(f"{curr_func} -- Computing remaining information...")
        self.pool_words = deepcopy(self.language_launcher.words)
        self.information = -helpers.safe_log2(1.0/float(len(self.pool_words)))
        self.word = random.choice(list(self.pool_words))

        print(f"{curr_func} -- Remaining information is: {round(self.information, 2)} bit(s)")


    def _is_invalid_word(self, word: str) -> bool:
        return word == '' or len(word) != self.language_launcher.word_lenght or tuple(ord(letter) for letter in word) not in self.language_launcher.words


    def _is_invalid_pattern(self, pattern: str) -> bool:
        allowed = [str(helpers.MISS), str(helpers.MISPLACED), str(helpers.EXACT)]
        foreign_found = not all(eval in allowed for eval in set(pattern))

        return not pattern.isnumeric() or len(pattern) != self.language_launcher.word_lenght or foreign_found


    def submit_guess_and_pattern(self, guess: str, pattern: str) -> None | list | list[tuple[tuple[int], float]]:
        curr_func = inspect.currentframe().f_code.co_name

        if self._is_invalid_word(guess):
            print(f"{curr_func} -- Word {guess} is not allowed")
            return None

        if self._is_invalid_pattern(pattern):
            print(f"{curr_func} -- Pattern {pattern} is not allowed")
            return None

        t_guess = tuple(ord(letter) for letter in guess)

        tic = time.perf_counter()

        if not self.pool_words:
            print(f"{curr_func} -- Pool words is empty")
            return None

        # print(f"{curr_func} -- Finding possible matches...")
        pool_words: set[tuple[int]] = set()
        for pair_words in self.language_launcher.pattern_compendium.get(pattern, {}):
            try:
                conj = int(not bool(pair_words.index(t_guess)))
                pool_words.add(pair_words[conj])
            except:
                pass
        self.pool_words = self.pool_words.intersection(pool_words)

        if not self.pool_words:
            print(f"{curr_func} -- Pool words is empty")
            return None

        # print(f"{curr_func} -- Computing matches information...")
        pool_words_information = helpers.compute_words_information_faster(self.pool_words)

        # print(f"{curr_func} -- Computing remaining information...")
        self.information = -helpers.safe_log2(1.0/float(len(pool_words_information)))

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Found {len(self.pool_words)} matches in {round(tac, 2)} second(s)")
        print(f"{curr_func} -- Remaining information is {round(self.information, 2)}")

        return pool_words_information


    def submit_guess(self, guess: str) -> None | tuple | tuple[int]:
        curr_func = inspect.currentframe().f_code.co_name

        if self._is_invalid_word(guess):
            print(f"{curr_func} -- Word {guess} is not allowed")
            return None

        pattern = helpers.compute_pattern(guess=tuple(ord(letter) for letter in guess), word=self.word)
        print(f"{curr_func} -- {guess}")
        print(f"{curr_func} -- {helpers.pattern_to_emoji(pattern)}")

        return pattern


def main() -> None:
    curr_func = inspect.currentframe().f_code.co_name

    file_path = "../data/fr.txt"
    best_opening = False
    max_chars = 5
    max_tries = 6
    threads = 0

    language_launcher = helpers.LangLauncher(file_path, best_opening, max_chars, max_tries, threads)
    nb_guesses: list[int] = []

    cptr_games = 0
    for word in language_launcher.words:
        game = Wordle(language_launcher)
        game.word = word

        print(f"{curr_func} -- Starting game n°{cptr_games + 1}")
        print(f"{curr_func} -- Word to guess is: {''.join(chr(ord_letter) for ord_letter in game.word)}")

        if best_opening:
            guess = "".join(chr(ord_letter) for ord_letter in game.language_launcher.words_information[0][0])
        guess = "aires" # "".join(chr(ord_letter) for ord_letter in random.choice(list(game.words)))
        pattern = tuple([helpers.MISS]*max_chars)

        cptr_tries = 0
        while cptr_tries < max_tries*2:
            print(f"{curr_func} -- Attempt n° {cptr_tries + 1} -- Trying word: {guess}")

            pattern = game.submit_guess(guess)
            if pattern == tuple([helpers.EXACT]*max_chars):
                break

            pool = game.submit_guess_and_pattern(guess, ''.join(str(p) for p in pattern))
            if pool is None:
                break

            guess = "".join(chr(ord_letter) for ord_letter in pool[0][0])

            cptr_tries = cptr_tries + 1

        if cptr_tries == max_tries:
            print(f"{curr_func} -- FAIL -- autoWordle failed to find a solution in {max_tries} (or less) attemps")

        print("##############################################################")
        nb_guesses.append(cptr_tries + 1)
        cptr_games = cptr_games + 1

    nb_guesses.sort()
    median = nb_guesses[cptr_games // 2] if cptr_games % 2 == 0 else (nb_guesses[cptr_games // 2] + nb_guesses[(cptr_games // 2) + 1]) / 2
    failed_games = 0
    for over_try in range(max_tries + 1, (max_tries*2) + 1, 1):
        try:
            idx = nb_guesses.index(over_try)
            failed_games = len(nb_guesses[idx:])
            break
        except:
            continue

    print(f"{curr_func} -- END -- Played {cptr_games} games")
    print(f"{curr_func} -- END -- Average tries is {round(sum(nb_guesses) / cptr_games, 2)}")
    print(f"{curr_func} -- END -- Median tries is {median}")
    print(f"{curr_func} -- END -- (Min, Max) tries are ({min(nb_guesses)}, {max(nb_guesses)})")
    print(f"{curr_func} -- END -- {nb_guesses.count(1)} Lucky guess")
    print(f"{curr_func} -- END -- {failed_games} Game Over")

if __name__ == "__main__":
    main()
