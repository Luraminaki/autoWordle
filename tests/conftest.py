#!/usr/bin/env python3
"""Shared pytest fixtures: a tiny synthetic app root/word list, and a test API client."""

#===================================================================================================
import json
import pathlib
import shutil

import pytest

#===================================================================================================

MINI_WORDS_FILE = pathlib.Path(__file__).parent / 'data' / 'mini.txt'


@pytest.fixture
def mini_words_file() -> pathlib.Path:
    """Path to the small synthetic 5-letter word list used across tests."""
    return MINI_WORDS_FILE


@pytest.fixture
def test_app_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A throwaway app root (config.json + data/) pointed at the mini word list.

    Never touches the real `data/` folder or its multi-hundred-MB precomputed
    sidecar files - everything here builds fresh, fast, from ~20 words.
    """
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _ = shutil.copy(MINI_WORDS_FILE, data_dir / 'mini.txt')

    config = {
        'service_id': 'wordle-test',
        'version': '0.0.0-test',
        'logging_level': 'INFO',
        'data_folder': 'data/',
        'compute_best_opening': False,
        'MAX_SESSIONS': 5,
        'SESSION_TTL_SECONDS': 1800,
        'default_word_lengths': [5],
    }
    _ = (tmp_path / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    return tmp_path


@pytest.fixture
def client(test_app_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """A `TestClient` for the app, wired to `test_app_root` instead of the real repo data.

    `webapp.api_views` builds its module-level `APP_SOURCES`/`SESSION_STORE`
    once at import time; rather than evicting and re-importing `autoWordle.*`
    (which leaves duplicate module objects around and breaks
    `ProcessPoolExecutor`'s pickling identity checks for anything already
    imported by another test module), just swap those two globals directly.
    `SESSION_STORE` points at a throwaway sqlite file under `test_app_root`,
    never the real one. `AUTOWORDLE_APP_ROOT` is also set so routes that
    rebuild sources on every call (`/get_app_sources`) resolve to
    `test_app_root` too.
    """
    from fastapi.testclient import TestClient

    from autoWordle.app import models, session_store
    from autoWordle.main import app
    from autoWordle.webapp import api_views

    monkeypatch.setenv('AUTOWORDLE_APP_ROOT', str(test_app_root))
    test_app_sources = models.init_app_sources(app_root=test_app_root)
    monkeypatch.setattr(api_views, 'APP_SOURCES', test_app_sources)
    monkeypatch.setattr(api_views, 'SESSION_STORE', session_store.SessionStore(test_app_root / 'sessions.sqlite', test_app_sources))

    return TestClient(app)
