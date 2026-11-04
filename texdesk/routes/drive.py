# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Google Drive: conexão (OAuth), sincronização, projetos no Drive e importação."""

from urllib.parse import quote

from flask import Blueprint, abort, jsonify, redirect, request

from .. import drive_sync, history, merge, services
from ..config import PROJECTS
from ..security import json_body
from ..storage import load_settings, project_dir, safe_path, save_settings, valid_name

bp = Blueprint("drive", __name__)
IN_DRIVE_HISTORY = "A versão do outro computador está no histórico do arquivo no Google Drive."


def _redirect_uri():
    # o Google aceita loopback (127.0.0.1) em qualquer porta para apps instalados
    return f"http://127.0.0.1:{request.host.split(':')[-1]}/api/drive/callback"


# ---------------------------------------------------------------- conexão


@bp.get("/api/drive/status")
def status():
    drive = services.drive
    s = drive.state()
    try:
        configured = drive.client_config() is not None
    except drive_sync.DriveError:
        configured = False
    return jsonify(
        {
            "configured": configured,
            "connected": drive.connected,
            "user": s.get("user"),
            "syncAll": bool(s.get("syncAll")),
            "redirectUri": _redirect_uri(),
            "tokenStorage": drive.tokens.location,
        }
    )


@bp.post("/api/drive/credentials")
def credentials():
    f = request.files.get("file")
    if not f:
        abort(400, "Nenhum arquivo")
    try:
        services.drive.save_credentials(f.read())
    except (ValueError, drive_sync.DriveError) as e:
        abort(400, str(e))
    return jsonify({"ok": True})


@bp.get("/api/drive/connect")
def connect():
    return redirect(services.drive.auth_url(_redirect_uri()))


@bp.get("/api/drive/callback")
def callback():
    if request.args.get("error"):
        return redirect("/?drive=" + quote("Login cancelado: " + request.args["error"]))
    try:
        services.drive.finish_auth(request.args.get("state", ""), request.args.get("code", ""))
    except drive_sync.DriveError as e:
        return redirect("/?drive=" + quote(str(e)))
    services.syncer.mark_all()
    return redirect("/?drive=ok")


@bp.post("/api/drive/disconnect")
def disconnect():
    services.drive.disconnect()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- sincronização


@bp.get("/api/drive/overview")
def overview():
    names = sorted(
        (
            d.name
            for d in PROJECTS.iterdir()
            if d.is_dir() and not d.name.startswith(".") and services.drive_enabled(d.name)
        ),
        key=str.lower,
    )
    ov = services.syncer.overview(names)
    ov["rootId"] = services.drive.state().get("rootId")
    return jsonify(ov)


@bp.post("/api/drive/sync-now")
def sync_now():
    services.syncer.mark_all()
    return jsonify({"ok": True})


@bp.post("/api/drive/sync-all")
def sync_all():
    """Liga/desliga a sincronização de todos os projetos (e dos novos)."""
    enabled = bool(json_body().get("enabled"))
    s = services.drive.state()
    s["syncAll"] = enabled
    services.drive.save_state(s)
    for d in PROJECTS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            st = load_settings(d)
            st["driveSync"] = enabled
            save_settings(d, st)
            services.syncer.mark_dirty(d.name, check_only=True)
    return jsonify({"ok": True})


@bp.get("/api/projects/<name>/drive")
def project_status(name):
    project_dir(name)
    return jsonify(services.syncer.get_status(name))


@bp.post("/api/projects/<name>/drive/sync")
def project_sync(name):
    project_dir(name)
    services.changed(name)
    return jsonify(services.syncer.get_status(name))


@bp.post("/api/projects/<name>/drive/check")
def project_check(name):
    """Confere se outro computador mexeu no projeto (o editor chama ao abrir e a cada ~10 s).

    A conferência roda em segundo plano; o editor acompanha pelo status (checkedAt).
    """
    project_dir(name)
    services.syncer.mark_dirty(name, check_only=True, urgent=True)
    return jsonify(services.syncer.get_status(name))


@bp.post("/api/projects/<name>/drive/conflict")
def resolve_conflict(name):
    """Escolha do usuário para um trecho alterado nos dois computadores.

    "mine" mantém o trecho deste computador (que já está no arquivo); "theirs" troca pelo do
    outro computador, guardando antes o estado atual no histórico.
    """
    d = project_dir(name)
    data = json_body()
    c = services.syncer.pop_conflict(name, data.get("id"))
    if not c:
        abort(404, "Esse conflito já foi resolvido")
    if data.get("use") != "theirs":
        return jsonify({"ok": True})
    p = safe_path(d, c["path"])
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        abort(409, "O arquivo não existe mais. " + IN_DRIVE_HISTORY)
    new = merge.apply_choice(text, c)
    if new is None:
        abort(409, "Esse trecho foi alterado depois. " + IN_DRIVE_HISTORY)
    history.snapshot(d, name)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    services.changed(name)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- projetos no Drive


@bp.get("/api/drive/remote")
def remote():
    """Pastas de projeto existentes no Drive, marcando as que já existem localmente."""
    drive = services.drive
    local = services.local_folder_ids()
    items = [
        {"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime"), "local": local.get(f["id"])}
        for f in drive.list_children(drive.root_folder())
        if f["mimeType"] == drive_sync.FOLDER_MIME
    ]
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


@bp.post("/api/drive/restore")
def restore():
    data = json_body()
    name = (data.get("name") or "").strip()
    if not valid_name(name):
        abort(400, "Nome inválido")
    if (PROJECTS / name).exists() or name in services.importer.reserved():
        abort(409, "Já existe um projeto local com esse nome; escolha outro")
    if data["id"] in services.importer.importing_ids():
        abort(409, "Esse projeto já está sendo importado")
    n = drive_sync.restore_project(services.drive, data["id"], PROJECTS / name, data.get("remoteName") or name)
    services.enable_sync(name)
    return jsonify({"name": name, "files": n})


@bp.get("/api/drive/import-candidates")
def import_candidates():
    """Projetos no Drive que não existem neste computador e ainda não foram oferecidos."""
    drive = services.drive
    if not drive.connected:
        return jsonify([])
    offered = set(drive.state().get("offered", []))
    skip = set(services.local_folder_ids()) | offered | services.importer.importing_ids()
    items = [
        {"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime")}
        for f in drive.list_children(drive.root_folder())
        if f["mimeType"] == drive_sync.FOLDER_MIME and f["id"] not in skip
    ]
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


@bp.post("/api/drive/offered")
def offered():
    """Marca projetos do Drive como já oferecidos (importados ou recusados): não pergunta de novo."""
    services.mark_offered(json_body().get("ids") or [])
    return jsonify({"ok": True})


@bp.post("/api/drive/import")
def import_project():
    """Põe um projeto do Drive na fila de importação, com um nome local livre, e responde na hora.

    O download acontece em segundo plano (services.importer); enquanto isso, o projeto aparece
    na lista do painel como "importando". Ao terminar, a sincronização é ligada.
    """
    data = json_body()
    fid, remote_name = data.get("id"), data.get("name") or "Projeto"
    if not fid:
        abort(400, "Falta o projeto do Drive")
    if fid in services.local_folder_ids() or fid in services.importer.importing_ids():
        abort(409, "Esse projeto já está neste computador")
    name = services.free_project_name(remote_name)
    services.importer.add(name, fid, remote_name)
    return jsonify({"name": name, "queued": True})


@bp.post("/api/drive/import/retry")
def import_retry():
    if not services.importer.retry(json_body().get("name")):
        abort(404, "Essa importação não está com erro")
    return jsonify({"ok": True})


@bp.post("/api/drive/import/dismiss")
def import_dismiss():
    """Descarta uma importação que falhou (o projeto continua no Drive, em "Só no Drive")."""
    if not services.importer.dismiss(json_body().get("name")):
        abort(404, "Essa importação não está com erro")
    return jsonify({"ok": True})
