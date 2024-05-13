#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 11:28:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
from fastapi import FastAPI

#pylint: disable=wrong-import-position, wrong-import-order
import models
from modules import helpers
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'

app = FastAPI()

APP_SOURCE = models.init_app_sources()
APP_SESSIONS = models.APP_SESSIONS


@app.get("/version")
async def get_version() -> dict[str, str]:
    return { 'status': helpers.StatusFunction.SUCCESS.name, 'version': APP_SOURCE.get('version'), 'error': '' }


@app.get("/get_active_games")
async def get_active_games() -> dict[str, str | int]:
    return { 'status': helpers.StatusFunction.SUCCESS.name, 'active_games': len(APP_SESSIONS), 'error': '' }


@app.post("/create_game_session")
async def create_game_session(lang: str, game_mode: str, word_lenght: int, max_tries: int) -> dict [str, str]:
    try:
        game_session = models.create_game_session(APP_SOURCE.get(lang, {}).get('pre_computed', {}).get(str(word_lenght), {}).get('lang_launcher'),
                                                  game_mode, max_tries)
        APP_SESSIONS.update({game_session['session_uuid']: game_session})
        return { 'status': helpers.StatusFunction.SUCCESS.name, 'session_uuid': game_session['session_uuid'], 'error': '' }

    except Exception as err:
        return { 'status': helpers.StatusFunction.ERROR.name, 'error': repr(err) }

# fastapi dev main.py
