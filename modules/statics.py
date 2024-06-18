#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 15 15:10:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import enum

import itertools as it
#pylint: disable=wrong-import-position, wrong-import-order

#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


class StatusLetter(enum.Enum):
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


def pattern_to_emoji(pattern: tuple[int]) -> str:
    d = {StatusLetter.MISS.value: "⬛",
         StatusLetter.MISPLACED.value: "🟨",
         StatusLetter.EXACT.value: "🟩"}
    return "".join(d[x] for x in pattern)


def emoji_to_pattern(pattern: str) -> str:
    d = {"⬛": StatusLetter.MISS.value,
         "🟨": StatusLetter.MISPLACED.value,
         "🟩": StatusLetter.EXACT.value}
    return "".join(str(d[x]) for x in pattern)


def pattern_permutations(word_lenght: int=5) -> set | set[tuple[int]]:
    return set(it.product([StatusLetter.MISS, StatusLetter.MISPLACED, StatusLetter.EXACT], repeat=word_lenght))
