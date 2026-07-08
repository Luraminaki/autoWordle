#!/usr/bin/env python3
"""FastAPI routes for the autoWordle solver/game API.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from fastapi import APIRouter

from autoWordle.app import models, paths, session_store
from autoWordle.modules import statics
from autoWordle.webapp import api_schemas

route = APIRouter(prefix='/api/app', tags=['API'])

APP_SOURCES = models.init_app_sources()
SESSION_STORE = session_store.SessionStore(paths.get_app_root() / APP_SOURCES.config.data_folder / 'sessions.sqlite', APP_SOURCES)


@route.get('/version')
async def get_version() -> api_schemas.VersionResponse:
    """Report the running application version."""
    return api_schemas.VersionResponse(status=statics.StatusFunction.SUCCESS, version=APP_SOURCES.config.version)


@route.get('/get_active_games')
async def get_active_games() -> api_schemas.ActiveGamesResponse:
    """Garbage-collect expired sessions and report how many are still active."""
    try:
        _ = SESSION_STORE.delete_expired(APP_SOURCES.config.session_ttl_seconds)
        active_games = SESSION_STORE.count()

    except Exception as err:
        return api_schemas.ActiveGamesResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.ActiveGamesResponse(status=statics.StatusFunction.SUCCESS, active_games=active_games)


@route.get('/get_app_sources')
async def get_app_sources() -> api_schemas.AppSourcesResponse:
    """Report available languages/word lengths and their solver capabilities."""
    try:
        client_sources = models.init_app_sources(client=True)

    except Exception as err:
        return api_schemas.AppSourcesResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.AppSourcesResponse(status=statics.StatusFunction.SUCCESS, app_sources=client_sources)


@route.post('/create_game_session')
async def create_game_session(request: api_schemas.CreateGameSessionRequest) -> api_schemas.CreateGameSessionResponse:
    """Create a new game session."""
    try:
        if SESSION_STORE.count() >= APP_SOURCES.config.max_sessions:
            return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.ERROR, error='MAX_SESSIONS limit reached')

        lang = request.lang.lower()
        lang_source = APP_SOURCES.langs.get(lang)
        precomputed = lang_source.pre_computed.get(str(request.word_length)) if lang_source else None
        lang_launcher = precomputed.lang_launcher if precomputed else None

        session = models.create_game_session(lang, request.word_length, lang_launcher, request.game_mode, request.max_tries)
        SESSION_STORE.save(session)

    except Exception as err:
        return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.SUCCESS, session_uuid=session.meta.session_uuid)


@route.post('/reset_game_session')
async def reset_game_session(request: api_schemas.ResetGameSessionRequest) -> api_schemas.StatusResponse:
    """Reset an existing game session to a fresh state."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        models.reset_game_session(session, request.game_mode, request.max_tries)
        SESSION_STORE.save(session)

    except Exception as err:
        return api_schemas.StatusResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.StatusResponse(status=statics.StatusFunction.SUCCESS)


@route.post('/delete_game_session')
async def delete_game_session(request: api_schemas.DeleteGameSessionRequest) -> api_schemas.StatusResponse:
    """Delete a game session."""
    try:
        SESSION_STORE.delete(request.session_uuid)

    except Exception as err:
        return api_schemas.StatusResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.StatusResponse(status=statics.StatusFunction.SUCCESS)


@route.post('/get_game_session_stats')
async def get_game_session_stats(request: api_schemas.GameSessionStatsRequest) -> api_schemas.GameSessionStatsResponse:
    """Report a session's current metadata (mode, tries, guesses, patterns, timestamps)."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        stats = models.get_game_session_stats(session)

    except Exception as err:
        return api_schemas.GameSessionStatsResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.GameSessionStatsResponse(status=statics.StatusFunction.SUCCESS, session_stats=stats)


@route.post('/get_word_to_guess')
async def get_word_to_guess(request: api_schemas.WordToGuessRequest) -> api_schemas.WordToGuessResponse:
    """Reveal the word to guess for a session (solve/assisted modes)."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        word = models.get_word_to_guess(session)

    except Exception as err:
        return api_schemas.WordToGuessResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.WordToGuessResponse(status=statics.StatusFunction.SUCCESS, word=word)


@route.post('/get_guess_stats')
async def get_guess_stats(request: api_schemas.GuessStatsRequest) -> api_schemas.GuessStatsResponse:
    """Compute elimination/solver statistics for a guess and its resulting pattern."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        stats = models.get_guess_stats(session, request.word, request.pattern)
        SESSION_STORE.save(session)

    except Exception as err:
        return api_schemas.GuessStatsResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.GuessStatsResponse(status=statics.StatusFunction.SUCCESS, guess_stats=stats)


@route.post('/submit_guess')
async def submit_guess(request: api_schemas.SubmitGuessRequest) -> api_schemas.SubmitGuessResponse:
    """Submit a guess against a session's hidden word."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        if (pattern := models.submit_guess(session, request.word)) is None:
            return api_schemas.SubmitGuessResponse(status=statics.StatusFunction.ERROR, error=f'INVALID_WORD {request.word}')

        SESSION_STORE.save(session)

    except Exception as err:
        return api_schemas.SubmitGuessResponse(status=statics.StatusFunction.ERROR, error=repr(err))

    return api_schemas.SubmitGuessResponse(status=statics.StatusFunction.SUCCESS, pattern=pattern)

# fastapi dev autoWordle/main.py
