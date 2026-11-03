# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Compilação, arquivos gerados (PDF) e SyncTeX."""

from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

from .. import services
from ..compiler import compile_project, inputs_fingerprint, load_last, save_last
from ..config import OUTPUT, TECTONIC
from ..storage import compile_target, load_settings, project_dir, project_lock, safe_path, save_settings
from ..synctex import SyncTex

bp = Blueprint("compile", __name__)


@bp.post("/api/projects/<name>/compile")
def compile_route(name):
    d = project_dir(name)
    s = load_settings(d)
    body = request.get_json(silent=True) or {}
    main = body.get("main") or s["main"]
    # compila o documento aberto no editor; "main" guarda o último compilado, para o PDF,
    # o SyncTeX e a miniatura seguirem o mesmo documento
    if not body.get("main") and body.get("open"):
        main = compile_target(d, s["main"], body["open"])
        if main != s["main"]:
            s["main"] = main
            save_settings(d, s)
            services.changed(name)
    main_path = safe_path(d, main)
    if not main_path.is_file():
        return jsonify(
            {"status": "failure", "message": f"Documento principal '{main}' não encontrado", "entries": [], "log": ""}
        )
    if not TECTONIC.exists():
        return jsonify(
            {
                "status": "failure",
                "entries": [],
                "log": "",
                "message": "Tectonic não instalado. Rode setup.ps1 (Windows) ou setup.sh (Linux/macOS).",
            }
        )
    lock = project_lock(name)
    if not lock.acquire(timeout=5):
        return jsonify({"status": "busy", "message": "Já existe uma compilação em andamento", "entries": []})
    try:
        shell_escape = bool(s.get("shellEscape"))
        # antes de compilar: o que mudar durante a compilação conta como mudança depois
        fingerprint = inputs_fingerprint(d, main, shell_escape)
        result = compile_project(d, name, main, main_path, shell_escape) | {"main": main}
        save_last(name, main, fingerprint, result)
        return jsonify(result)
    finally:
        lock.release()


@bp.get("/api/projects/<name>/compiled")
def last_compiled(name):
    """Ao abrir o editor: o PDF e os logs da última compilação, se nada mudou desde então.

    Assim quem compilou, fechou e voltou não espera outra compilação. Se algum arquivo,
    o documento principal ou o shell-escape mudou, responde {"fresh": false} e o editor compila.
    """
    d = project_dir(name)
    s = load_settings(d)
    main = compile_target(d, s["main"], request.args.get("open", ""))
    last = load_last(d, name, main, bool(s.get("shellEscape")))
    return jsonify(last | {"fresh": True} if last else {"fresh": False})


@bp.get("/api/projects/<name>/output/<path:fname>")
def output_file(name, fname):
    project_dir(name)
    p = safe_path(OUTPUT / name, fname)
    if not p.is_file():
        abort(404)
    resp = send_file(p)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _synctex(name):
    d = project_dir(name)
    s = load_settings(d)
    f = OUTPUT / name / (Path(s["main"]).stem + ".synctex.gz")
    if not f.exists():
        abort(404, "Compile o projeto primeiro")
    return SyncTex(f, d, (d / s["main"]).parent)


@bp.get("/api/projects/<name>/synctex/code")
def synctex_code(name):
    """PDF -> código (clique duplo no PDF)."""
    r = _synctex(name).edit(int(request.args["page"]), float(request.args["x"]), float(request.args["y"]))
    return jsonify(r or {})


@bp.get("/api/projects/<name>/synctex/pdf")
def synctex_pdf(name):
    """Código -> PDF (ir para a posição no PDF)."""
    return jsonify(_synctex(name).view(request.args["file"], int(request.args["line"])))
