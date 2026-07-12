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

from autoWordle.app import display, paths, precompute_store, schemas
from autoWordle.modules import computing, helpers, statics, word_codec, wordle

logger = logging.getLogger(__name__)


class GameSessionNotAllowedError(ValueError):
    """Raised when a game session cannot be created for the requested language/mode."""


class PrecomputeNotAllowedError(ValueError):
    """Raised when a precompute build is requested for an unknown language."""


class NoTriesRemainingError(ValueError):
    """Raised when `submit_guess` is called on a session with no tries left."""


# Client-facing message for a precompute build failure - the real exception
# (which can include internal file paths, e.g. a PermissionError's repr) is
# logged server-side via `logger.exception` instead, same policy as
# `webapp.api_views._INTERNAL_ERROR` for unexpected route failures.
_PRECOMPUTE_FAILURE_MESSAGE = 'Build failed - see server logs for details'


@dataclasses.dataclass
class GameSession:
    """A live game session: JSON-serializable metadata plus the running solver state.

    `game` is kept as a plain attribute (not a Pydantic field) because
    `modules.wordle.Wordle` holds large mutable sets/tuples that must not be
    copied or re-validated on every guess.
    """

    meta: schemas.GameSessionMeta
    game: wordle.Wordle


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
        app_root (pathlib.Path | None): Directory `config.json` and the configured data folder are
            resolved relative to. Defaults to `paths.get_app_root()`.
        client (bool): When `True`, build the JSON-serializable client view instead.

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


def refresh_lang_launcher_if_stale(app_sources: schemas.AppSources, lang: str, word_length: int) -> helpers.LangLauncher | None:
    """Look up `(lang, word_length)`'s `LangLauncher`, loading fresh exhaustive data if it now exists on disk.

    `app_sources` is a plain in-memory structure shared across a single
    process, unlike `SESSION_STORE`/`PRECOMPUTE_STORE` (SQLite-backed
    specifically to stay correct across multiple `uvicorn` workers) - a build
    completed by `run_precompute_job` on a *different* worker mutates only
    that worker's own copy, so this worker's `app_sources` never learns about
    it on its own. Rather than re-scanning the whole data folder and
    re-parsing every language's word list on every request (what
    `init_app_sources` does) to catch that, this does exactly one cheap
    `Path.exists()` check for the specific combination being asked about, and
    only pays the cost of actually loading it if that check indicates
    something changed - `LangLauncher.compute_words_information` itself loads
    the existing sidecar rather than recomputing it, since the marker file
    already exists by the time this calls it.

    Args:
        app_sources (schemas.AppSources): Shared, mutable application sources.
        lang (str): Language stem.
        word_length (int): Word length.

    Returns:
        helpers.LangLauncher | None: The (possibly freshly loaded) launcher,
        or `None` if `lang` isn't known at all.
    """
    lang_source = app_sources.langs.get(lang)
    if lang_source is None:
        return None

    precomputed = lang_source.pre_computed.get(str(word_length))
    if precomputed is not None and precomputed.lang_launcher is not None and precomputed.lang_launcher.words_information:
        return precomputed.lang_launcher  # already loaded with real exhaustive data - fast path, no disk I/O

    lang_path = precomputed.path if precomputed is not None else lang_source.path
    _, words_information_file = word_codec.get_data_paths(lang_path, word_length)

    if not words_information_file.exists():
        # Nothing new on disk either - return whatever's already loaded (a
        # bare, PLAY-only launcher for this length, or None).
        return precomputed.lang_launcher if precomputed is not None else None

    logger.info("Detected exhaustive data for %s/%d built elsewhere - loading it", lang, word_length)
    fresh_launcher = helpers.LangLauncher(lang_path, compute_best_opening=True, word_length=word_length)
    app_sources.langs[lang].pre_computed[str(word_length)] = schemas.PrecomputedEntry(
        path=lang_path, length=word_length, lang_launcher=fresh_launcher, has_exhaustive_data=True)
    return fresh_launcher


def build_client_view(app_sources: schemas.AppSources) -> schemas.AppSourcesClientView:
    """Build the client-safe view directly from the already-loaded `app_sources`.

    Used by `GET /get_app_sources` instead of a fresh `init_app_sources(client=True)`
    call, which re-globs the data folder and re-parses every language's word
    list from scratch on every single request - real, if not hot-path,
    redundant work for state that's already resident in memory. Each already-known
    combination is refreshed on-demand first (see `refresh_lang_launcher_if_stale`),
    so a build completed by a different worker still becomes visible without
    a restart - only a brand new *language* (a `.txt` file dropped in while
    the app is running) needs a restart to be discovered, same as before.

    Args:
        app_sources (schemas.AppSources): Shared, mutable application sources.

    Returns:
        schemas.AppSourcesClientView: JSON-serializable view (string
        placeholders throughout, no live objects).
    """
    for lang, lang_source in app_sources.langs.items():
        for word_length_str in list(lang_source.pre_computed):
            _ = refresh_lang_launcher_if_stale(app_sources, lang, int(word_length_str))

    # Built explicitly, not via LangSourceClient.model_validate(lang_source):
    # `pre_computed` entries hold real `LangLauncher` instances here, and
    # Pydantic has no built-in way to coerce those into the client's `str`
    # placeholder field on its own - `init_lang_app_data`'s own client=True
    # branch sidesteps this the same way, by building the placeholder string
    # itself rather than leaning on validation to do it. `.name`, not the
    # full path, for the same reason `init_lang_app_data`'s client branch
    # uses `lang_file.name` - the server's absolute filesystem layout isn't
    # something a client response should expose.
    client_langs = {}
    for lang, lang_source in app_sources.langs.items():
        client_pre_computed = {
            word_length_str: schemas.PrecomputedEntryClient(
                path=entry.path.name, length=entry.length,
                lang_launcher=str(entry.lang_launcher) if entry.lang_launcher is not None else 'None',
                has_exhaustive_data=entry.has_exhaustive_data)
            for word_length_str, entry in lang_source.pre_computed.items()
        }
        client_langs[lang] = schemas.LangSourceClient(path=lang_source.path.name, pre_computed=client_pre_computed)

    return schemas.AppSourcesClientView(config=app_sources.config, langs=client_langs, game_modes=app_sources.game_modes)


def create_game_session(lang: str, word_length: int, lang_launcher: helpers.LangLauncher | None,
                        game_mode: statics.GameMode, max_tries: int = 6) -> GameSession:
    """Create a new game session.

    Args:
        lang (str): Language the session is played in - recorded on the session so
            it can be rehydrated from storage later (see
            `app.session_store`), since the live `lang_launcher` itself isn't
            persisted.
        word_length (int): Word length the session is played at.
        lang_launcher (helpers.LangLauncher | None): Loaded solver data for `lang`/`word_length`, or `None`
            if that combination isn't available.
        game_mode (statics.GameMode): Requested game mode.
        max_tries (int): Maximum number of guesses allowed.

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
        session (GameSession): Session to reset.
        game_mode (statics.GameMode): New game mode.
        max_tries (int): New maximum number of guesses allowed.
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
        session (GameSession): Session to inspect.

    Returns:
        schemas.GameSessionMeta: The session's metadata.
    """
    return session.meta


def get_word_to_guess(session: GameSession) -> str:
    """Reveal the word to guess for a session (solve/assisted modes).

    Args:
        session (GameSession): Session to inspect.

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
        session (GameSession): Session to update.
        word (str): Guessed word.
        pattern (str): Emoji pattern resulting from the guess.

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
    # `game.best_guesses` reflects the *current* pool (pool-only entropy while
    # it's still large, full-dictionary-vs-current-pool entropy once it's
    # small enough - see `wordle.Wordle.submit_guess_and_pattern`), unlike
    # the static, precomputed-once-at-startup `language_launcher.words_information`
    # this used to be fed, which never adapted to the game's actual progress.
    suggestions = computing.build_suggestion(game.best_guesses, pool_letters, pool_letters_dupes, game.letter_extractor)

    if session.meta.game_mode == statics.GameMode.GAME_MODE_SOLVE:
        session.meta.guesses.append(word)
        session.meta.patterns.append(pattern)
        session.meta.last_active_timestamp = int(time.time())

    best_guess = game.best_guesses[0] if game.best_guesses else None

    return schemas.GuessStats(pool_words=display.convert_pool_words(pool, game.shift),
                              pool_letters=display.convert_pool_letters(pool_letters, game.shift),
                              pool_letters_dupes=display.convert_pool_letters_dupes(pool_letters_dupes, game.shift),
                              elimination_suggestions=display.convert_elimination_suggestions(suggestions, game.shift),
                              best_guess=display.convert_best_guess(best_guess, game.shift),
                              information=game.information)


def submit_guess(session: GameSession, word: str) -> str | None:
    """Submit a guess against a session's hidden word.

    Args:
        session (GameSession): Session to update.
        word (str): Guessed word.

    Returns:
        str | None: The resulting emoji pattern, or `None` if the guess is invalid.

    Raises:
        NoTriesRemainingError: If the session already has no tries left. A
            distinct exception rather than folding into the `None` case below
            - the two used to be indistinguishable to callers, so
            `webapp.api_views.submit_guess` always reported both as
            `INVALID_WORD`, telling a player who was simply out of tries that
            their (possibly perfectly valid) word was invalid.
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
        raise NoTriesRemainingError('No tries remaining for this session')

    t_pattern = session.game.submit_guess(tuple(ord(letter) - session.game.shift for letter in word))

    if not t_pattern:
        return None

    pattern = statics.pattern_to_emoji(t_pattern)

    session.meta.guesses.append(word)
    session.meta.patterns.append(pattern)
    session.meta.current_tries += 1
    session.meta.last_active_timestamp = int(time.time())

    return pattern


def request_precompute(app_sources: schemas.AppSources, job_store: precompute_store.PrecomputeJobStore,
                       lang: str, word_length: int) -> precompute_store.PrecomputeRequestResult:
    """Request an exhaustive-data build for `lang`/`word_length`.

    Only validates that `lang` is known - the actual build (in
    `run_precompute_job`) re-reads `app_sources` itself once it actually
    runs, since a queued request might sit for a while before that happens.

    Short-circuits before ever touching `job_store` if `lang`/`word_length`
    already has real exhaustive data loaded. Without this, a request for an
    already-complete combination would still fall through to
    `job_store.request`, which treats a `done` row as reclaimable the same
    as a `failed` one - triggering a pointless (if cheap, since
    `LangLauncher` itself skips recomputing when its sidecar files already
    exist) `running -> done` cycle. The normal UI never causes this (the
    "Build solver data" button is hidden once data is available), but a
    direct API caller could otherwise hit it.

    Args:
        app_sources (schemas.AppSources): Assembled application sources.
        job_store (precompute_store.PrecomputeJobStore): Precompute job store.
        lang (str): Language stem.
        word_length (int): Word length to precompute.

    Returns:
        precompute_store.PrecomputeRequestResult: Current status/queue
        position, and whether the caller should run the build itself.

    Raises:
        PrecomputeNotAllowedError: If `lang` isn't a known language.
    """
    if lang not in app_sources.langs:
        raise PrecomputeNotAllowedError(f'Unknown language {lang!r}')

    # Checks (and refreshes, if another worker finished this build since
    # app_sources was last touched) the live state instead of reading
    # app_sources.langs[...] directly - see refresh_lang_launcher_if_stale.
    lang_launcher = refresh_lang_launcher_if_stale(app_sources, lang, word_length)
    if lang_launcher is not None and lang_launcher.words_information:
        return precompute_store.PrecomputeRequestResult(status=statics.PrecomputeStatus.DONE, position=None, should_start=False)

    return job_store.request(lang, word_length)


def run_precompute_job(app_sources: schemas.AppSources, job_store: precompute_store.PrecomputeJobStore,
                       lang: str, word_length: int) -> None:
    """Build exhaustive data for `lang`/`word_length`, then dispatch the next queued job if any.

    The background body scheduled via `fastapi.BackgroundTasks` by the
    `/precompute` route. Runs as a loop, not recursion - a long queue chained
    through recursive calls would grow the call stack for no reason, since
    this always runs in a thread-pool thread with no caller waiting on it.

    Args:
        app_sources (schemas.AppSources): Shared application sources, mutated in place once a
            build completes - the freshly built `LangLauncher` replaces (or
            creates) `app_sources.langs[lang].pre_computed[str(word_length)]`.
        job_store (precompute_store.PrecomputeJobStore): Precompute job store.
        lang (str): Language stem to build first.
        word_length (int): Word length to build first.
    """
    current: tuple[str, int] | None = (lang, word_length)

    while current is not None:
        current_lang, current_word_length = current

        try:
            lang_file = app_sources.langs[current_lang].path

            def progress_callback(fraction_done: float, eta_seconds: float,
                                  lang: str = current_lang, word_length: int = current_word_length) -> None:
                job_store.update_progress(lang, word_length, fraction_done, eta_seconds)

            new_launcher = helpers.LangLauncher(lang_file, compute_best_opening=True, word_length=current_word_length,
                                                progress_callback=progress_callback)

            app_sources.langs[current_lang].pre_computed[str(current_word_length)] = schemas.PrecomputedEntry(
                path=lang_file, length=current_word_length, lang_launcher=new_launcher)

            current = job_store.mark_done(current_lang, current_word_length)

        except Exception:
            logger.exception("Precompute job failed for %s/%d", current_lang, current_word_length)
            current = job_store.mark_failed(current_lang, current_word_length, _PRECOMPUTE_FAILURE_MESSAGE)
