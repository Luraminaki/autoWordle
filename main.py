#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 11:28:51 2024

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

#===================================================================================================
from fastapi import FastAPI, staticfiles
from fastapi.middleware.cors import CORSMiddleware

#pylint: disable=wrong-import-position, wrong-import-order
import api_views
#pylint: enable=wrong-import-position, wrong-import-order
#===================================================================================================

__version__ = '0.1.0'


def create_app():
    webapp = FastAPI(title="autoWordle", description="Wordle / Motus solver game web app written in VUE 3 and Python 3.")

    webapp.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # MUST be in that specific order, else it doesn't work
    webapp.include_router(api_views.route)
    webapp.mount("/",
                 staticfiles.StaticFiles(directory="frontend/.output/public", html=True),
                 name="autoWordle")

    return webapp


app = create_app()

# fastapi dev main.py
