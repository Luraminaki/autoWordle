#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 02 10:20:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import enum
import time
import inspect
import pathlib
import pickle

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


class GameMode(enum.Enum):
    GAME_MODE_PLAY = enum.auto()
    GAME_MODE_SOLVE = enum.auto()
    GAME_MODE_ASSISTED = enum.auto()


class StatusFunction(enum.Enum):
    SUCCESS = enum.auto()
    FAIL = enum.auto()
    ONGOING = enum.auto()
    DONE = enum.auto()
    ERROR = enum.auto()
    WARNING = enum.auto()


class LangLauncher():
    def __init__(self, words_path: str | pathlib.Path, compute_best_opening: bool=False, word_lenght: int=5, threads: int=0) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        tic = time.perf_counter()

        self.compute_best_opening = compute_best_opening
        self.word_lenght = word_lenght
        self.threads = threads

        print(f"{curr_func} -- Acquiring file {words_path}...")
        if isinstance(words_path, str):
            words_file = pathlib.Path(words_path).expanduser()
        else:
            words_file = words_path

        print(f"{curr_func} -- Building word list...")
        self.words = get_words_list(words_file, self.word_lenght)
        if not self.words:
            raise ValueError
        print(f"{curr_func} -- Found {len(self.words)} words...")

        print(f"{curr_func} -- Building pattern compendium...")
        saved_compendium_path = str(words_path).replace(words_file.name, words_file.stem + "_" + str(self.word_lenght) + "_compendium.pkl")
        saved_compendium_file = pathlib.Path(saved_compendium_path).expanduser()
        if saved_compendium_file.is_file():
            self.pattern_compendium = pickle.load(saved_compendium_file.open('rb'))
        else:
            self.pattern_compendium = build_pattern_compendium(self.words)
            pickle.dump(self.pattern_compendium, saved_compendium_file.open('wb'))
        print(f"{curr_func} -- Found {len(self.pattern_compendium)} patterns...")

        self.words_information: list | list[tuple[tuple[int], float]] = []
        if self.compute_best_opening:
            saved_words_information_path = str(words_path).replace(words_file.name, words_file.stem + "_" + str(self.word_lenght) + "_info" + words_file.suffix)
            saved_words_information_file = pathlib.Path(saved_words_information_path).expanduser()

            if saved_words_information_file.is_file():
                print(f"{curr_func} -- Loading exhaustive information for best opening...")
                self.words_information = load_words_information(saved_words_information_file)

            else:
                print(f"{curr_func} -- Computing exhaustive information for best opening...")
                self.words_information = compute_words_information_faster(self.words, self.threads)
                save_words_information(saved_words_information_file, self.words_information)

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Language launcher for {words_file.name} initialised in {round(tac, 2)} second(s)")


    def __str__ (self) -> str:
        return self.__class__.__name__


def init_lang_app_data(lang_files: list[pathlib.Path], exhautsive_files: list[pathlib.Path], compute_best_opening: bool=False, client: bool=False) -> dict[str, dict[str, str | pathlib.Path | dict[str, dict[str, str | pathlib.Path | int | LangLauncher]]]]:
    curr_func = inspect.currentframe().f_code.co_name

    app_sources: dict[str, dict[str, str | pathlib.Path | dict[str, dict[str, str | pathlib.Path | int | LangLauncher]]]] = {}

    for lang_file in lang_files:
        print(f"{curr_func} -- Found language <{lang_file.stem}>...")
        app_sources[lang_file.stem] = {'path': lang_file if not client else lang_file.name,
                                       'pre_computed': {}}

        for exhautsive_file in exhautsive_files:
            if lang_file.stem in exhautsive_file.stem:
                word_lenght = int(exhautsive_file.stem.split('_')[1])

                pre_computed = {'path': exhautsive_file if not client else exhautsive_file.name,
                                'lenght': word_lenght,
                                'lang_launcher': LangLauncher(lang_file, compute_best_opening, word_lenght) if not client else str(LangLauncher)}
                app_sources[lang_file.stem]['pre_computed'][str(word_lenght)] = pre_computed

    return app_sources


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


def save_words_information(path: pathlib.Path, words_information: list[tuple[tuple[int], float]]) -> None:
    path.unlink(missing_ok=True)

    with path.open('a', encoding='utf-8') as fp:
        for word_info in words_information:
            word = "".join(chr(letter) for letter in word_info[0])
            line = "".join([word, " ", str(word_info[1]), "\n"])
            fp.write(line)


def load_words_information(path: pathlib.Path) -> list | list[tuple[tuple[int], float]]:
    words_information: list | list[tuple[tuple[int], float]] = []

    with path.open('r', encoding='utf-8') as fp:
        for line in fp.readlines():
            word_info = line.split(" ", maxsplit=1)
            word_info[0] = tuple(ord(letter) for letter in word_info[0])
            word_info[1] = float(word_info[1].strip())
            words_information.append((word_info[0], word_info[1]))

    return words_information


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


def emoji_to_pattern(pattern: str) -> str:
    d = {"⬛": MISS, "🟨": MISPLACED, "🟩": EXACT}
    return "".join(str(d[x]) for x in pattern)


def build_letter_extractor(guess: tuple[int], pattern: tuple[int]) -> dict[str, dict] | dict[str, dict[str, int]]:
    extractor: dict[str, dict] | dict[str, dict[str, int]] = {"incl": {}, "excl": {}}

    for pos, letter in enumerate(guess):
        letter_chr = chr(letter)

        if pattern[pos] != MISS:
            if extractor["incl"].get(letter_chr, None) is None:
                extractor["incl"][letter_chr] = 1
                continue

            extractor["incl"][letter_chr] = extractor["incl"][letter_chr] + 1
            continue

        extractor["excl"][letter_chr] = 1

    return extractor


def update_letter_extractor(old_ext: dict[str, dict[str, int]], new_ext: dict[str, dict[str, int]]) -> dict[str, dict] | dict[str, dict[str, int]]:
    for letter in new_ext["incl"]:
        if old_ext["incl"].get(letter, None) is None:
            old_ext["incl"][letter] = new_ext["incl"][letter]
            continue

        old_ext["incl"][letter] = old_ext["incl"][letter] + new_ext["incl"][letter]

    old_ext["excl"].update(new_ext["excl"])

    return old_ext


def gather_pool_letters(pool_words: list[tuple[tuple[int], float]]) -> tuple[set, dict] | tuple[set[int], dict[str, int]]:
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


def build_suggestion(pool_words_information: list[tuple[tuple[int], float]],
                     pool_letters: set[int],
                     pool_letters_dupes: dict[str, int],
                     letter_extractor: dict[str, dict[str, int]]) -> list[list] | list[list[tuple[tuple[int], float]]]:
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
    suggestions: list[list[tuple[tuple[int], float]]] = [None]*(len(pool_words_information[0][0])+1)

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


def compute_words_information(pool_words: set[tuple[int]], threads: int=0) -> list | list[tuple[tuple[int], float]]:
    curr_func = inspect.currentframe().f_code.co_name

    words_information: list | list[tuple[tuple[int], float]] = []
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


def compute_words_information_faster(pool_words: set[tuple[int]], threads: int=0) -> list | list[tuple[tuple[int], float]]:
    curr_func = inspect.currentframe().f_code.co_name

    words_information: list | list[tuple[tuple[int], float]] = []
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
