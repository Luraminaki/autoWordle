#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 11:28:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
import json
import pathlib
from fastapi import FastAPI

#pylint: disable=wrong-import-position, wrong-import-order
import models
from modules import helpers
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


CWD = pathlib.Path.cwd()

DATA_FOLDER = 'data/'
CONFIG_FILE = 'config.json'

with open(CWD/CONFIG_FILE, encoding='utf-8') as f:
    conf = json.load(f)

DATA_FILES = pathlib.Path(CWD/DATA_FOLDER).glob('*.txt')
LANG_FILES: list[pathlib.Path] = []
EXHAUSTIVE_FILES: list[pathlib.Path] = []

for file in DATA_FILES:
    if '_' not in file.name:
        LANG_FILES.append(file)

    else:
        EXHAUSTIVE_FILES.append(file)

APP_SOURCES = helpers.init_lang_app_data(LANG_FILES, EXHAUSTIVE_FILES)

app = FastAPI()


@app.get("/version")
async def get_version() -> dict[str, str]:
    return {'version': __version__}
