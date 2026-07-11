#!/usr/bin/env python3
"""FastAPI routes for the autoWordle solver/game API.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from autoWordle.app import models, paths, precompute_store, rate_limiter, session_store
from autoWordle.modules import statics
from autoWordle.webapp import api_schemas

logger = logging.getLogger(__name__)

# Client-facing message for any *unexpected* exception - the real exception
# (type, message, args, which can include internal file paths or other
# implementation detail) is logged server-side via `logger.exception` instead
# of being handed to the caller, unlike the specific, safe-to-expose error
# strings used elsewhere in this module (e.g. `'INVALID_WORD ...'`).
_INTERNAL_ERROR = 'INTERNAL_ERROR'

APP_SOURCES = models.init_app_sources()
SESSION_STORE = session_store.SessionStore(paths.get_app_root() / APP_SOURCES.config.data_folder / 'sessions.sqlite', APP_SOURCES)
PRECOMPUTE_STORE = precompute_store.PrecomputeJobStore(paths.get_app_root() / APP_SOURCES.config.data_folder / 'precompute_jobs.sqlite')

# Server-side poll interval for the SSE progress stream below - the client
# never polls (a single long-lived EventSource connection), this is only how
# often the generator re-reads the shared, multi-worker-safe job store.
_PROGRESS_POLL_INTERVAL_SECONDS = 1.0

DEFAULT_RATE_LIMITER = rate_limiter.RateLimiter(limit=APP_SOURCES.config.default_rate_limit_per_minute, window_seconds=60.0)
PRECOMPUTE_RATE_LIMITER = rate_limiter.RateLimiter(limit=APP_SOURCES.config.precompute_rate_limit_per_minute, window_seconds=60.0)


def _client_key(request: Request) -> str:
    # Not `X-Forwarded-For`-aware: trusting that header without a declared
    # trusted-proxy configuration would let a client spoof its own rate-limit
    # key. Fine for this project's direct-exposure deployment model.
    return request.client.host if request.client else 'unknown'


def _rate_limit(request: Request, limiter: rate_limiter.RateLimiter) -> None:
    if not limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail='Too many requests - please slow down and try again shortly.')


def rate_limit_default(request: Request) -> None:
    """Router-wide default rate limit dependency."""
    _rate_limit(request, DEFAULT_RATE_LIMITER)


def rate_limit_precompute(request: Request) -> None:
    """Stricter rate limit dependency for the expensive `/precompute` route."""
    _rate_limit(request, PRECOMPUTE_RATE_LIMITER)


route = APIRouter(prefix='/api/app', tags=['API'], dependencies=[Depends(rate_limit_default)])


@route.get('/version')
async def get_version() -> api_schemas.VersionResponse:
    """Report the running application version."""
    return api_schemas.VersionResponse(status=statics.StatusFunction.SUCCESS, version=paths.get_app_version())


@route.get('/get_active_games')
async def get_active_games() -> api_schemas.ActiveGamesResponse:
    """Garbage-collect expired sessions and report how many are still active."""
    try:
        _ = SESSION_STORE.delete_expired(APP_SOURCES.config.session_ttl_seconds)
        active_games = SESSION_STORE.count()

    except Exception:
        logger.exception("Failed to get active games")
        return api_schemas.ActiveGamesResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.ActiveGamesResponse(status=statics.StatusFunction.SUCCESS, active_games=active_games)


@route.get('/get_app_sources')
async def get_app_sources() -> api_schemas.AppSourcesResponse:
    """Report available languages/word lengths and their solver capabilities."""
    try:
        client_sources = models.init_app_sources(client=True)

    except Exception:
        logger.exception("Failed to get app sources")
        return api_schemas.AppSourcesResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.AppSourcesResponse(status=statics.StatusFunction.SUCCESS, app_sources=client_sources)


@route.post('/create_game_session')
async def create_game_session(request: api_schemas.CreateGameSessionRequest) -> api_schemas.CreateGameSessionResponse:
    """Create a new game session."""
    try:
        # Purge expired sessions before counting, same as get_active_games -
        # without this, the cap is checked against whatever's in the table
        # regardless of staleness, so it only reflects genuinely live sessions
        # by accident (only if some other client happened to call
        # get_active_games recently). Making this call self-sufficient means
        # the cap is correct no matter what any other endpoint was called.
        _ = SESSION_STORE.delete_expired(APP_SOURCES.config.session_ttl_seconds)

        if SESSION_STORE.count() >= APP_SOURCES.config.max_sessions:
            return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.ERROR, error='MAX_SESSIONS limit reached')

        lang = request.lang.lower()
        lang_source = APP_SOURCES.langs.get(lang)
        precomputed = lang_source.pre_computed.get(str(request.word_length)) if lang_source else None
        lang_launcher = precomputed.lang_launcher if precomputed else None

        session = models.create_game_session(lang, request.word_length, lang_launcher, request.game_mode, request.max_tries)
        SESSION_STORE.save(session)

    except Exception:
        logger.exception("Failed to create game session")
        return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.CreateGameSessionResponse(status=statics.StatusFunction.SUCCESS, session_uuid=session.meta.session_uuid)


@route.post('/reset_game_session')
async def reset_game_session(request: api_schemas.ResetGameSessionRequest) -> api_schemas.ResetGameSessionResponse:
    """Reset an existing game session to a fresh state."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        models.reset_game_session(session, request.game_mode, request.max_tries)
        SESSION_STORE.save(session)

    except Exception:
        logger.exception("Failed to reset game session")
        return api_schemas.ResetGameSessionResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.ResetGameSessionResponse(status=statics.StatusFunction.SUCCESS, session_stats=session.meta)


@route.post('/delete_game_session')
async def delete_game_session(request: api_schemas.DeleteGameSessionRequest) -> api_schemas.StatusResponse:
    """Delete a game session."""
    try:
        SESSION_STORE.delete(request.session_uuid)

    except Exception:
        logger.exception("Failed to delete game session")
        return api_schemas.StatusResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.StatusResponse(status=statics.StatusFunction.SUCCESS)


@route.post('/get_game_session_stats')
async def get_game_session_stats(request: api_schemas.GameSessionStatsRequest) -> api_schemas.GameSessionStatsResponse:
    """Report a session's current metadata (mode, tries, guesses, patterns, timestamps)."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        stats = models.get_game_session_stats(session)

    except Exception:
        logger.exception("Failed to get game session stats")
        return api_schemas.GameSessionStatsResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.GameSessionStatsResponse(status=statics.StatusFunction.SUCCESS, session_stats=stats)


@route.post('/get_word_to_guess')
async def get_word_to_guess(request: api_schemas.WordToGuessRequest) -> api_schemas.WordToGuessResponse:
    """Reveal the word to guess for a session (solve/assisted modes)."""
    try:
        session = SESSION_STORE.load(request.session_uuid)
        if session is None:
            raise KeyError(request.session_uuid)

        word = models.get_word_to_guess(session)

    except Exception:
        logger.exception("Failed to get word to guess")
        return api_schemas.WordToGuessResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

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

    except Exception:
        logger.exception("Failed to get guess stats")
        return api_schemas.GuessStatsResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

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

    except Exception:
        logger.exception("Failed to submit guess")
        return api_schemas.SubmitGuessResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.SubmitGuessResponse(status=statics.StatusFunction.SUCCESS, pattern=pattern)


@route.post('/precompute', dependencies=[Depends(rate_limit_precompute)])
async def precompute(request: api_schemas.PrecomputeRequest, background_tasks: BackgroundTasks) -> api_schemas.PrecomputeResponse:
    """Trigger (or join) an exhaustive-data build for a language/word length.

    Returns immediately - `should_start` in the underlying job-store result
    decides whether *this* request is the one that actually schedules the
    (potentially multi-minute) build as a background task; a duplicate
    request for the same, already-running/queued combination just reports
    its current status instead of starting a second one.
    """
    try:
        # Purge finished job rows before doing anything else, same lazy-purge
        # pattern as create_game_session's SESSION_STORE.delete_expired call -
        # otherwise DONE/FAILED rows accumulate in precompute_jobs.sqlite forever.
        _ = PRECOMPUTE_STORE.prune_finished(precompute_store.FINISHED_RETENTION_SECONDS)

        lang = request.lang.lower()
        result = models.request_precompute(APP_SOURCES, PRECOMPUTE_STORE, lang, request.word_length)

        if result.should_start:
            background_tasks.add_task(models.run_precompute_job, APP_SOURCES, PRECOMPUTE_STORE, lang, request.word_length)

    except models.PrecomputeNotAllowedError as err:
        return api_schemas.PrecomputeResponse(status=statics.StatusFunction.ERROR, error=str(err))

    except Exception:
        logger.exception("Failed to request precompute")
        return api_schemas.PrecomputeResponse(status=statics.StatusFunction.ERROR, error=_INTERNAL_ERROR)

    return api_schemas.PrecomputeResponse(status=statics.StatusFunction.SUCCESS,
                                          job_status=result.status, queue_position=result.position)


def _precompute_progress_payload(job: precompute_store.PrecomputeJobStatus) -> dict:
    """Build one SSE payload for a job's current status.

    Split out from the generator below so it's a plain function a test can
    call directly with a synthetic `job`, instead of only being reachable by
    fully draining a live SSE stream - which, for a job that's QUEUED and
    never resolves, never terminates.

    Args:
        job (precompute_store.PrecomputeJobStatus): The job to describe.

    Returns:
        dict: JSON-serializable payload for this job's SSE event.
    """
    payload = {'status': job.status.value, 'fraction_done': job.fraction_done,
              'eta_seconds': job.eta_seconds, 'position': job.position, 'error': job.error}

    # A queued job's own fraction_done/eta_seconds are meaningless
    # placeholders (nothing updates them until it starts running) - surface
    # whichever job *is* currently running instead, so a queued caller sees
    # real, live progress rather than a static screen indistinguishable from
    # a hang.
    if job.status == statics.PrecomputeStatus.QUEUED:
        running = PRECOMPUTE_STORE.get_running_job()
        payload['current_job'] = {
            'lang': running.lang, 'word_length': running.word_length,
            'fraction_done': running.fraction_done, 'eta_seconds': running.eta_seconds,
        } if running else None

    return payload


@route.get('/precompute_progress')
async def precompute_progress(lang: str, word_length: int) -> StreamingResponse:
    """Stream live progress for a precompute job via Server-Sent Events until it finishes.

    The client holds a single `EventSource` connection and never polls;
    the polling happens server-side against the shared, multi-worker-safe
    `PRECOMPUTE_STORE` (see its module docstring) to feed this stream.
    """
    lang_lower = lang.lower()

    async def event_stream():
        while True:
            job = PRECOMPUTE_STORE.get_status(lang_lower, word_length)

            if job is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return

            yield f"data: {json.dumps(_precompute_progress_payload(job))}\n\n"

            if job.status in (statics.PrecomputeStatus.DONE, statics.PrecomputeStatus.FAILED):
                return

            await asyncio.sleep(_PROGRESS_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_stream(), media_type='text/event-stream')

# fastapi dev autoWordle/main.py
