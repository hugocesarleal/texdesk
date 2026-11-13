# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Rotas HTTP, uma área por módulo."""

from . import compile, drive, files, github, pages, projects, tools

BLUEPRINTS = [pages.bp, projects.bp, files.bp, compile.bp, drive.bp, github.bp, tools.bp]
