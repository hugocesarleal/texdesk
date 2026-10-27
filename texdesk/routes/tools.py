# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Ferramentas do editor: busca no projeto, contagem de palavras e histórico de versões."""

import re

from flask import Blueprint, abort, jsonify, request

from .. import history, services, spell, texttools
from ..security import json_body
from ..storage import load_settings, project_dir, safe_path

bp = Blueprint("tools", __name__)


@bp.get("/api/projects/<name>/search")
def search(name):
    d = project_dir(name)
    q = request.args.get("q", "")
    if not q:
        return jsonify({"results": [], "truncated": False})
    flag = lambda k: request.args.get(k) == "1"  # noqa: E731
    try:
        return jsonify(texttools.search(d, q, case=flag("case"), regex=flag("regex"), word=flag("word")))
    except re.error as e:
        abort(400, f"Expressão regular inválida: {e}")


@bp.get("/api/projects/<name>/wordcount")
def word_count(name):
    d = project_dir(name)
    main = request.args.get("main") or load_settings(d).get("main") or "main.tex"
    safe_path(d, main)
    return jsonify(texttools.word_count(d, main))


@bp.get("/api/projects/<name>/history")
def list_versions(name):
    project_dir(name)
    return jsonify(history.list_versions(name))


@bp.post("/api/projects/<name>/history")
def save_version(name):
    d = project_dir(name)
    label = (json_body().get("label") or "").strip()
    if not label:
        abort(400, "Dê um nome para a versão")
    sid = history.snapshot(d, name, label=label, auto=False)
    return jsonify({"id": sid})


def _version(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        abort(404, "Versão ou arquivo não encontrado")


@bp.get("/api/projects/<name>/history/<sid>")
def compare_version(name, sid):
    return jsonify(_version(history.compare, project_dir(name), name, sid))


@bp.get("/api/projects/<name>/history/<sid>/diff")
def diff_version(name, sid):
    d = project_dir(name)
    path = request.args.get("path", "")
    safe_path(d, path)
    return jsonify(_version(history.file_diff, d, name, sid, path))


@bp.post("/api/projects/<name>/history/<sid>/restore")
def restore_version(name, sid):
    d = project_dir(name)
    path = json_body().get("path") or None
    if path:
        safe_path(d, path)
    restored = _version(history.restore, d, name, sid, path)
    services.changed(name)
    return jsonify({"restored": restored})


@bp.post("/api/spell")
def spell_check():
    data = json_body()
    try:
        return jsonify({"unknown": spell.unknown(data.get("lang", ""), data.get("words") or [])})
    except spell.SpellError as e:
        abort(400, str(e))


@bp.get("/api/spell/suggest")
def spell_suggest():
    try:
        return jsonify(spell.suggestions(request.args.get("lang", ""), request.args.get("word", "")))
    except spell.SpellError as e:
        abort(400, str(e))
