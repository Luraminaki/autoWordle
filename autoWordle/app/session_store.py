#!/usr/bin/env python3
"""SQLite-backed persistent store for game sessions.

Replaces a process-local `dict` for `APP_SESSIONS`: sessions now survive app
restarts, and (thanks to WAL mode + a shared file, the same approach already
proven in `modules.compendium_cache`) work correctly if the app ever runs
behind multiple `uvicorn` workers, since every read/write goes through
SQLite rather than an in-memory cache only one worker would see.

Every operation is a full read-through/write-through round trip (no
in-memory caching layer) - deliberately, so a different worker process
always sees the latest state. Session counts are tiny (`MAX_SESSIONS` is a
handful by default) and reads/writes happen at most once per guess, so this
is not a hot path the way `compendium_cache` is.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import _thread
import dataclasses
import json
import logging
import pathlib
import sqlite3
import time
from threading import Lock

from autoWordle.app import models, schemas
from autoWordle.modules import computing, helpers, word_codec, wordle

logger = logging.getLogger(__name__)


class SessionStore:
    """A SQLite-backed store of `models.GameSession` objects, keyed by `session_uuid`."""

    def __init__(self, db_path: str | pathlib.Path, app_sources: schemas.AppSources) -> None:
        """Open (creating if needed) the session database.

        Args:
            db_path: Path to the SQLite file.
            app_sources: Assembled application sources, used to look up the
                live `LangLauncher` a stored session belongs to by
                `lang`/`word_length` when rehydrating it.
        """
        self.app_sources: schemas.AppSources = app_sources
        self.lock: _thread.LockType = Lock()
        self.db: sqlite3.Connection = sqlite3.connect(str(db_path), timeout=5.0, isolation_level=None, check_same_thread=False)

        with self.lock:
            _ = self.db.execute('PRAGMA journal_mode=WAL')
            _ = self.db.execute('PRAGMA synchronous=NORMAL')
            _ = self.db.execute('PRAGMA busy_timeout=5000')

            with self.db:
                _ = self.db.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_uuid TEXT PRIMARY KEY,
                        lang TEXT NOT NULL,
                        word_length INTEGER NOT NULL,
                        game_mode TEXT NOT NULL,
                        max_tries INTEGER NOT NULL,
                        current_tries INTEGER NOT NULL,
                        guesses TEXT NOT NULL,
                        patterns TEXT NOT NULL,
                        created_timestamp INTEGER NOT NULL,
                        last_active_timestamp INTEGER NOT NULL,
                        word INTEGER NOT NULL,
                        pool_words TEXT NOT NULL,
                        information REAL NOT NULL,
                        letter_extractor TEXT NOT NULL
                    )
                ''')


    def _lang_launcher(self, lang: str, word_length: int) -> helpers.LangLauncher | None:
        """Look up the live `LangLauncher` a stored session belongs to.

        Args:
            lang: Language stem (e.g. `"wordle"`).
            word_length: Word length.

        Returns:
            helpers.LangLauncher | None: The launcher, or `None` if this
            language/length is no longer available (e.g. config changed
            since the session was created).
        """
        lang_source = self.app_sources.langs.get(lang)
        precomputed = lang_source.pre_computed.get(str(word_length)) if lang_source else None
        return precomputed.lang_launcher if precomputed else None


    def save(self, session: models.GameSession) -> None:
        """Persist a session, inserting or overwriting it by `session_uuid`.

        Args:
            session: Session to persist.
        """
        game = session.game
        meta = session.meta

        row = (
            meta.session_uuid, meta.lang, meta.word_length, meta.game_mode.value,
            meta.max_tries, meta.current_tries, json.dumps(meta.guesses), json.dumps(meta.patterns),
            meta.created_timestamp, meta.last_active_timestamp,
            word_codec.tord_to_int(game.word), json.dumps([word_codec.tord_to_int(word) for word in game.pool_words]),
            game.information, json.dumps(dataclasses.asdict(game.letter_extractor)),
        )

        with self.lock, self.db:
            _ = self.db.execute('''
                INSERT INTO sessions (session_uuid, lang, word_length, game_mode, max_tries, current_tries,
                                      guesses, patterns, created_timestamp, last_active_timestamp,
                                      word, pool_words, information, letter_extractor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_uuid) DO UPDATE SET
                    game_mode=excluded.game_mode, max_tries=excluded.max_tries, current_tries=excluded.current_tries,
                    guesses=excluded.guesses, patterns=excluded.patterns, last_active_timestamp=excluded.last_active_timestamp,
                    word=excluded.word, pool_words=excluded.pool_words, information=excluded.information,
                    letter_extractor=excluded.letter_extractor
            ''', row)


    def load(self, session_uuid: str) -> models.GameSession | None:
        """Load a session by `session_uuid`.

        Args:
            session_uuid: Session to load.

        Returns:
            models.GameSession | None: The session, or `None` if it doesn't
            exist, or its language/word length is no longer available.
        """
        with self.lock:
            cursor = self.db.execute('SELECT * FROM sessions WHERE session_uuid = ?', (session_uuid,))
            columns = [description[0] for description in cursor.description]
            row = cursor.fetchone()

        if row is None:
            return None

        record = dict(zip(columns, row, strict=True))

        lang_launcher = self._lang_launcher(record['lang'], record['word_length'])
        if lang_launcher is None:
            logger.warning("Session %s refers to an unavailable language/word_length (%s/%d)",
                          session_uuid, record['lang'], record['word_length'])
            return None

        meta = schemas.GameSessionMeta(
            session_uuid=record['session_uuid'], lang=record['lang'], word_length=record['word_length'],
            game_mode=record['game_mode'], max_tries=record['max_tries'], current_tries=record['current_tries'],
            guesses=json.loads(record['guesses']), patterns=json.loads(record['patterns']),
            created_timestamp=record['created_timestamp'], last_active_timestamp=record['last_active_timestamp'],
        )

        game = wordle.Wordle(lang_launcher)
        game.word = word_codec.tord_from_int(record['word'], record['word_length'])
        game.pool_words = {word_codec.tord_from_int(packed, record['word_length'])
                          for packed in json.loads(record['pool_words'])}
        game.information = record['information']
        # JSON object keys are always strings; `letter_extractor`'s inner
        # dicts are keyed by shifted-ordinal ints, so they need converting back.
        raw_extractor: dict[str, dict[int, int]] = json.loads(record['letter_extractor'])
        game.letter_extractor = computing.LetterExtractor(
            incl={int(letter): count for letter, count in raw_extractor['incl'].items()},
            excl={int(letter): count for letter, count in raw_extractor['excl'].items()})

        return models.GameSession(meta=meta, game=game)


    def delete(self, session_uuid: str) -> None:
        """Delete a session by `session_uuid`. A no-op if it doesn't exist.

        Args:
            session_uuid: Session to delete.
        """
        with self.lock, self.db:
            _ = self.db.execute('DELETE FROM sessions WHERE session_uuid = ?', (session_uuid,))


    def count(self) -> int:
        """Report how many sessions are currently stored.

        Returns:
            int: Number of stored sessions.
        """
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]


    def delete_expired(self, ttl_seconds: int) -> int:
        """Delete every session inactive for at least `ttl_seconds`.

        Args:
            ttl_seconds: Inactivity threshold, in seconds.

        Returns:
            int: Number of sessions deleted.
        """
        now = int(time.time())

        with self.lock, self.db:
            cursor = self.db.execute('DELETE FROM sessions WHERE (? - last_active_timestamp) >= ?', (now, ttl_seconds))
            return cursor.rowcount


    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self.lock:
            self.db.close()
