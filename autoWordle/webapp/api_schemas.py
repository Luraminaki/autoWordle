#!/usr/bin/env python3
"""HTTP request/response contracts for the FastAPI routes in `webapp.api_views`.

Split out from `autoWordle.app.schemas`, which keeps only the core domain
models (`AppConfig`, `AppSources`, `GameSessionMeta`, `GuessStats`, ...) that
`autoWordle.app.models` itself depends on, independent of any web transport.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from pydantic import BaseModel, Field

from autoWordle.app.schemas import AppSourcesClientView, GameSessionMeta, GuessStats
from autoWordle.modules import statics


class StatusResponse(BaseModel):
    """Common envelope shared by every API response."""

    status: statics.StatusFunction
    error: str = ''


class VersionResponse(StatusResponse):
    """Response body for `GET /version`."""

    version: str = ''


class ActiveGamesResponse(StatusResponse):
    """Response body for `GET /get_active_games`."""

    active_games: int = 0


class AppSourcesResponse(StatusResponse):
    """Response body for `GET /get_app_sources`."""

    app_sources: AppSourcesClientView | None = None


class CreateGameSessionRequest(BaseModel):
    """Request body for `POST /create_game_session`."""

    lang: str
    word_length: int = Field(gt=0)
    max_tries: int = Field(gt=0, default=6)
    game_mode: statics.GameMode = statics.GameMode.GAME_MODE_PLAY


class CreateGameSessionResponse(StatusResponse):
    """Response body for `POST /create_game_session`."""

    session_uuid: str | None = None


class ResetGameSessionRequest(BaseModel):
    """Request body for `POST /reset_game_session`."""

    session_uuid: str
    game_mode: statics.GameMode = statics.GameMode.GAME_MODE_PLAY
    max_tries: int = Field(gt=0, default=6)


class ResetGameSessionResponse(StatusResponse):
    """Response body for `POST /reset_game_session`.

    Includes the freshly-reset `session_stats` directly (same shape as
    `GameSessionStatsResponse`) so callers don't need a second
    `get_game_session_stats` round trip just to learn the state their own
    reset request produced - collapsing what would otherwise be two
    sequential calls (with a failure window between them: reset succeeds,
    then the follow-up fetch fails, leaving the caller out of sync) into one.
    """

    session_stats: GameSessionMeta | None = None


class DeleteGameSessionRequest(BaseModel):
    """Request body for `POST /delete_game_session`."""

    session_uuid: str


class GameSessionStatsRequest(BaseModel):
    """Request body for `POST /get_game_session_stats`."""

    session_uuid: str


class GameSessionStatsResponse(StatusResponse):
    """Response body for `POST /get_game_session_stats`."""

    session_stats: GameSessionMeta | None = None


class WordToGuessRequest(BaseModel):
    """Request body for `POST /get_word_to_guess`."""

    session_uuid: str


class WordToGuessResponse(StatusResponse):
    """Response body for `POST /get_word_to_guess`."""

    word: str = ''


class GuessStatsRequest(BaseModel):
    """Request body for `POST /get_guess_stats`."""

    session_uuid: str
    word: str
    pattern: str


class GuessStatsResponse(StatusResponse):
    """Response body for `POST /get_guess_stats`."""

    guess_stats: GuessStats | None = None


class SubmitGuessRequest(BaseModel):
    """Request body for `POST /submit_guess`."""

    session_uuid: str
    word: str


class SubmitGuessResponse(StatusResponse):
    """Response body for `POST /submit_guess`."""

    pattern: str | None = None


class PrecomputeRequest(BaseModel):
    """Request body for `POST /precompute`."""

    lang: str
    word_length: int = Field(gt=0)


class PrecomputeResponse(StatusResponse):
    """Response body for `POST /precompute`."""

    job_status: statics.PrecomputeStatus | None = None
    queue_position: int | None = None
