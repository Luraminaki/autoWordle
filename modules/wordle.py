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

#pylint: disable=wrong-import-position, wrong-import-order
from modules import statics, helpers, computing
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


class Wordle ():
    def __init__(self, language_launcher: helpers.LangLauncher) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        self.language_launcher = language_launcher

        print(f"{curr_func} -- Computing remaining information...")
        self.pool_words = set()
        self.information = 0.0
        self.word = tuple()
        self.letter_extractor = {"incl": {}, "excl": {}}

        self.reset()
        print(f"{curr_func} -- Remaining information is: {round(self.information, 2)} bit(s)")


    def _is_invalid_word(self, word: str) -> bool:
        return word == '' or len(word) != self.language_launcher.word_lenght or tuple(ord(letter) for letter in word) not in self.language_launcher.words


    def _is_invalid_pattern(self, pattern: str) -> bool:
        allowed = [str(entry.value) for entry in statics.StatusLetter]
        foreign_found = not all(eval in allowed for eval in set(pattern))

        return not pattern.isnumeric() or len(pattern) != self.language_launcher.word_lenght or foreign_found


    def reset(self) -> None:
        self.pool_words = self.language_launcher.words.copy()
        self.information = -computing.safe_log2(1.0/float(len(self.pool_words)))
        self.word = random.choice(list(self.pool_words))

        self.letter_extractor = {"incl": {}, "excl": {}}


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
        for pair_words in self.language_launcher.get_couples_from_compendium(pattern):
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
        pool_pattern_compendium = computing.build_pattern_compendium(self.pool_words)
        pool_words_information = computing.compute_words_information_faster(self.pool_words, pool_pattern_compendium)

        # print(f"{curr_func} -- Computing remaining information...")
        self.information = -computing.safe_log2(1.0/float(len(pool_words_information)))

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Found {len(self.pool_words)} matches in {round(tac, 2)} second(s)")
        print(f"{curr_func} -- Remaining information is {round(self.information, 2)}")

        return pool_words_information


    def submit_guess(self, guess: str) -> None | tuple | tuple[int]:
        curr_func = inspect.currentframe().f_code.co_name

        if self._is_invalid_word(guess):
            print(f"{curr_func} -- Word {guess} is not allowed")
            return None

        pattern = computing.compute_pattern(guess=tuple(ord(letter) for letter in guess), word=self.word)
        print(f"{curr_func} -- {guess}")
        print(f"{curr_func} -- {statics.pattern_to_emoji(pattern)}")

        return pattern
