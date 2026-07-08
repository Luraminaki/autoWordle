#!/usr/bin/env python3
"""FastAPI application factory.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from fastapi import FastAPI, staticfiles
from fastapi.middleware.cors import CORSMiddleware

from autoWordle.app import logging_utils, paths, schemas


def _configure_logging() -> None:
    """Configure logging from `config.json`'s `logging_level`, before `api_views` is imported.

    `webapp.api_views` builds its module-level `APP_SOURCES` (which loads
    every language's word list, and can trigger the whole solver-data
    precomputation pipeline) as soon as it's imported - logging must already
    be configured by then, or those log records get emitted before any
    handler exists to catch them.
    """
    app_root = paths.get_app_root()
    conf = schemas.AppConfig.model_validate(paths.load_json_config(app_root / 'config.json'))
    logging_utils.configure_logging(level=conf.logging_level)


def create_app() -> FastAPI:
    """Build the FastAPI application: API router first, then static frontend mount.

    Returns:
        FastAPI: The configured application.
    """
    _configure_logging()

    # Deferred: importing `api_views` triggers its module-level `APP_SOURCES`
    # load, which must happen after `_configure_logging()` above.
    from autoWordle.webapp import api_views

    fastapi_app = FastAPI(title='autoWordle', description='Wordle / Motus solver game web app.')

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    frontend_dir = paths.get_app_root() / 'frontend' / '.output' / 'public'

    # MUST be in that specific order, else it doesn't work
    fastapi_app.include_router(api_views.route)
    if frontend_dir.is_dir():
        fastapi_app.mount('/', staticfiles.StaticFiles(directory=frontend_dir, html=True), name='autoWordle')

    return fastapi_app


app = create_app()

# fastapi dev autoWordle/main.py
