#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun 18 11:43:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect
import pathlib

import random

#pylint: disable=wrong-import-position, wrong-import-order
from modules import computing, compendium_cache
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def main():
    curr_func = inspect.currentframe().f_code.co_name

    words = ["pet", "bag", "tip", "cup", "big", "bug", "cap", "top", "put", "bob", "bip", "zap", "zoo"]
    words.sort()
    pool_words = {tuple(ord(letter) for letter in word) for word in words}

    pattern_compendium = computing.build_pattern_compendium(pool_words)

    db_path = pathlib.Path('compendium.sqlite').expanduser()
    exist_db = db_path.exists()

    compendium = compendium_cache.CacheDB(db_path, set(pattern_compendium.keys()), guess="TEXT", word="TEXT")

    cptr = 0
    for pattern, combinations in pattern_compendium.items():
        if not exist_db:
            guesses = ["".join(chr(letter_ord) for letter_ord in pair[0]) for pair in combinations]
            words   = ["".join(chr(letter_ord) for letter_ord in pair[-1]) for pair in combinations]

            compendium.add_entries(pattern, guess=guesses, word=words)

        cptr = cptr + len(words)

    print(f"{curr_func} -- {cptr} entries in cache compendium...")

    cols = ("guess", "word")
    choice_pattern, _ = random.choice(list(pattern_compendium.items()))
    constraints = f'AND (guess = "{random.choice(words)}" OR word = "{random.choice(words)}")'
    result = compendium.get_entries(choice_pattern, cols, constraints)

    print(f"{curr_func} -- Returned entries with query SELECT {cols} FROM {choice_pattern} WHERE {constraints}: {result}")

if __name__ == "__main__":
    main()
