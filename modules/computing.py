#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 15 15:10:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect

import math

from collections import Counter
from copy import deepcopy
from multiprocessing import Process, managers, Manager, cpu_count

#pylint: disable=wrong-import-position, wrong-import-order
from modules import statics
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def compute_pattern(guess: tuple[int, ...], word: tuple[int, ...]) -> tuple | tuple[int, ...]:
    pattern = [statics.StatusLetter.MISS.value] * len(word)
    temp_guess = list(guess)

    for w_cptr, w_letter in enumerate(word):
        if w_letter == guess[w_cptr]:
            pattern[w_cptr] = statics.StatusLetter.EXACT.value
            temp_guess[w_cptr] = -1

        else:
            if temp_guess.count(w_letter) == 0:
                continue

            idx = temp_guess.index(w_letter)
            pattern[idx] = statics.StatusLetter.MISPLACED.value
            temp_guess[idx] = -1

    return tuple(pattern)


def build_letter_extractor(guess: tuple[int, ...], pattern: tuple[int, ...]) -> dict[str, dict] | dict[str, dict[str, int]]:
    extractor: dict[str, dict] | dict[str, dict[str, int]] = {"incl": {}, "excl": {}}

    for pos, letter in enumerate(guess):
        letter_chr = chr(letter)

        if pattern[pos] != statics.StatusLetter.MISS.value:
            if letter_chr not in extractor["incl"]:
                extractor["incl"][letter_chr] = 1
                continue

            extractor["incl"][letter_chr] = extractor["incl"][letter_chr] + 1
            continue

        extractor["excl"][letter_chr] = 1

    return extractor


def update_letter_extractor(old_ext: dict[str, dict[str, int]], new_ext: dict[str, dict[str, int]]) -> dict[str, dict] | dict[str, dict[str, int]]:
    for letter in new_ext["incl"]:
        if letter not in old_ext["incl"]:
            old_ext["incl"][letter] = new_ext["incl"][letter]
            continue

        old_ext["incl"][letter] = old_ext["incl"][letter] + new_ext["incl"][letter]

    old_ext["excl"].update(new_ext["excl"])

    return old_ext


def gather_pool_letters(pool_words: list[tuple[tuple[int, ...], float]]) -> tuple[set, dict] | tuple[set[int], dict[str, int]]:
    pool_letters = set()
    dupes: dict[str, int] = {}

    for word in pool_words:
        unique_letters = set(word[0])
        pool_letters.update(unique_letters)

        if len(unique_letters) < len(word[0]):
            for letter in unique_letters:
                if count := word[0].count(letter):
                    char = chr(letter)
                    dupes[char] = count if dupes.get(char, 0) < count else dupes.get(char, count)

    return pool_letters, dupes


def build_suggestion(pool_words_information: list[tuple[tuple[int, ...], float]],
                     pool_letters: set[int],
                     pool_letters_dupes: dict[str, int],
                     letter_extractor: dict[str, dict[str, int]]) -> list[list] | list[list[tuple[tuple[int, ...], float]]]:
    known_letters = set()

    for letter in letter_extractor["incl"]:
        # If the letter can have a dupe (according to the pool_words),
        # but we don't know for sure (because not tested),
        # then we don't add it in the known_letters (and should test it if possible)
        if pool_letters_dupes.get(letter, 0) != 0 and pool_letters_dupes.get(letter, 0) > letter_extractor["incl"].get(letter, 0):
            continue
        known_letters.add(ord(letter))

    # By design, if the letter extracted is in the exclusion list, but also in the inclusion list,
    # then it means that we know for sure how many time the letter is in the word to guess,
    # and we should have pool_letters_dupes.get(letter, 0) == letter_extractor["incl"].get(letter, 0)
    for letter in letter_extractor["excl"]:
        known_letters.add(ord(letter))

    unknown_letters = pool_letters.difference(known_letters)
    suggestions: list[list[tuple[tuple[int, ...], float]]] = [None]*(len(pool_words_information[0][0])+1)

    for word_information in pool_words_information:
        nb_letters_in_common = len(set(word_information[0]).intersection(unknown_letters))
        if suggestions[nb_letters_in_common] is None:
            suggestions[nb_letters_in_common] = [word_information]
            continue
        suggestions[nb_letters_in_common].append(word_information)

    for idx, sugg_letters_in_common in enumerate(suggestions):
        if sugg_letters_in_common:
            suggestions[idx] = sorted(sugg_letters_in_common, key = lambda x: x[-1], reverse=True)

    return suggestions


def safe_log2(x: int | float) -> int | float:
    return math.log2(x) if x > 0 else 0


def prepare_worker_datas(pool_words: set[tuple[int, ...]], threads: int=0) -> tuple[list[list[tuple[int, ...]]], managers.DictProxy, list[Process]]:
    if not 0 < threads <= cpu_count():
        threads = cpu_count()

    chunk_size = math.ceil(len(pool_words)/threads)
    pool_words: list[tuple[int, ...]] = list(pool_words)
    pool_words_chunked = [pool_words[i:i + chunk_size] for i in range(0, len(pool_words), chunk_size)]

    manager = Manager()
    return_dict_entropy = manager.dict()
    jobs: list[Process] = []

    return pool_words_chunked, return_dict_entropy, jobs


#####################################
####  NEW AND FASTER COMPUTAION  ####
#####################################


def build_pattern_compendium(pool_words: set[tuple[int, ...]]) -> dict | dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]]:
    pool_words_pile: set[tuple[int, ...]] = deepcopy(pool_words)

    pattern_compendium: dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]] = {}

    while pool_words_pile:
        word_piled = pool_words_pile.pop()

        for word in pool_words:

            if word == word_piled:
                continue

            pattern = compute_pattern(guess=word_piled, word=word)

            if pattern not in pattern_compendium:
                pattern_compendium[pattern] = {tuple(sorted([word_piled, word]))}
                continue

            pattern_compendium[pattern].add(tuple(sorted([word_piled, word])))

    return pattern_compendium


def compute_word_counter_by_pattern(pattern_compendium: dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]]) -> dict[tuple[int, ...], dict[str, int]]:
    word_counter_by_pattern: dict[str, dict[str, int]] = {}

    for pattern, compendium in pattern_compendium.items():
        pattern_words = ["".join(chr(letter) for letter in word) for word_matched in compendium for word in word_matched]
        word_counter_by_pattern[pattern] = dict(Counter(pattern_words))

    return word_counter_by_pattern


def compute_word_entropy_faster(word: tuple[int, ...], word_counter_by_pattern: dict[str, dict[str, int]], nbr_words: int) -> float:
    entropy = 0.0

    for _, compendium in word_counter_by_pattern.items():
        match_probability = compendium.get("".join(chr(letter) for letter in word), 0) / nbr_words
        entropy += (match_probability * -safe_log2(match_probability))

    return entropy


def compute_word_entropy_faster_worker(pool_words_chunk: set[tuple[int, ...]], word_counter_by_pattern: dict[str, dict[str, int]], nbr_words: int,
                                       return_dict_entropy: managers.DictProxy) -> None:
    for word in pool_words_chunk:
        return_dict_entropy[word] = compute_word_entropy_faster(word, word_counter_by_pattern, nbr_words)


def compute_words_information_faster(pool_words: set[tuple[int, ...]],
                                     pattern_compendium: dict[tuple[int, ...], set[tuple[tuple[int, ...], tuple[int, ...]]]],
                                     threads: int=0) -> list | list[tuple[tuple[int, ...], float]]:
    curr_func = inspect.currentframe().f_code.co_name

    words_information: list | list[tuple[tuple[int, ...], float]] = []
    pool_words_chunked, return_dict_entropy, jobs = prepare_worker_datas(pool_words, threads)
    word_counter_by_pattern = compute_word_counter_by_pattern(pattern_compendium)

    for pool_words_chunk in pool_words_chunked:
        jobs.append(Process(target=compute_word_entropy_faster_worker,
                            args=(set(pool_words_chunk), word_counter_by_pattern, len(pool_words), return_dict_entropy)))
        jobs[-1].start()

    for process in jobs:
        process.join()

    try:
        words_information = sorted(return_dict_entropy.items(), key=lambda x : x[1], reverse=True)

    except Exception as err:
        print(f"{curr_func} -- Something went wrong: {repr(err)}")

    return words_information
