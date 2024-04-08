#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jan 20 10:20:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect
import pathlib

import math

import itertools as it
from multiprocessing import Process, managers, Manager, cpu_count

import unidecode

#pylint: disable=wrong-import-position, wrong-import-order

#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


MISS = 0
MISPLACED = 1
EXACT = 2


def get_words_list(path: pathlib.Path, word_lenght: int=5) -> set | set[tuple[int]]:
    curr_func = inspect.currentframe().f_code.co_name

    words = set()

    if not path.is_file():
        print(f"{curr_func} -- Invalid path for file {path}")
        return words

    with path.open('r', encoding='utf-8') as fp:
        for word in fp.readlines():
            word = unidecode.unidecode(word.strip()).lower()
            if (len(word) == word_lenght and word.isalpha()):
                words.add(tuple(ord(letter) for letter in word))

    return words


def compute_pattern(guess: tuple[int], word: tuple[int]) -> tuple | tuple[int]:
    pattern = [MISS] * len(word)
    temp_guess = list(guess)

    for w_cptr, w_letter in enumerate(word):
        if w_letter == guess[w_cptr]:
            pattern[w_cptr] = EXACT
            temp_guess[w_cptr] = -1

        else:
            if temp_guess.count(w_letter) == 0:
                continue

            idx = temp_guess.index(w_letter)
            pattern[idx] = MISPLACED
            temp_guess[idx] = -1

    return tuple(pattern)


def pattern_to_emoji(pattern: tuple[int]) -> str:
    d = {MISS: "⬛", MISPLACED: "🟨", EXACT: "🟩"}
    return "".join(d[x] for x in pattern)


def safe_log2(x: int | float) -> int | float:
    return math.log2(x) if x > 0 else 0


def pattern_permutations(word_lenght: int=5) -> set | set[tuple[int]]:
    return set(it.product([MISS, MISPLACED, EXACT], repeat=word_lenght))


def find_possible_matches(word: tuple[int], words_list: set[tuple[int]], pattern_to_match: tuple[int]) -> set | set[tuple[int]]:
    matches = set()

    for word_to_match in words_list:
        if word_to_match == word:
            continue

        if compute_pattern(guess=word, word=word_to_match) == pattern_to_match:
            matches.add(word_to_match)

    return matches


def compute_word_entropy(word: tuple[int], words_list: set[tuple[int]]) -> float:
    entropy = 0.0

    for pp in pattern_permutations(len(word)):
        match_probability = len(find_possible_matches(word, words_list, pp)) / len(words_list)
        entropy += (match_probability * -safe_log2(match_probability))

    return entropy


def compute_word_entropy_worker(pool_words_chunk: set[tuple[int]], pool_words: set[tuple[int]],
                                return_dict_entropy: managers.DictProxy) -> None:
    for word in pool_words_chunk:
        return_dict_entropy[word] = compute_word_entropy(word, pool_words)


def prepare_worker_datas(pool_words: set[tuple[int]], threads: int=0) -> tuple[list[list[tuple[int]]], managers.DictProxy, list[Process]]:
    if not 0 < threads <= cpu_count():
        threads = cpu_count()

    chunk_size = math.ceil(len(pool_words)/threads)
    pool_words: list[tuple[int]] = list(pool_words)
    pool_words_chunked = [pool_words[i:i + chunk_size] for i in range(0, len(pool_words), chunk_size)]

    manager = Manager()
    return_dict_entropy = manager.dict()
    jobs: list[Process] = []

    return pool_words_chunked, return_dict_entropy, jobs
