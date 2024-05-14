#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 11:28:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import time
from fastapi import FastAPI

#pylint: disable=wrong-import-position, wrong-import-order
import models
from modules import helpers
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'

app = FastAPI()

APP_SOURCES = models.init_app_sources()
APP_SESSIONS = models.APP_SESSIONS


@app.get("/version")
async def get_version() -> dict[str, str]:
    return { 'status': helpers.StatusFunction.SUCCESS.name, 'version': APP_SOURCES.get('version'), 'error': '' }


@app.get("/get_active_games")
async def get_active_games() -> dict[str, str | int]:
    try:
        now = int(time.time())
        sessions_gc: list[str] = []

        for session_uuid, game_session in APP_SESSIONS.items():
            if now - game_session['last_active_timestamp'] >= APP_SOURCES['SESSION_TTL_SECONDS']:
                sessions_gc.append(session_uuid)

        for session_uuid in sessions_gc:
            del APP_SESSIONS[session_uuid]

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'active_games': len(APP_SESSIONS), 'error': '' }


@app.get("/app_sources")
async def get_app_sources() -> dict[str, str | dict[str, dict[str, str | dict[str, dict[str, str | int]] | int] | str | int | bool]]:
    app_sources = models.init_app_sources(client=True)
    return { 'status': helpers.StatusFunction.SUCCESS.name, 'app_sources': app_sources, 'error': '' }


@app.post("/create_game_session")
async def create_game_session(lang: str, word_lenght: int, max_tries: int, game_mode: str=helpers.GameMode.GAME_MODE_PLAY.name) -> dict [str, str]:
    try:
        if len(APP_SESSIONS) >= APP_SOURCES['MAX_SESSIONS']:
            return { 'status': helpers.StatusFunction.ERROR.name, 'error': 'MAX_SESSIONS limit reached' }

        game_session = models.create_game_session(APP_SOURCES.get(lang, {}).get('pre_computed', {}).get(str(word_lenght), {}).get('lang_launcher'),
                                                  game_mode, max_tries)
        APP_SESSIONS.update({game_session['session_uuid']: game_session})

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'session_uuid': game_session['session_uuid'], 'error': '' }


@app.post("/reset_game_session")
async def reset_game_session(session_uuid: str, game_mode: str="GAME_MODE_PLAY") -> dict[str, str]:
    try:
        models.reset_game_session(APP_SESSIONS[session_uuid], game_mode)

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'error': '' }


@app.post("/delete_game_session")
async def delete_game_session(session_uuid: str) -> dict[str, str]:
    try:
        del APP_SESSIONS[session_uuid]

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'error': '' }


@app.post("/get_game_session_stats")
async def get_game_session_stats(session_uuid: str) -> dict[str, str | dict[str, str | int | list[str]]]:
    try:
        stats = models.get_game_session_stats(APP_SESSIONS[session_uuid])

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'session_stats': stats, 'error': '' }


@app.post("/get_word_to_guess")
async def get_word_to_guess(session_uuid: str) -> dict[str, str]:
    try:
        word = models.get_word_to_guess(APP_SESSIONS[session_uuid])

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'word': word, 'error': '' }


@app.post("/get_guess_stats")
async def get_guess_stats(session_uuid: str, word: str, pattern: str) -> dict[str, str | dict | dict[str, list[tuple[tuple[int], float]] | set[int] | dict[str, int] | list[list[tuple[tuple[int], float]]] | float]]:
    try:
        stats = models.get_guess_stats(APP_SESSIONS[session_uuid], word, helpers.emoji_to_pattern(pattern))

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'guess_stats': stats, 'error': '' }


@app.post("/submit_guess")
async def submit_guess(session_uuid: str, word: str) -> dict[str, str]:
    try:
        if (resp_guess := models.submit_guess(APP_SESSIONS[session_uuid], word)) is None:
            return { 'status': helpers.StatusFunction.ERROR.name, 'error': f'INVALID_WORD {word}' }

        pattern = helpers.pattern_to_emoji(resp_guess)

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

    return { 'status': helpers.StatusFunction.SUCCESS.name, 'pattern': pattern, 'error': '' }

# fastapi dev main.py
