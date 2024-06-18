#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May 15 15:10:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import inspect

import random

#pylint: disable=wrong-import-position, wrong-import-order
from modules import statics, helpers, computing, wordle
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def main() -> None:
    curr_func = inspect.currentframe().f_code.co_name

    file_path = "data/wordle.txt"
    best_opening = True
    max_chars = 5
    max_tries = 6
    threads = 0

    language_launcher = helpers.LangLauncher(file_path, best_opening, max_chars, threads)
    max_games = 2#len(language_launcher.words) # 0 and 1 are forbidden !
    nb_guesses: list[int] = []
    nb_suggestion_used: list[int] = []

    cptr_games = 0
    for word in language_launcher.words:
        game = wordle.Wordle(language_launcher)
        game.word = word

        print(f"{curr_func} -- Starting game n°{cptr_games + 1}")
        print(f"{curr_func} -- Word to guess is: {''.join(chr(ord_letter) for ord_letter in game.word)}")

        guess = "".join(chr(ord_letter) for ord_letter in random.choice(list(game.language_launcher.words)))
        if best_opening:
            guess = "".join(chr(ord_letter) for ord_letter in game.language_launcher.words_information[0][0])
        pattern = tuple([statics.StatusLetter.MISS.value]*max_chars)
        letter_extractor = {"incl": {}, "excl": {}}

        cptr_suggestion_used = 0
        cptr_tries = 0
        while cptr_tries < max_tries*2:
            print("-------------------------------------------------------------")
            print(f"{curr_func} -- Attempt n° {cptr_tries + 1} -- Trying word: {guess} -- {len(game.pool_words)}/{len(language_launcher.words)}")

            pattern = game.submit_guess(guess)
            if pattern == tuple([statics.StatusLetter.EXACT.value]*max_chars):
                break

            pool = game.submit_guess_and_pattern(guess, ''.join(str(p) for p in pattern))
            if pool is None:
                break

            ###### RUN SECOND SUGGESTION TO COVER MORE LETTERS ######
            letter_extractor = computing.update_letter_extractor(letter_extractor,
                                                                 computing.build_letter_extractor(tuple(ord(letter) for letter in guess),
                                                                                                  pattern))
            pool_letters, pool_letters_dupes = computing.gather_pool_letters(pool)
            suggestions = computing.build_suggestion(game.language_launcher.words_information,
                                                     pool_letters,
                                                     pool_letters_dupes,
                                                     letter_extractor)
            print(f"{curr_func} -- Found {len(pool_letters)} different letters to try with {len(pool_letters_dupes)} dupes")
            for sugg_rank in range(game.language_launcher.word_lenght - 1, 0 - 1, -1):
                if suggestions[sugg_rank] is not None:
                    if len(suggestions[sugg_rank]) > 0:
                        print(f"{curr_func} -- Rank {sugg_rank} has {len(suggestions[sugg_rank])} suggestions")
                        break
            sugg_guesses = ["".join(chr(letter) for letter in sugg[0]) for sugg in suggestions[sugg_rank]]
            # print(f"{curr_func} -- Suggestion are {sugg_guesses}")

            ###### ESTABLISH IF SECOND SUGGESTION IS BETTER THAN INFORMATION SUGGESTION ######
            thresh_sugg = (game.language_launcher.word_lenght % 2) + game.language_launcher.word_lenght // 2
            if len(pool) <= 2:
                guess = "".join(chr(ord_letter) for ord_letter in pool[0][0])
            elif len(pool) > 2 and \
                 sugg_rank > game.language_launcher.word_lenght - thresh_sugg and \
                 pattern.count(statics.StatusLetter.EXACT.value) >= thresh_sugg:
                guess = sugg_guesses[0]
                print(f"{curr_func} -- ⚠️  Using suggestion '{guess}' on next attemp ⚠️")
                cptr_suggestion_used = cptr_suggestion_used + 1
            else:
                guess = "".join(chr(ord_letter) for ord_letter in pool[0][0])

            cptr_tries = cptr_tries + 1

        if cptr_tries == max_tries:
            print(f"{curr_func} -- FAIL -- autoWordle failed to find a solution in {max_tries} (or less) attemps")

        print("##############################################################")
        nb_guesses.append(cptr_tries + 1)
        nb_suggestion_used.append(cptr_suggestion_used)
        cptr_games = cptr_games + 1

        if cptr_games == max_games:
            break

    nb_guesses.sort()
    median_guesses = nb_guesses[cptr_games // 2] if cptr_games % 2 == 0 else (nb_guesses[cptr_games // 2] + nb_guesses[(cptr_games // 2) + 1]) / 2
    failed_games = 0
    for over_try in range(max_tries + 1, (max_tries*2) + 1, 1):
        try:
            idx = nb_guesses.index(over_try)
            failed_games = len(nb_guesses[idx:])
            break
        except:
            continue

    nb_suggestion_used.sort()
    median_suggestion_used = nb_suggestion_used[cptr_games // 2] if cptr_games % 2 == 0 else (nb_suggestion_used[cptr_games // 2] + nb_suggestion_used[(cptr_games // 2) + 1]) / 2
    game_where_sugg_used = max_games - nb_suggestion_used.count(0)

    print(f"{curr_func} -- END -- Played {cptr_games} games")
    print(f"{curr_func} -- END -- Average tries is {round(sum(nb_guesses) / cptr_games, 2)}")
    print(f"{curr_func} -- END -- Median tries is {median_guesses}")
    print(f"{curr_func} -- END -- (Min, Max) tries are ({min(nb_guesses)}, {max(nb_guesses)})")
    print(f"{curr_func} -- END -- {nb_guesses.count(1)} Lucky guess")
    print(f"{curr_func} -- END -- {failed_games} Game Over")

    print(f"{curr_func} -- END -- Average suggestion use is {round(sum(nb_suggestion_used) / cptr_games, 2)}")
    print(f"{curr_func} -- END -- Median suggestion use is {median_suggestion_used}")
    print(f"{curr_func} -- END -- Suggestion used in {game_where_sugg_used} game(s)")

if __name__ == "__main__":
    main()
