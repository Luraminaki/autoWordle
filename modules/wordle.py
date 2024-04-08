#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 20 10:20:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import time
import inspect
import pathlib

import random

from copy import deepcopy
from multiprocessing import Process

#pylint: disable=wrong-import-position, wrong-import-order
import helpers
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


class Wordle ():
    def __init__(self, words_path: str, word_lenght: int=5, tries: int=6, threads: int=0) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        tic = time.perf_counter()

        self.word_lenght = word_lenght
        self.tries = tries
        self.threads = threads

        print(f"{curr_func} -- Acquiring file {words_path}...")
        words_file = pathlib.Path(words_path).expanduser()

        print(f"{curr_func} -- Building word list...")
        self.words = helpers.get_words_list(words_file, self.word_lenght)
        if not self.words:
            raise ValueError
        print(f"{curr_func} -- Found {len(self.words)} words...")

        # self.words_information: list | list[tuple[str, float]] = self._compute_words_information(self.words)
        self.pool_words = deepcopy(self.words)

        print(f"{curr_func} -- Computing remaining information...")
        self.information = -helpers.safe_log2(1.0/float(len(self.words)))
        self.word = random.choice(list(self.words))

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Session initialised in {tac} second(s) \
                \n\tWord to guess is: {''.join(chr(ord_letter) for ord_letter in self.word)} \
                \n\tRemaining information is: {self.information} bit(s)")


    def _compute_words_information(self, pool_words: set[tuple[int]]) -> list | list[tuple[str, float]]:
        curr_func = inspect.currentframe().f_code.co_name

        words_information: list | list[tuple[str, float]] = []
        pool_words_chunked, return_dict_entropy, jobs = helpers.prepare_worker_datas(pool_words, self.threads)

        for pool_words_chunk in pool_words_chunked:
            jobs.append(Process(target=helpers.compute_word_entropy_worker,
                                args=(set(pool_words_chunk), pool_words, return_dict_entropy)))
            jobs[-1].start()

        for process in jobs:
            process.join()

        try:
            words_information = sorted(return_dict_entropy.items(), key=lambda x : x[1], reverse=True)

        except Exception as err:
            print(f"{curr_func} -- Something went wrong: {repr(err)}")

        return words_information



    def _is_invalid_word(self, word: str) -> bool:
        return word == '' or len(word) != self.word_lenght or tuple(ord(letter) for letter in word) not in self.words


    def _is_invalid_pattern(self, pattern: str) -> bool:
        allowed = [str(helpers.MISS), str(helpers.MISPLACED), str(helpers.EXACT)]
        foreign_found = not all(eval in allowed for eval in set(pattern))

        return not pattern.isnumeric() or len(pattern) != self.word_lenght or foreign_found


    def submit_guess_and_pattern(self, guess: str, pattern: str) -> None | list | list[tuple[str, float]]:
        curr_func = inspect.currentframe().f_code.co_name

        if self._is_invalid_word(guess):
            print(f"{curr_func} -- Word {guess} is not allowed")
            return None

        if self._is_invalid_pattern(pattern):
            print(f"{curr_func} -- Pattern {pattern} is not allowed")
            return None

        t_guess = tuple(ord(letter) for letter in guess)
        t_pattern = tuple(int(p) for p in pattern)

        tic = time.perf_counter()

        if not self.pool_words:
            print(f"{curr_func} -- Pool words is empty")
            return None

        # print(f"{curr_func} -- Finding possible matches...")
        self.pool_words = helpers.find_possible_matches(t_guess, self.pool_words, t_pattern)

        if not self.pool_words:
            print(f"{curr_func} -- Pool words is empty")
            return None

        # print(f"{curr_func} -- Computing matches information...")
        pool_words_information = self._compute_words_information(self.pool_words)

        # print(f"{curr_func} -- Computing remaining information...")
        self.information = -helpers.safe_log2(1.0/float(len(pool_words_information)))

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Found {len(self.pool_words)} matches in {tac} second(s)")
        print(f"{curr_func} -- Remaining information is {self.information}")

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
    max_chars = 5
    max_tries = 6
    threads = 1

    game = Wordle(file_path, max_chars, max_tries, threads)
    guess = "".join(chr(ord_letter) for ord_letter in random.choice(list(game.words)))
    pattern = tuple([helpers.MISS]*max_chars)

    nb_tries = 0
    while nb_tries < max_tries:
        time.sleep(1)
        print(f"{curr_func} -- Attempt n° {nb_tries + 1} -- Trying word: {guess}")

        pattern = game.submit_guess(guess)
        if pattern == tuple([helpers.EXACT]*max_chars):
            break

        pool = game.submit_guess_and_pattern(guess, ''.join(str(p) for p in pattern))
        if pool is None:
            break

        guess = "".join(chr(ord_letter) for ord_letter in pool[-1][0])

        nb_tries = nb_tries + 1

    if nb_tries == max_tries:
        print(f"{curr_func} -- FAIL -- autoWordle failed to find a solution in {max_tries} (or less) attemps")


if __name__ == "__main__":
    main()
