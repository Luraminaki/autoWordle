# CHANGELOG

- 0.3.1: Backend hardening and frontend polish.
  Every API route is now rate-limited per client IP (`DEFAULT_RATE_LIMIT_PER_MINUTE`,
  default 60/min), with a stricter dedicated limit on `POST /precompute`
  (`PRECOMPUTE_RATE_LIMIT_PER_MINUTE`, default 5/min) since a build can run
  for minutes of real CPU time - see [ARCHITECTURE](README.md#architecture).
  `precompute_jobs.sqlite` now prunes finished (`done`/`failed`) rows older
  than an hour, mirroring the existing session-expiry purge pattern, instead
  of accumulating them for the life of the process. The frontend gained a
  manual light/dark/auto theme toggle (persisted in `localStorage`, stacked
  on top of the existing `prefers-color-scheme` detection) and a PWA
  manifest + icon for installability (no offline support - the app still
  needs the backend for everything it does) - see
  [PLAYING THE GAME](README.md#playing-the-game). `api.js` also now surfaces
  the server's actual error detail (e.g. a 429's message) instead of a bare
  `HTTP <code>` for any non-2xx response.
- 0.3.0: Frontend - a full pure JS/HTML/CSS web UI (no framework, no build
  step) covering all three game modes, session persistence with a
  resume-by-ID fallback for browsers that clear `localStorage` on close, an
  in-browser trigger for the `POST /precompute` build with live progress,
  and a QWERTY/AZERTY on-screen keyboard toggle - see
  [PLAYING THE GAME](README.md#playing-the-game). `main.py` now serves
  `frontend/` directly instead of a leftover `frontend/.output/public/`
  convention from before the "no build tooling" decision.
  `reset_game_session` now returns the freshly-reset session state
  (`session_stats`) directly instead of requiring a separate
  `get_game_session_stats` call afterward, closing a window where a network
  hiccup between the two could leave a client's view of a session out of
  sync with the server post-reset.
  `create_game_session` now purges expired sessions before checking the
  `MAX_SESSIONS` cap, same as `get_active_games` already did - previously
  only `get_active_games` triggered that cleanup, so the cap could reject a
  new session based on others that were already expired but not yet swept.
  The running version is now read from installed package metadata
  (`importlib.metadata`) instead of being duplicated in `config.json`.
  Also fixes a Windows-only bug where `word_codec.save_words_information`
  wrote CSV rows with doubled line endings (missing `newline=''`),
  corrupting `*_info.csv` sidecars on that platform.
- 0.2.2: Exhaustive-data precomputation can now be triggered on demand
  through the API (`POST /precompute`) instead of only at process startup or
  via a manual CLI command, with live progress/ETA over Server-Sent Events
  (`GET /precompute_progress`) - see [THE SOLVER](README.md#the-solver).
- 0.2.0: Backend refresh - package restructure, Pydantic-based API contracts,
  several bugfixes (see below), SQLite/multiprocessing optimizations, ruff
  linting, a real pytest suite, `pyproject.toml` packaging, real `logging`
  (rotating file + console) instead of bare `print()`, and SQLite-backed
  session persistence (survives restarts, safe across multiple workers)
  instead of a process-local in-memory dict.
  Pattern-compendium precomputation now streams straight to the
  SQLite cache instead of materializing the full `O(n**2)` compendium in
  memory first, and computes each guess's patterns against the whole pool as
  a batch of vectorized numpy array operations instead of one Python call per
  pair - ~10x lower peak RSS and ~2x faster at real dictionary scale (see
  [THE SOLVER](README.md#the-solver)). Also fixes a scoring bug in
  `compute_pattern` for guesses with a repeated letter where one occurrence
  is an exact match (e.g. guessing "jelly" against "allay" incorrectly
  scored the second "l" as black instead of yellow) - existing precomputed
  sidecars need regenerating.
- 0.1.0-alpha: First release