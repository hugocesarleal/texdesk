# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Projetos: lista, modelos, criar, importar/exportar .zip, renomear, duplicar, excluir."""
import io
import json
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, request, send_file

from .. import drive_sync, services
from ..config import OUTPUT, PROJECTS, SETTINGS_FILE, TEMPLATE_META, TEMPLATES, THUMB_FILE
from ..security import json_body
from ..storage import is_hidden, load_settings, png_size, project_dir, safe_path, save_settings, valid_name

bp = Blueprint("projects", __name__)


@bp.get("/api/projects")
def list_projects():
    items = []
    for d in PROJECTS.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        mtime = max((p.stat().st_mtime for p in d.rglob("*")
                     if p.is_file() and p.name not in (THUMB_FILE, SETTINGS_FILE, drive_sync.MANIFEST)),
                    default=d.stat().st_mtime)
        thumb = d / THUMB_FILE
        settings = load_settings(d)
        pdf = OUTPUT / d.name / (Path(settings["main"]).stem + ".pdf")
        tw, th = png_size(thumb)
        items.append({
            "name": d.name, "modified": mtime,
            "thumb": thumb.stat().st_mtime if thumb.exists() else None,
            "thumbW": tw, "thumbH": th,
            "pdf": pdf.stat().st_mtime if pdf.exists() else None,
            "pdfUrl": f"/api/projects/{quote(d.name)}/output/{quote(pdf.name)}" if pdf.exists() else None,
            "drive": services.syncer.get_status(d.name) if settings["driveSync"] else None,
        })
    items.sort(key=lambda x: -x["modified"])
    return jsonify(items)


@bp.get("/api/templates")
def list_templates():
    out = []
    for p in TEMPLATES.iterdir():
        if not p.is_dir():
            continue
        meta = {}
        try:
            meta = json.loads((p / TEMPLATE_META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        out.append({"id": p.name, "name": meta.get("name", p.name), "description": meta.get("description", ""),
                    "order": meta.get("order", 99), "source": meta.get("source")})
    out.sort(key=lambda t: (t["order"], t["name"]))
    return jsonify(out)


@bp.post("/api/projects")
def create_project():
    data = json_body()
    name = (data.get("name") or "").strip()
    if not valid_name(name):
        abort(400, "Nome inválido (use letras, números, espaço, - _ .)")
    d = PROJECTS / name
    if d.exists():
        abort(409, "Já existe um projeto com esse nome")
    tpl = TEMPLATES / (data.get("template") or "blank")
    if tpl.is_dir() and TEMPLATES in tpl.resolve().parents:
        shutil.copytree(tpl, d, ignore=shutil.ignore_patterns(TEMPLATE_META))
    else:
        d.mkdir()
        (d / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nOlá, mundo!\n\\end{document}\n",
                                    encoding="utf-8")
    services.apply_sync_default(d)
    return jsonify({"name": name})


@bp.post("/api/projects/upload")
def upload_project():
    f = request.files.get("file")
    if not f:
        abort(400, "Nenhum arquivo")
    name = (request.form.get("name") or Path(f.filename).stem).strip()
    if not valid_name(name):
        abort(400, "Nome inválido")
    d = PROJECTS / name
    if d.exists():
        abort(409, "Já existe um projeto com esse nome")
    with zipfile.ZipFile(io.BytesIO(f.read())) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        # se tudo estiver dentro de uma única pasta, remove esse prefixo
        prefix = ""
        tops = {n.split("/")[0] for n in z.namelist()}
        if len(tops) == 1 and all("/" in n for n in names):
            prefix = tops.pop() + "/"
        d.mkdir()
        try:
            for n in names:
                rel = n[len(prefix):]
                if not rel or rel.startswith("__MACOSX"):
                    continue
                target = safe_path(d, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(n))
        except Exception:
            shutil.rmtree(d, ignore_errors=True)  # .zip com caminho inválido não deixa projeto pela metade
            raise
    (d / drive_sync.MANIFEST).unlink(missing_ok=True)
    services.apply_sync_default(d)
    return jsonify({"name": name})


@bp.delete("/api/projects/<name>")
def delete_project(name):
    d = project_dir(name)
    shutil.rmtree(d)
    shutil.rmtree(OUTPUT / name, ignore_errors=True)
    services.syncer.forget(name)  # a cópia no Drive é mantida; pode ser restaurada pelo painel
    return jsonify({"ok": True})


@bp.post("/api/projects/<name>/rename")
def rename_project(name):
    d = project_dir(name)
    new = (json_body().get("name") or "").strip()
    if not valid_name(new):
        abort(400, "Nome inválido")
    if (PROJECTS / new).exists():
        abort(409, "Já existe um projeto com esse nome")
    d.rename(PROJECTS / new)
    if (OUTPUT / name).exists():
        (OUTPUT / name).rename(OUTPUT / new)
    services.syncer.forget(name)
    services.changed(new)  # renomeia a pasta no Drive
    return jsonify({"name": new})


@bp.post("/api/projects/<name>/clone")
def clone_project(name):
    d = project_dir(name)
    new = (json_body().get("name") or "").strip()
    if not valid_name(new) or (PROJECTS / new).exists():
        abort(400, "Nome inválido ou já existente")
    shutil.copytree(d, PROJECTS / new)
    # a cópia é um projeto novo: não pode apontar para a mesma pasta do Drive
    (PROJECTS / new / drive_sync.MANIFEST).unlink(missing_ok=True)
    services.changed(new)
    return jsonify({"name": new})


@bp.get("/api/projects/<name>/zip")
def download_zip(name):
    d = project_dir(name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in d.rglob("*"):
            rel = p.relative_to(d)
            if p.is_file() and not is_hidden(rel):
                z.write(p, rel.as_posix())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"{name}.zip")


@bp.get("/api/projects/<name>/settings")
def get_settings(name):
    return jsonify(load_settings(project_dir(name)))


@bp.post("/api/projects/<name>/settings")
def set_settings(name):
    d = project_dir(name)
    s = load_settings(d)
    data = json_body()
    for k in ("main", "autoCompile", "shellEscape", "driveSync"):
        if k in data:
            s[k] = data[k]
    if s["main"]:
        safe_path(d, s["main"])
    save_settings(d, s)
    services.changed(name)
    return jsonify(s)


@bp.get("/api/projects/<name>/thumbnail")
def get_thumbnail(name):
    f = project_dir(name) / THUMB_FILE
    if not f.exists():
        abort(404)
    resp = send_file(f, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=31536000"  # a URL leva ?v=mtime
    return resp


@bp.post("/api/projects/<name>/thumbnail")
def put_thumbnail(name):
    """Miniatura da 1ª página, renderizada pelo navegador (PDF.js) após compilar."""
    d = project_dir(name)
    data = request.get_data()
    if not data.startswith(b"\x89PNG") or len(data) > 2_000_000:
        abort(400, "PNG inválido")
    (d / THUMB_FILE).write_bytes(data)
    return jsonify({"ok": True})
