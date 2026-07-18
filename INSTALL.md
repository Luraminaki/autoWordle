# INSTALL

autoWordle is a plain Python (FastAPI) backend. It's packaged with a standard
`pyproject.toml` and installed with the stdlib `venv` + `pip` - no extra
tooling (uv, Poetry, ...) required.

Requires **Python 3.12+**.

<!-- TOC -->

- [INSTALL](#install)
  - [Windows](#windows)
  - [Linux (Debian / Ubuntu)](#linux-debian--ubuntu)
  - [Linux (Arch)](#linux-arch)
  - [Running the app](#running-the-app)
  - [config.json reference](#configjson-reference)
  - [Running the tests](#running-the-tests)
  - [Regenerating solver data for a new language/word length](#regenerating-solver-data-for-a-new-languageword-length)

<!-- /TOC -->

Two install options below, and every OS section shows both:
- `pip install -e .` - just the app itself (FastAPI, numpy, etc.) - all you
  need to **run** the game.
- `pip install -e ".[dev]"` - adds `ruff`/`pytest`/`pytest-cov`/`httpx` on
  top - only needed if you're going to **run the tests or lint** (see
  [Running the tests](#running-the-tests)). Skip it if you just want to play.

## Windows

1. Install Python 3.12+ from [python.org](https://www.python.org/downloads/windows/) (check "Add python.exe to PATH" in the installer).
2. From the repository root, in PowerShell or `cmd.exe`:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   # Or, to also be able to run tests/lint: pip install -e ".[dev]"
   ```

## Linux (Debian / Ubuntu)

Debian/Ubuntu split `venv` out of the base `python3` package, so install it explicitly first:

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
# Or, to also be able to run tests/lint: pip install -e ".[dev]"
```

## Linux (Arch)

Arch's `python` package already bundles `venv`:

```bash
sudo pacman -S python python-pip

python -m venv .venv
source .venv/bin/activate
pip install -e .
# Or, to also be able to run tests/lint: pip install -e ".[dev]"
```

## Running the app

From the repository root, with the virtual environment activated:

```bash
uvicorn autoWordle.main:app --reload --port 10000
```

Then open **http://127.0.0.1:10000/** in a browser to play - the same
`uvicorn` process serves the frontend directly, nothing else to start or
build. See [PLAYING THE GAME](README.md#playing-the-game) in the README for
how the web UI itself works.

**`--reload` is for development only** - it watches source files and
restarts the process on every change, which forces a single worker process
and adds file-watching overhead you don't want under real traffic. For
production, drop it and add `--workers` instead (sized to available CPU
cores), and bind explicitly with `--host 0.0.0.0` - uvicorn otherwise
defaults to `127.0.0.1` (loopback-only), which isn't reachable from outside
the machine/container it's running on:

```bash
uvicorn autoWordle.main:app --host 0.0.0.0 --port 10000 --workers 4
```

The app reads `config.json` and the `data/` folder relative to the current
working directory by default - run it from the repository root. To run it
from elsewhere (or point it at a different config/data location entirely),
set `AUTOWORDLE_APP_ROOT`:

```bash
AUTOWORDLE_APP_ROOT=/path/to/autoWordle uvicorn autoWordle.main:app --port 10000
```

The API is served under `/api/app/...` (see `autoWordle/webapp/api_views.py`); interactive
docs are available at `/docs` once the app is running.

## config.json reference

Validated by `autoWordle/app/schemas.py`'s `AppConfig` - an invalid or
incomplete `config.json` fails fast at startup rather than falling back to
silent defaults for a *required* key. The version number is deliberately
**not** here - it's read from installed package metadata instead (see
[VERSION](README.md#version)).

| Key | Type | Required? | Description |
| --- | --- | --- | --- |
| `service_id` | string | **Required** | Arbitrary identifier for this deployment/instance. Not read anywhere else in the app yet - reserved for future use (e.g. distinguishing instances in logs/metrics). |
| `logging_level` | string | **Required** | Root logging level: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, or `"CRITICAL"` (see `app/logging_utils.py`). |
| `data_folder` | string | **Required** | Path, relative to the app root, where word lists (`*.txt`) and generated solver/session data live, e.g. `"data/"`. |
| `MAX_SESSIONS` | integer (> 0) | **Required** | Maximum concurrent game sessions before `POST /create_game_session` starts rejecting new ones. |
| `SESSION_TTL_SECONDS` | integer (> 0) | **Required** | Inactivity timeout, in seconds, after which a session is garbage-collected (30 min in the shipped config). |
| `DEFAULT_RATE_LIMIT_PER_MINUTE` | integer (> 0) | Optional (default `60`) | Per-client-IP request budget for the API as a whole (see [ARCHITECTURE](README.md#architecture)). |
| `PRECOMPUTE_RATE_LIMIT_PER_MINUTE` | integer (> 0) | Optional (default `5`) | Stricter per-client-IP budget specifically for `POST /precompute`, since a build can run for minutes of real CPU time. |
| `default_word_lengths` | list of integers | Optional (default `[5]`) | Word length(s) every language always gets a plain, `GAME_MODE_PLAY`-capable word list built for at startup, regardless of whether exhaustive solver data has been precomputed for that length yet. |

Exhaustive solver data for a new language/length is always built via an
explicit `POST /precompute` (or the "Build solver data" button), never
automatically at startup - see
[Regenerating solver data](#regenerating-solver-data-for-a-new-languageword-length).

## Running the tests

Requires the `[dev]` extras (`pip install -e ".[dev]"` - see above) if you
only installed the base package so far.

```bash
pytest
```

Tests run against a tiny synthetic word list (`tests/data/mini.txt`) and never
touch the real `data/` folder or its precomputed sidecar files.

Ruff (lint) can be run with:

```bash
ruff check .
```

## Regenerating solver data for a new language/word length

The repository ships with precomputed exhaustive solver data
(`data/wordle_5_compendium.sqlite` + `data/wordle_5_info.csv`) for the
bundled 5-letter `wordle.txt` answer list only - that's what powers the
"best opening word" suggestion and `GAME_MODE_SOLVE`/`GAME_MODE_ASSISTED`.
`en.txt`/`fr.txt` are large general dictionaries meant for `GAME_MODE_PLAY`
only; computing exhaustive data for them is `O(n**2)` in the word count and
deliberately **not** triggered automatically (it would mean several minutes
and multiple gigabytes of RAM on first boot for a dictionary that size).

The easiest way to build it is from the running app itself: picking
Solve/Assisted for a language/word length that doesn't have it yet shows a
"Build solver data" button on the setup screen, with a live progress bar -
no command line needed.

The CLI below runs the same underlying build - useful for scripting, or for
precomputing ahead of time without opening a browser. Run it once per
word list/length (slow the first time, then cached on disk):

```bash
python -c "from autoWordle.modules import helpers; helpers.LangLauncher('data/<file>.txt', compute_best_opening=True, word_length=<N>)"
```

This produces `data/<file>_<N>_compendium.sqlite` and `data/<file>_<N>_info.csv`;
once present, the app picks them up automatically on the next start.
