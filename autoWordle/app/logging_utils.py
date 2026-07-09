#!/usr/bin/env python3
"""Shared logging setup for the app and its dev/benchmark scripts.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import logging
from logging.handlers import RotatingFileHandler

_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5


def reset_logging() -> None:
    """Remove every handler/filter from the root logger.

    Called before (re)configuring logging, so repeated calls - e.g. across
    test runs, or a script that gets imported more than once - don't stack
    duplicate handlers and duplicate every log line.
    """
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for log_filter in root.filters[:]:
        root.removeFilter(log_filter)


def configure_logging(log_file_stem: str = 'autoWordle', level: int | str = logging.INFO,
                      max_bytes: int = _DEFAULT_MAX_BYTES, backup_count: int = _DEFAULT_BACKUP_COUNT) -> None:
    """Configure root logging once: a rotating file handler plus console output.

    Format includes `%(funcName)s`, so callers no longer need the
    `inspect.currentframe().f_code.co_name` dance the codebase used to do
    just to log which function a message came from.

    Args:
        log_file_stem (str): Stem for the rotating log file (`<stem>.log`, `.log.1`, ...).
        level (int | str): Logging level for the root logger, as an int or a level name (e.g. `"INFO"`).
        max_bytes (int): Size a log file may reach before it rotates.
        backup_count (int): Number of rotated log files to keep.
    """
    reset_logging()

    logging.basicConfig(
        level=level,
        format='[%(asctime)s] [%(process)s] [%(name)s] [%(levelname)s]: %(funcName)s -- %(message)s',
        handlers=[
            RotatingFileHandler(f'{log_file_stem}.log', mode='a', maxBytes=max_bytes,
                                backupCount=backup_count, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
