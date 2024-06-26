#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on Mon Apr 15 15:25:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
'''

#===================================================================================================
import time
import uuid
import json
import inspect
import pathlib
from pydantic import BaseModel

#pylint: disable=wrong-import-position, wrong-import-order
from modules import statics, helpers, computing, wordle
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


APP_SESSIONS: dict[str, dict[str, str | wordle.Wordle | int | list[str]]] = {}


class Config(BaseModel):
    dict_path: str
    exhaustive: bool
    word_lenght: int


def init_app_sources(client: bool=False) -> dict[str, dict[str, str | pathlib.Path | dict[str, dict[str, str | pathlib.Path | int | helpers.LangLauncher]] | int] | str | int | bool]:
    cwd = pathlib.Path.cwd()

    config_file = 'config.json'

    with open(cwd/config_file, encoding='utf-8') as f:
        conf: dict[str, str] = json.load(f)

    data_files = pathlib.Path(cwd/conf["data_folder"]).glob('*.txt')
    lang_files: list[pathlib.Path] = []
    exhaustive_files: list[pathlib.Path] = []

    for file in data_files:
        if '_' not in file.name:
            lang_files.append(file)

        else:
            exhaustive_files.append(file)

    app_sources = helpers.init_lang_app_data(lang_files,
                                             exhaustive_files,
                                             compute_best_opening=not client if client else conf.get('compute_best_opening', False),
                                             client=client)
    app_sources.update(conf)

    game_modes = {g.name: g.value for g in statics.GameMode}
    app_sources.update({"game_modes": game_modes})

    return app_sources


def init_lang_launcher(config: Config) -> helpers.LangLauncher:
    return helpers.LangLauncher(config.dict_path, config.exhaustive, config.word_lenght)


def create_game_session(lang_launcher: helpers.LangLauncher,
                        compute_best_opening: bool,
                        game_mode: str, max_tries: int=6) -> dict[str, str | wordle.Wordle | int | list[str]]:
    curr_func = inspect.currentframe().f_code.co_name

    if not compute_best_opening and game_mode != statics.GameMode.GAME_MODE_PLAY.name:
        return {}

    session_uuid = str(uuid.uuid4())

    print(f"{curr_func} -- Creating game_session {session_uuid}")

    return {'session_uuid': session_uuid,
            'game_session': wordle.Wordle(lang_launcher),
            'game_mode': game_mode,
            'max_tries': max_tries,
            'current_tries': 0,
            'guesses': [],
            'patterns': [],
            'created_timestamp': int(time.time()),
            'last_active_timestamp': int(time.time())}


def reset_game_session(game_session: dict[str, str | wordle.Wordle | int | list[str]], game_mode: str, max_tries: int=6) -> None:
    game_session['game_session'].reset()
    game_session['game_mode'] = game_mode
    game_session['max_tries'] = max_tries
    game_session['current_tries'] = 0
    game_session['guesses'] = []
    game_session['patterns'] = []
    game_session['last_active_timestamp'] = int(time.time())


def get_game_session_stats(game_session: dict[str, str | wordle.Wordle | int | list[str]]) -> dict[str, str | int | list[str]]:
    return {'game_mode': game_session['game_mode'],
            'max_tries': game_session['max_tries'],
            'current_tries': game_session['current_tries'],
            'guesses': game_session['guesses'],
            'patterns': game_session['patterns'],
            'created_timestamp': game_session['created_timestamp'],
            'last_active_timestamp': game_session['last_active_timestamp']}


def get_word_to_guess(game_session: dict[str, str | wordle.Wordle | int | list[str]]) -> str:
    return "".join(chr(ord_letter) for ord_letter in game_session['game_session'].word)


def get_guess_stats(game_session: dict[str, str | wordle.Wordle | int | list[str]],
                    word: str,
                    pattern: str) -> dict | dict[str, list | list[dict[str, float]] | list[str] | dict | dict[str, int] | dict[int, list[dict[str, float]]]]:
    if game_session['game_mode'] == statics.GameMode.GAME_MODE_PLAY.name:
        return {}

    t_word = tuple(ord(letter) for letter in word)
    t_pattern = tuple(int(letter_status) for letter_status in statics.emoji_to_pattern(pattern))

    pool = game_session['game_session'].submit_guess_and_pattern(t_word, t_pattern)
    game_session['game_session'].letter_extractor = computing.update_letter_extractor(game_session['game_session'].letter_extractor,
                                                                                      computing.build_letter_extractor(t_word, t_pattern))
    pool_letters, pool_letters_dupes = computing.gather_pool_letters(pool)
    suggestions = computing.build_suggestion(game_session['game_session'].language_launcher.words_information,
                                             pool_letters,
                                             pool_letters_dupes,
                                             game_session['game_session'].letter_extractor)

    if game_session['game_mode'] == statics.GameMode.GAME_MODE_SOLVE.name:
        game_session['guesses'].append(word)
        game_session['patterns'].append(pattern)
        game_session['last_active_timestamp'] = int(time.time())

    return {'pool_words': convert_pool_words(pool),
            'pool_letters': convert_pool_letters(pool_letters),
            'pool_letters_dupes': convert_pool_letters_dupes(pool_letters_dupes),
            'elimination_suggestions': convert_elimination_suggestions(suggestions),
            'information': game_session['game_session'].information}


def submit_guess(game_session: dict[str, str | wordle.Wordle | int | list[str]], word: str) -> str | None:
    if game_session['current_tries'] >= game_session['max_tries']:
        return None

    t_pattern = game_session['game_session'].submit_guess(tuple(ord(letter) for letter in word))

    if not t_pattern or t_pattern is None:
        return None

    pattern = statics.pattern_to_emoji(t_pattern)

    game_session['guesses'].append(word)
    game_session['patterns'].append(pattern)
    game_session['current_tries'] = game_session['current_tries'] + 1
    game_session['last_active_timestamp'] = int(time.time())

    return pattern


def convert_pool_words(pool: list | list[tuple[tuple[int, ...], float]]) -> list | list[dict[str, float]]:
    return [{"".join(chr(ord_letter) for ord_letter in suggestion): round(information, 5)} for suggestion, information in pool]


def convert_pool_letters(pool_letters: set[int]) -> list | list[str]:
    return [chr(ord_letter) for ord_letter in pool_letters]


def convert_pool_letters_dupes(pool_letters_dupes: dict[int, int]) -> dict | dict[str, int]:
    return {str(key): val for key, val in pool_letters_dupes}


def convert_elimination_suggestions(suggestions: list[list[tuple[tuple[int, ...], float]]]) -> dict | dict[int, list[dict[str, float]]]:
    elimination_suggestions: dict[int, list[dict[str, float]]] = {}

    for rank, ranked_suggestions in enumerate(suggestions):
        if ranked_suggestions:
            temp_suggs = [{"".join(chr(ord_letter) for ord_letter in suggestion): round(information, 5)} for suggestion, information in ranked_suggestions]

            if elimination_suggestions.get(rank+1) is None:
                elimination_suggestions[rank+1] = [temp_suggs]
                continue

            elimination_suggestions[rank+1].append(temp_suggs)

    return elimination_suggestions
