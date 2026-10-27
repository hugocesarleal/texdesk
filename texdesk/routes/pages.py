# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Páginas: painel de projetos e editor."""

from flask import Blueprint, send_from_directory

from ..config import STATIC
from ..storage import project_dir

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@bp.get("/manifest.webmanifest")
def manifest():
    """Manifesto do aplicativo: o Chrome e o Edge deixam instalar o TexDesk em janela própria."""
    return send_from_directory(STATIC, "manifest.webmanifest", mimetype="application/manifest+json")


@bp.get("/project/<name>")
def editor(name):
    project_dir(name)
    return send_from_directory(STATIC, "editor.html")
