# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Arquivos de um projeto: árvore, ler/gravar, pastas, envio, mover, apagar, autocompletar."""

import re
import shutil
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

from .. import services
from ..security import json_body
from ..storage import is_hidden, is_text, load_settings, project_dir, safe_path, save_settings, tree

bp = Blueprint("files", __name__)


@bp.get("/api/projects/<name>/files")
def list_files(name):
    return jsonify(tree(project_dir(name)))


@bp.get("/api/projects/<name>/file")
def read_file(name):
    d = project_dir(name)
    p = safe_path(d, request.args.get("path"))
    if not p.is_file():
        abort(404, "Arquivo não encontrado")
    if request.args.get("raw"):
        return send_file(p)
    if not is_text(p):
        abort(415, "Arquivo binário")
    return jsonify(
        {
            "path": request.args["path"],
            "content": p.read_text(encoding="utf-8", errors="replace"),
            "mtime": p.stat().st_mtime,
        }
    )


@bp.put("/api/projects/<name>/file")
def write_file(name):
    d = project_dir(name)
    data = json_body()
    p = safe_path(d, data.get("path"))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(data.get("content", ""))
    services.changed(name)
    return jsonify({"ok": True, "mtime": p.stat().st_mtime})


@bp.post("/api/projects/<name>/folder")
def make_folder(name):
    d = project_dir(name)
    safe_path(d, json_body().get("path")).mkdir(parents=True, exist_ok=True)
    services.changed(name)
    return jsonify({"ok": True})


@bp.post("/api/projects/<name>/upload")
def upload_files(name):
    d = project_dir(name)
    folder = (request.form.get("folder") or "").strip("/")
    saved = []
    for f in request.files.getlist("files"):
        rel = (folder + "/" if folder else "") + Path(f.filename).name
        p = safe_path(d, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        f.save(p)
        saved.append(rel)
    services.changed(name)
    return jsonify({"saved": saved})


@bp.post("/api/projects/<name>/move")
def move_file(name):
    d = project_dir(name)
    data = json_body()
    src, dst = safe_path(d, data.get("from")), safe_path(d, data.get("to"))
    if not src.exists():
        abort(404, "Origem não existe")
    if dst.exists():
        abort(409, "Destino já existe")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    s = load_settings(d)
    if s.get("main") == data.get("from"):
        s["main"] = data.get("to")
        save_settings(d, s)
    services.changed(name)
    return jsonify({"ok": True})


@bp.delete("/api/projects/<name>/file")
def delete_file(name):
    d = project_dir(name)
    p = safe_path(d, request.args.get("path"))
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    services.changed(name)
    return jsonify({"ok": True})


@bp.get("/api/projects/<name>/meta")
def project_meta(name):
    """Rótulos (\\label), chaves de citação (.bib) e pacotes usados, para o autocompletar."""
    d = project_dir(name)
    labels, keys, packages = set(), set(), set()
    for p in d.rglob("*"):
        if is_hidden(p.relative_to(d)) or not p.is_file():
            continue
        if p.suffix == ".tex":
            t = p.read_text(encoding="utf-8", errors="ignore")
            labels.update(re.findall(r"\\label\{([^}]+)\}", t))
            for group in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", t):
                packages.update(x.strip() for x in group.split(","))
        elif p.suffix == ".bib":
            t = p.read_text(encoding="utf-8", errors="ignore")
            keys.update(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", t))
    return jsonify({"labels": sorted(labels), "citeKeys": sorted(keys), "packages": sorted(packages)})
