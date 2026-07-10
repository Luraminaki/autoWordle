#!/usr/bin/env python3
"""Core Pydantic domain models: app configuration, app sources, and session metadata.

These are the models `autoWordle.app.models` itself depends on, independent of
any web transport. HTTP request/response contracts for the FastAPI routes live
in the companion `webapp.api_schemas` module instead.

Hot-path, high-cardinality internal structures (word/pattern tuples, pattern
compendia, candidate pools in `modules.computing`) are deliberately kept as
plain tuples/dicts/sets rather than modeled here: they never cross a
serialization boundary individually and wrapping them in Pydantic would add
per-item validation overhead for millions of entries with no contract benefit.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import pathlib

from pydantic import BaseModel, ConfigDict, Field

from autoWordle.modules import statics
from autoWordle.modules.helpers import LangLauncher


class AppConfig(BaseModel):
    """Validated shape of `config.json`.

    Deliberately has no `version` field - that's not user-configurable, it's
    a fact about which code is installed, so it's read from package metadata
    instead (`paths.get_app_version`) rather than duplicated here.
    """

    model_config = ConfigDict(populate_by_name=True)

    service_id: str
    logging_level: str
    data_folder: str
    compute_best_opening: bool = False
    max_sessions: int = Field(alias='MAX_SESSIONS', gt=0)
    session_ttl_seconds: int = Field(alias='SESSION_TTL_SECONDS', gt=0)
    # Word lengths a `LangLauncher` is always built for, on top of any
    # already precomputed (`*_info.csv`-marked) lengths discovered on disk.
    # Without this, a fresh install with no precomputed sidecars yet would
    # never build a `LangLauncher` for any language at all - not even for
    # GAME_MODE_PLAY, which needs nothing but the plain word list.
    default_word_lengths: tuple[int, ...] | list[int] = Field(default_factory=lambda: [5])


class PrecomputedEntry(BaseModel):
    """A single word-length's precomputed solver data for one language.

    Only ever built via `init_app_sources(client=False)`, where
    `lang_launcher` is always a real `LangLauncher` (or `None`) - never a
    string placeholder, unlike `PrecomputedEntryClient`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: pathlib.Path
    length: int
    lang_launcher: LangLauncher | None = None
    has_exhaustive_data: bool = False


class LangSource(BaseModel):
    """One language's word list plus any precomputed solver data."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: pathlib.Path
    pre_computed: dict[str, PrecomputedEntry] = Field(default_factory=dict)


class AppSources(BaseModel):
    """Full in-process application state assembled at startup."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: AppConfig
    langs: dict[str, LangSource]
    game_modes: dict[str, str]


class PrecomputedEntryClient(BaseModel):
    """Client-safe (JSON-serializable) view of `PrecomputedEntry`."""

    path: str
    length: int
    lang_launcher: str
    has_exhaustive_data: bool = False


class LangSourceClient(BaseModel):
    """Client-safe (JSON-serializable) view of `LangSource`."""

    path: str
    pre_computed: dict[str, PrecomputedEntryClient] = Field(default_factory=dict)


class AppSourcesClientView(BaseModel):
    """Client-safe (JSON-serializable) view of `AppSources`, returned by `/get_app_sources`."""

    config: AppConfig
    langs: dict[str, LangSourceClient]
    game_modes: dict[str, str]


# ------------------------------------------------------------------ session state


class GameSessionMeta(BaseModel):
    """JSON-serializable metadata for a single game session.

    The live, mutable solving state (`modules.wordle.Wordle` instance) is kept
    out of this model and stored alongside it on `models.GameSession` instead,
    since it holds large sets/tuples that must not be copied or re-validated
    on every mutation.

    `lang`/`word_length` identify which `LangLauncher` the session's `Wordle`
    instance was built against - needed by `app.session_store` to look up the
    right (already-loaded) `LangLauncher` from `AppSources` when rehydrating a
    session from storage, since that live object itself is never persisted.
    """

    session_uuid: str
    lang: str
    word_length: int = Field(gt=0)
    game_mode: statics.GameMode
    max_tries: int = Field(gt=0)
    current_tries: int = 0
    guesses: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    created_timestamp: int
    last_active_timestamp: int


class GuessStats(BaseModel):
    """Elimination/solver statistics computed for one guess.

    Returned by `models.get_guess_stats`; shaped into the
    `webapp.api_schemas.GuessStatsResponse` HTTP response by the route handler.
    """

    pool_words: list[dict[str, float]] = Field(default_factory=list)
    pool_letters: list[str] = Field(default_factory=list)
    pool_letters_dupes: dict[str, int] = Field(default_factory=dict)
    elimination_suggestions: dict[int, list[dict[str, float]]] = Field(default_factory=dict)
    # The single highest-entropy next guess (`wordle.Wordle.best_guesses[0]`) -
    # pool-only while the pool is still large, full-dictionary-vs-current-pool
    # once it's small enough to be worth the extra cost (see
    # `wordle._FULL_SCAN_POOL_THRESHOLD`). Distinct from `elimination_suggestions`,
    # which buckets candidates by unknown-letter coverage for a human to choose
    # between - this is "just tell me the best move" instead.
    best_guess: dict[str, float] | None = None
    information: float = 0.0
