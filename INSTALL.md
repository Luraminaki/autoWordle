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
  - [Running the tests](#running-the-tests)
  - [Regenerating solver data for a new language/word length](#regenerating-solver-data-for-a-new-languageword-length)

<!-- /TOC -->

## Windows

1. Install Python 3.12+ from [python.org](https://www.python.org/downloads/windows/) (check "Add python.exe to PATH" in the installer).
2. From the repository root, in PowerShell or `cmd.exe`:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

## Linux (Debian / Ubuntu)

Debian/Ubuntu split `venv` out of the base `python3` package, so install it explicitly first:

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Linux (Arch)

Arch's `python` package already bundles `venv`:

```bash
sudo pacman -S python python-pip

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the app

From the repository root, with the virtual environment activated:

```bash
uvicorn autoWordle.main:app --reload
```

The app reads `config.json` and the `data/` folder relative to the current
working directory by default - run it from the repository root. To run it
from elsewhere (or point it at a different config/data location entirely),
set `AUTOWORDLE_APP_ROOT`:

```bash
AUTOWORDLE_APP_ROOT=/path/to/autoWordle uvicorn autoWordle.main:app
```

The API is served under `/api/app/...` (see `autoWordle/webapp/api_views.py`); interactive
docs are available at `/docs` once the app is running.

## Running the tests

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

To precompute exhaustive data for a different word list/length, run once
(this is slow the first time, then cached on disk):

```bash
python -c "from autoWordle.modules import helpers; helpers.LangLauncher('data/<file>.txt', compute_best_opening=True, word_length=<N>)"
```

This produces `data/<file>_<N>_compendium.sqlite` and `data/<file>_<N>_info.csv`;
once present, the app picks them up automatically on the next start.
