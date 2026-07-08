#!/usr/bin/env python3
"""Session and application-state management.

Pure display-formatting helpers (converting internal shifted-ordinal data
into JSON-friendly output) live in the companion `display` module instead.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import dataclasses
import logging
import pathlib
import time
import uuid
from typing import Literal, overload

from autoWordle.app import display, paths, schemas
from autoWordle.modules import computing, helpers, statics, wordle

logger = logging.getLogger(__name__)


class GameSessionNotAllowedError(ValueError):
    """Raised when a game session cannot be created for the requested language/mode."""


@dataclasses.dataclass
class GameSession:
    """A live game session: JSON-serializable metadata plus the running solver state.

    `game` is kept as a plain attribute (not a Pydantic field) because
    `modules.wordle.Wordle` holds large mutable sets/tuples that must not be
    copied or re-validated on every guess.
    """

    meta: schemas.GameSessionMeta
    game: wordle.Wordle


APP_SESSIONS: dict[str, GameSession] = {}


@overload
def init_app_sources(app_root: pathlib.Path | None = None, client: Literal[False] = False) -> schemas.AppSources: ...
@overload
def init_app_sources(app_root: pathlib.Path | None = None, *, client: Literal[True]) -> schemas.AppSourcesClientView: ...
def init_app_sources(app_root: pathlib.Path | None = None, client: bool = False) -> schemas.AppSources | schemas.AppSourcesClientView:
    """Load `config.json` and every available language's word list / solver data.

    `client` picks not just the runtime values but the returned Pydantic
    *type*: `client=False` (default) returns `AppSources`, whose
    `PrecomputedEntry.lang_launcher` is always a real `LangLauncher` (or
    `None`) - never a string placeholder, so callers like
    `create_game_session` don't need to account for a case that can't happen
    on this path. `client=True` returns the distinct, JSON-serializable
    `AppSourcesClientView` instead (string placeholders throughout, no live
    objects), suitable for exposing to a frontend.

    Args:
        app_root: Directory `config.json` and the configured data folder are
            resolved relative to. Defaults to `paths.get_app_root()`.
        client: When `True`, build the JSON-serializable client view instead.

    Returns:
        schemas.AppSources | schemas.AppSourcesClientView: Assembled
        application configuration and sources.
    """
    app_root = app_root or paths.get_app_root()
    conf = schemas.AppConfig.model_validate(paths.load_json_config(app_root / 'config.json'))

    data_folder = app_root / conf.data_folder
    # Plain word lists are ``*.txt``; a completed exhaustive precomputation for
    # a given (language, word_length) always leaves a ``*_info.csv`` sidecar
    # (see `helpers.save_words_information`/`helpers.get_data_paths`), which is
    # what marks that combination as available. These used to both be sourced
    # from a single ``*.txt`` glob split on "contains an underscore", which
    # never matched anything since no ``.txt`` file is ever named that way -
    # exhaustive data was silently never discovered.
    lang_files = list(data_folder.glob('*.txt'))
    exhaustive_files = list(data_folder.glob('*_info.csv'))

    compute_best_opening = not client if client else conf.compute_best_opening
    langs_raw = helpers.init_lang_app_data(lang_files, exhaustive_files, conf.default_word_lengths,
                                           compute_best_opening=compute_best_opening,
                                           client=client)
    game_modes = {mode.name: mode.value for mode in statics.GameMode}

    if client:
        client_langs = {lang: schemas.LangSourceClient.model_validate(source) for lang, source in langs_raw.items()}
        return schemas.AppSourcesClientView(config=conf, langs=client_langs, game_modes=game_modes)

    langs = {lang: schemas.LangSource.model_validate(source) for lang, source in langs_raw.items()}
    return schemas.AppSources(config=conf, langs=langs, game_modes=game_modes)


def create_game_session(lang: str, word_length: int, lang_launcher: helpers.LangLauncher | None,
                        game_mode: statics.GameMode, max_tries: int = 6) -> GameSession:
    """Create a new game session.

    Args:
        lang: Language the session is played in - recorded on the session so
            it can be rehydrated from storage later (see
            `app.session_store`), since the live `lang_launcher` itself isn't
            persisted.
        word_length: Word length the session is played at.
        lang_launcher: Loaded solver data for `lang`/`word_length`, or `None`
            if that combination isn't available.
        game_mode: Requested game mode.
        max_tries: Maximum number of guesses allowed.

    Returns:
        GameSession: The newly created session.

    Raises:
        GameSessionNotAllowedError: If `lang_launcher` is unavailable, or if
            `game_mode` requires exhaustive solver data `lang_launcher` doesn't have.
    """
    if lang_launcher is None:
        raise GameSessionNotAllowedError('No solver data available for the requested language/word length')

    # Not every LangLauncher has exhaustive data even when the app-wide
    # `compute_best_opening` config flag is on - it's only computed/loaded
    # for language/length combinations explicitly precomputed on disk (see
    # `helpers.init_lang_app_data`), so this must be checked per-launcher.
    if not lang_launcher.words_information and game_mode != statics.GameMode.GAME_MODE_PLAY:
        raise GameSessionNotAllowedError(f'{game_mode.value} requires exhaustive solver data for this language/length')

    session_uuid = str(uuid.uuid4())
    now = int(time.time())

    logger.info("Creating game_session %s", session_uuid)

    meta = schemas.GameSessionMeta(session_uuid=session_uuid, lang=lang, word_length=word_length,
                                  game_mode=game_mode, max_tries=max_tries,
                                  created_timestamp=now, last_active_timestamp=now)

    return GameSession(meta=meta, game=wordle.Wordle(lang_launcher))


def reset_game_session(session: GameSession, game_mode: statics.GameMode, max_tries: int = 6) -> None:
    """Reset a game session to a fresh state, keeping its `session_uuid`.

    Args:
        session: Session to reset.
        game_mode: New game mode.
        max_tries: New maximum number of guesses allowed.
    """
    session.game.reset()
    session.meta.game_mode = game_mode
    session.meta.max_tries = max_tries
    session.meta.current_tries = 0
    session.meta.guesses = []
    session.meta.patterns = []
    session.meta.last_active_timestamp = int(time.time())


def get_game_session_stats(session: GameSession) -> schemas.GameSessionMeta:
    """Return a session's current metadata.

    Args:
        session: Session to inspect.

    Returns:
        schemas.GameSessionMeta: The session's metadata.
    """
    return session.meta


def get_word_to_guess(session: GameSession) -> str:
    """Reveal the word to guess for a session (solve/assisted modes).

    Args:
        session: Session to inspect.

    Returns:
        str: The word to guess.
    """
    return ''.join(chr(ord_letter + session.game.shift) for ord_letter in session.game.word)


def get_guess_stats(session: GameSession, word: str, pattern: str) -> schemas.GuessStats | None:
    """Compute elimination/solver statistics for a guess and its resulting pattern.

    Only records the guess into `session.meta.guesses`/`patterns` in
    `GAME_MODE_SOLVE` - the only mode where `submit_guess` isn't also called
    for the same guess (see `submit_guess`'s docstring), so recording it here
    too would double it.

    Args:
        session: Session to update.
        word: Guessed word.
        pattern: Emoji pattern resulting from the guess.

    Returns:
        schemas.GuessStats | None: Solver statistics, or `None` in
        `GAME_MODE_PLAY` (no solver assistance) or if the guess/pattern leaves
        no remaining candidate words.
    """
    if session.meta.game_mode == statics.GameMode.GAME_MODE_PLAY:
        return None

    game = session.game
    t_word = tuple(ord(letter) - game.shift for letter in word)
    t_pattern = tuple(int(letter_status) for letter_status in statics.emoji_to_pattern(pattern))

    pool = game.submit_guess_and_pattern(t_word, t_pattern)
    if pool is None:
        return None

    game.letter_extractor = computing.update_letter_extractor(game.letter_extractor,
                                                              computing.build_letter_extractor(t_word, t_pattern))
    pool_letters, pool_letters_dupes = computing.gather_pool_letters(pool)
    suggestions = computing.build_suggestion(game.language_launcher.words_information,
                                             pool_letters, pool_letters_dupes, game.letter_extractor)

    if session.meta.game_mode == statics.GameMode.GAME_MODE_SOLVE:
        session.meta.guesses.append(word)
        session.meta.patterns.append(pattern)
        session.meta.last_active_timestamp = int(time.time())

    return schemas.GuessStats(pool_words=display.convert_pool_words(pool, game.shift),
                              pool_letters=display.convert_pool_letters(pool_letters, game.shift),
                              pool_letters_dupes=display.convert_pool_letters_dupes(pool_letters_dupes, game.shift),
                              elimination_suggestions=display.convert_elimination_suggestions(suggestions, game.shift),
                              information=game.information)


def submit_guess(session: GameSession, word: str) -> str | None:
    """Submit a guess against a session's hidden word.

    Args:
        session: Session to update.
        word: Guessed word.

    Returns:
        str | None: The resulting emoji pattern, or `None` if the session has
        no tries left or the guess is invalid.

    Raises:
        GameSessionNotAllowedError: If the session is in `GAME_MODE_SOLVE`.
            That mode is for solving an *external* puzzle, where the pattern
            comes from outside (passed directly to `get_guess_stats`) rather
            than from comparison against `session.game.word` - a random
            internal word irrelevant to the external puzzle. Without this
            guard, calling both endpoints for the same guess in
            `GAME_MODE_SOLVE` would both compute a meaningless pattern here
            *and* double-record the guess (this function always appends to
            `guesses`/`patterns`; `get_guess_stats` also does, but only for
            `GAME_MODE_SOLVE` specifically, since it's the only endpoint
            meant to record guesses in that mode).
    """
    if session.meta.game_mode == statics.GameMode.GAME_MODE_SOLVE:
        raise GameSessionNotAllowedError('submit_guess is not valid in GAME_MODE_SOLVE - use get_guess_stats instead')

    if session.meta.current_tries >= session.meta.max_tries:
        return None

    t_pattern = session.game.submit_guess(tuple(ord(letter) - session.game.shift for letter in word))

    if not t_pattern:
        return None

    pattern = statics.pattern_to_emoji(t_pattern)

    session.meta.guesses.append(word)
    session.meta.patterns.append(pattern)
    session.meta.current_tries += 1
    session.meta.last_active_timestamp = int(time.time())

    return pattern
