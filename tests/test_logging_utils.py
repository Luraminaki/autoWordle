#!/usr/bin/env python3
"""Tests for `autoWordle.app.logging_utils`."""

#===================================================================================================
import logging
import os
import pathlib
from unittest.mock import MagicMock

from autoWordle.app import logging_utils

#===================================================================================================


def test_reset_logging_clears_handlers_and_filters() -> None:
    root = logging.getLogger()
    root.addHandler(logging.NullHandler())
    root.addFilter(logging.Filter())

    logging_utils.reset_logging()

    assert root.handlers == []
    assert root.filters == []


def test_configure_logging_sets_level_and_handlers(tmp_path: pathlib.Path, monkeypatch: MagicMock) -> None:
    monkeypatch.chdir(tmp_path)

    logging_utils.configure_logging(log_file_stem='test_autowordle', level=logging.DEBUG)

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 2  # rotating file handler + stream handler
    assert (tmp_path / f'test_autowordle.{os.getpid()}.log').is_file()

    logging_utils.reset_logging()


def test_configure_logging_suffixes_filename_with_pid_so_workers_cant_collide(
        tmp_path: pathlib.Path, monkeypatch: MagicMock) -> None:
    # Regression test: stdlib's RotatingFileHandler has no cross-process
    # locking around rollover - two uvicorn workers (separate processes)
    # both pointed at the exact same file could race during rotation, one
    # renaming the file out from under the other and losing/misplacing log
    # lines. Suffixing with the process's own PID means two different
    # "workers" (simulated here via monkeypatched os.getpid) always resolve
    # to two different files, so that race can't happen.
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(logging_utils.os, 'getpid', lambda: 11111)
    logging_utils.configure_logging(log_file_stem='test_autowordle')
    logging_utils.reset_logging()

    monkeypatch.setattr(logging_utils.os, 'getpid', lambda: 22222)
    logging_utils.configure_logging(log_file_stem='test_autowordle')
    logging_utils.reset_logging()

    assert (tmp_path / 'test_autowordle.11111.log').is_file()
    assert (tmp_path / 'test_autowordle.22222.log').is_file()


def test_configure_logging_accepts_string_level(tmp_path: pathlib.Path, monkeypatch: MagicMock) -> None:
    monkeypatch.chdir(tmp_path)

    logging_utils.configure_logging(log_file_stem='test_autowordle', level='WARNING')

    assert logging.getLogger().level == logging.WARNING

    logging_utils.reset_logging()


def test_configure_logging_is_idempotent(tmp_path: pathlib.Path, monkeypatch: MagicMock) -> None:
    monkeypatch.chdir(tmp_path)

    logging_utils.configure_logging(log_file_stem='test_autowordle')
    logging_utils.configure_logging(log_file_stem='test_autowordle')

    assert len(logging.getLogger().handlers) == 2

    logging_utils.reset_logging()
