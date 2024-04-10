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
import pathlib

import math

import itertools as it
from copy import deepcopy
from multiprocessing import Process, managers, Manager, cpu_count

import unidecode

#pylint: disable=wrong-import-position, wrong-import-order

#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


MISS = 0
MISPLACED = 1
EXACT = 2


class LangLauncher():
    def __init__(self, words_path: str, compute_best_opening: bool=False, word_lenght: int=5, tries: int=6, threads: int=0) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        tic = time.perf_counter()

        self.compute_best_opening = compute_best_opening
        self.word_lenght = word_lenght
        self.tries = tries
        self.threads = threads

        print(f"{curr_func} -- Acquiring file {words_path}...")
        words_file = pathlib.Path(words_path).expanduser()

        print(f"{curr_func} -- Building word list...")
        self.words = get_words_list(words_file, self.word_lenght)
        if not self.words:
            raise ValueError
        print(f"{curr_func} -- Found {len(self.words)} words...")

        print(f"{curr_func} -- Building pattern compendium...")
        self.pattern_compendium = build_pattern_compendium(self.words)
        print(f"{curr_func} -- Found {len(self.pattern_compendium)} patterns...")

        self.words_information: list | list[tuple[str, float]] = []
        if self.compute_best_opening:
            print(f"{curr_func} -- Computing exhaustive information for best opening...")
            self.words_information: list | list[tuple[str, float]] = compute_words_information_faster(self.words, self.threads)

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Language launcher for {words_file.name} initialised in {tac} second(s)")


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


#####################################
#### LEGCACY AND SLOW COMPUTAION ####
#####################################


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


def compute_words_information(pool_words: set[tuple[int]], threads: int=0) -> list | list[tuple[int, float]]:
    curr_func = inspect.currentframe().f_code.co_name

    words_information: list | list[tuple[int, float]] = []
    pool_words_chunked, return_dict_entropy, jobs = prepare_worker_datas(pool_words, threads)

    for pool_words_chunk in pool_words_chunked:
        jobs.append(Process(target=compute_word_entropy_worker,
                            args=(set(pool_words_chunk), pool_words, return_dict_entropy)))
        jobs[-1].start()

    for process in jobs:
        process.join()

    try:
        words_information = sorted(return_dict_entropy.items(), key=lambda x : x[1], reverse=True)

    except Exception as err:
        print(f"{curr_func} -- Something went wrong: {repr(err)}")

    return words_information


#####################################
####  NEW AND FASTER COMPUTAION  ####
#####################################


def build_pattern_compendium(pool_words: set[tuple[int]]) -> dict | dict[str, set[tuple[tuple[int]]]]:
    pool_words_pile: set[tuple[int]] = deepcopy(pool_words)

    pattern_compendium: dict[str, set[tuple[tuple[int]]]] = {}

    while pool_words_pile:
        word_piled = pool_words_pile.pop()

        for word in pool_words:

            if word == word_piled:
                continue

            pattern = ''.join(str(p) for p in compute_pattern(guess=word_piled, word=word))

            if pattern_compendium.get(pattern, None) is None:
                pattern_compendium[pattern] = {tuple(sorted([word_piled, word]))}

            pattern_compendium[pattern].add(tuple(sorted([word_piled, word])))

    return pattern_compendium


def compute_word_entropy_faster(word: tuple[int], pattern_compendium: dict[str, set[tuple[tuple[int]]]], nbr_words: int) -> float:
    entropy = 0.0

    for _, compendium in pattern_compendium.items():
        match_probability = len([word_matched for word_matched in compendium if word in word_matched]) / nbr_words
        entropy += (match_probability * -safe_log2(match_probability))

    return entropy


def compute_word_entropy_faster_worker(pool_words_chunk: set[tuple[int]], pattern_compendium: dict[str, set[tuple[tuple[int]]]], nbr_words: int,
                                       return_dict_entropy: managers.DictProxy) -> None:
    for word in pool_words_chunk:
        return_dict_entropy[word] = compute_word_entropy_faster(word, pattern_compendium, nbr_words)


def compute_words_information_faster(pool_words: set[tuple[int]], threads: int=0) -> list | list[tuple[int, float]]:
    curr_func = inspect.currentframe().f_code.co_name

    words_information: list | list[tuple[int, float]] = []
    pool_words_chunked, return_dict_entropy, jobs = prepare_worker_datas(pool_words, threads)
    pattern_compendium = build_pattern_compendium(pool_words)

    for pool_words_chunk in pool_words_chunked:
        jobs.append(Process(target=compute_word_entropy_faster_worker,
                            args=(set(pool_words_chunk), pattern_compendium, len(pool_words), return_dict_entropy)))
        jobs[-1].start()

    for process in jobs:
        process.join()

    try:
        words_information = sorted(return_dict_entropy.items(), key=lambda x : x[1], reverse=True)

    except Exception as err:
        print(f"{curr_func} -- Something went wrong: {repr(err)}")

    return words_information
