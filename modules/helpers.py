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
import pickle

import unidecode

#pylint: disable=wrong-import-position, wrong-import-order
from modules import computing
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


class LangLauncher():
    def __init__(self, words_path: str | pathlib.Path,
                 compute_best_opening: bool=False,
                 word_lenght: int=5,
                 threads: int=0) -> None:
        curr_func = inspect.currentframe().f_code.co_name

        tic = time.perf_counter()

        self.compute_best_opening = compute_best_opening
        self.word_lenght = word_lenght
        self.threads = threads

        print(f"{curr_func} -- Acquiring file {words_path}...")
        if isinstance(words_path, str):
            self.words_file = pathlib.Path(words_path).expanduser()
        else:
            self.words_file = words_path

        print(f"{curr_func} -- Building word list...")
        self.words = get_words_list(self.words_file, self.word_lenght)
        if not self.words:
            raise ValueError
        print(f"{curr_func} -- Found {len(self.words)} words...")

        self.pattern_compendium: dict | dict[str, set[tuple[tuple[int]]]] = self.build_pattern_compendium(self.compute_best_opening)
        self.words_information: list | list[tuple[tuple[int], float]] = self.compute_words_information(self.compute_best_opening)

        tac = time.perf_counter() - tic

        print(f"{curr_func} -- Language launcher for {self.words_file.name} initialised in {round(tac, 2)} second(s)")


    def __str__ (self) -> str:
        return self.__class__.__name__


    def get_couples_from_compendium(self, pattern: str) -> set | set[tuple[tuple[int]]]:
        if self.compute_best_opening:
            return self.pattern_compendium.get(pattern, {})

        return set() #TODO SQL database call here


    def build_pattern_compendium(self, build_compendium: bool) -> dict | dict[str, set[tuple[tuple[int]]]]:
        curr_func = inspect.currentframe().f_code.co_name

        if not build_compendium:
            return {}

        print(f"{curr_func} -- Building pattern compendium...")
        pattern_compendium: dict | dict[str, set[tuple[tuple[int]]]] = {}

        saved_compendium_path = str(self.words_file).replace(self.words_file.name,
                                                             f"{self.words_file.stem}_{str(self.word_lenght)}_compendium.pkl")
        saved_compendium_file = pathlib.Path(saved_compendium_path).expanduser()
        if saved_compendium_file.is_file():
            pattern_compendium = pickle.load(saved_compendium_file.open('rb'))
        else:
            pattern_compendium = computing.build_pattern_compendium(self.words)
            pickle.dump(pattern_compendium, saved_compendium_file.open('wb'))
        print(f"{curr_func} -- Found {len(pattern_compendium)} patterns...")

        return pattern_compendium


    def compute_words_information(self, compute_best_opening: bool) -> list | list[tuple[tuple[int], float]]:
        curr_func = inspect.currentframe().f_code.co_name

        words_information: list | list[tuple[tuple[int], float]] = []

        saved_words_information_path = str(self.words_file).replace(self.words_file.name,
                                                                    f"{self.words_file.stem}_{str(self.word_lenght)}_info{self.words_file.suffix}")
        saved_words_information_file = pathlib.Path(saved_words_information_path).expanduser()

        if saved_words_information_file.is_file():
            print(f"{curr_func} -- Loading exhaustive information for best opening...")
            words_information = load_words_information(saved_words_information_file)

        elif compute_best_opening:
            print(f"{curr_func} -- Computing exhaustive information for best opening...")
            words_information = computing.compute_words_information_faster(self.words, self.threads)
            save_words_information(saved_words_information_file, self.words_information)

        else:
            pass

        return words_information


def init_lang_app_data(lang_files: list[pathlib.Path],
                       exhautsive_files: list[pathlib.Path],
                       compute_best_opening: bool=False,
                       client: bool=False) -> dict[str, dict[str, str | pathlib.Path | dict[str, dict[str, str | pathlib.Path | int | LangLauncher]]]]:
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
