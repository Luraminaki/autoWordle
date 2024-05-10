#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 11:28:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
from fastapi import FastAPI

#pylint: disable=wrong-import-position, wrong-import-order
import models
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'

app = FastAPI()
APP_SOURCE = models.init_app_sources()

@app.get("/version")
async def get_version() -> dict[str, str]:
    return {'version': APP_SOURCE.get('version')}
