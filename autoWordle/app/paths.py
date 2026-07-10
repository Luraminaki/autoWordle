#!/usr/bin/env python3
"""Application root resolution helpers.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import importlib.metadata
import json
import os
import pathlib

APP_ROOT_ENV_VAR = 'AUTOWORDLE_APP_ROOT'

# Matches `pyproject.toml`'s `[project] name` - the installed distribution's
# metadata is the single source of truth for the running version (see
# `get_app_version`), instead of a second copy hardcoded in `config.json`.
_DISTRIBUTION_NAME = 'autowordle'


def get_app_root() -> pathlib.Path:
    """Resolve the directory ``config.json`` and ``data/`` are read from.

    Checks the ``AUTOWORDLE_APP_ROOT`` environment variable first, so tests and
    non-standard deployments can point elsewhere, and falls back to the current
    working directory otherwise, which preserves the historical "run the app
    from the repository root" behavior.

    Returns:
        pathlib.Path: Resolved, absolute application root directory.
    """
    if env_root := os.environ.get(APP_ROOT_ENV_VAR):
        return pathlib.Path(env_root).expanduser().resolve()

    return pathlib.Path.cwd()


def load_json_config(path: pathlib.Path) -> dict:
    """Read and parse a JSON config file.

    Args:
        path (pathlib.Path): Path to the JSON file.

    Returns:
        dict: Parsed JSON content.

    Raises:
        FileNotFoundError: If `path` doesn't point to an existing file.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    return json.loads(path.read_text(encoding='utf-8'))


def get_app_version() -> str:
    """Resolve the running application's version from installed package metadata.

    Reads `pyproject.toml`'s `[project] version` back via the installed
    distribution's metadata rather than duplicating the number a second time
    in `config.json`, where it could silently drift out of sync on a bump.

    Returns:
        str: The installed version, or a placeholder if the package isn't
        installed (e.g. running straight from a checkout without
        `pip install -e .`).
    """
    try:
        return importlib.metadata.version(_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return '0.0.0-dev'
