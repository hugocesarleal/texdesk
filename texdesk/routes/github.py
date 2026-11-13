# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""GitHub: conexão ("Entrar com GitHub"), sincronização, projetos no repositório e importação."""

from flask import Blueprint, abort, jsonify

from .. import github_sync, history, merge, services
from ..config import PROJECTS
from ..security import json_body
from ..storage import project_dir, safe_path

bp = Blueprint("github", __name__)
IN_GITHUB_HISTORY = "A versão do outro computador está no histórico de commits do GitHub."


def _names():
    dirs = (d for d in PROJECTS.iterdir() if d.is_dir() and not d.name.startswith("."))
    return sorted((d.name for d in dirs if services.github_enabled(d.name)), key=str.lower)


# ---------------------------------------------------------------- conexão


@bp.get("/api/github/status")
def status():
    gh = services.github
    s = gh.state()
    return jsonify(
        {
            "configured": gh.configured,
            "connected": gh.connected,
            "user": s.get("user"),
            "repo": s.get("repo"),
            "repoUrl": f"https://github.com/{s['repo']}" if s.get("repo") else None,
            "syncAll": bool(s.get("syncAll")),
            "tokenStorage": gh.tokens.location,
            "commitDelay": github_sync.COMMIT_DELAY,
        }
    )


@bp.post("/api/github/login/start")
def login_start():
    """Pede o código do "Entrar com GitHub": a pessoa o digita em github.com/login/device."""
    try:
        return jsonify(services.github.start_login())
    except github_sync.GitHubError as e:
        abort(502, str(e))


@bp.post("/api/github/login/poll")
def login_poll():
    """O painel pergunta a cada poucos segundos se a pessoa já autorizou."""
    try:
        r = services.github.poll_login()
    except github_sync.GitHubError as e:
        abort(502, str(e))
    if r["state"] == "done":
        if services.github.state().get("syncAll"):
            services.set_github_all(True)  # todos os projetos entram no repositório
        services.gitsync.mark_all()
    return jsonify(r)


@bp.post("/api/github/disconnect")
def disconnect():
    services.github.disconnect()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- sincronização


@bp.get("/api/github/overview")
def overview():
    ov = services.gitsync.overview(_names())
    ov["repoUrl"] = f"https://github.com/{services.github.repo}" if services.github.repo else None
    return jsonify(ov)


@bp.post("/api/github/sync-now")
def sync_now():
    """Envia já tudo o que está esperando o commit (sem esperar os 2 minutos)."""
    services.gitsync.mark_all()
    return jsonify({"ok": True})


@bp.post("/api/github/sync-all")
def sync_all():
    services.set_github_all(bool(json_body().get("enabled")))
    return jsonify({"ok": True})


@bp.get("/api/projects/<name>/github")
def project_status(name):
    project_dir(name)
    return jsonify(services.gitsync.get_status(name))


@bp.post("/api/projects/<name>/github/check")
def project_check(name):
    """Confere se outro computador mexeu no projeto (o editor chama ao abrir e a cada 30 s)."""
    project_dir(name)
    services.gitsync.check(name)
    return jsonify(services.gitsync.get_status(name))


@bp.post("/api/projects/<name>/github/commit")
def project_commit(name):
    """Commit já, sem esperar os 2 minutos (botão no editor, ou o editor sendo fechado)."""
    project_dir(name)
    services.gitsync.commit_now(name)
    return jsonify(services.gitsync.get_status(name))


@bp.post("/api/projects/<name>/github/conflict")
def resolve_conflict(name):
    """Escolha do usuário para um trecho alterado nos dois computadores (como no Drive)."""
    d = project_dir(name)
    data = json_body()
    c = services.gitsync.pop_conflict(name, data.get("id"))
    if not c:
        abort(404, "Esse conflito já foi resolvido")
    if data.get("use") != "theirs":
        return jsonify({"ok": True})
    p = safe_path(d, c["path"])
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        abort(409, "O arquivo não existe mais. " + IN_GITHUB_HISTORY)
    new = merge.apply_choice(text, c)
    if new is None:
        abort(409, "Esse trecho foi alterado depois. " + IN_GITHUB_HISTORY)
    history.snapshot(d, name)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(new)
    services.changed(name)
    return jsonify({"ok": True})


# ---------------------------------------------------------------- projetos no repositório


def _remote_folders():
    gh = services.github
    return gh.top_folders(gh.commit_tree(gh.head()))


@bp.get("/api/github/remote")
def remote():
    """Pastas de projeto no repositório, marcando as que já existem neste computador."""
    try:
        folders = _remote_folders()
    except github_sync.GitHubError as e:
        abort(502, str(e))
    local = services.local_github_paths()
    items = [{"id": path, "name": path, "local": local.get(path)} for path in folders]
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


@bp.get("/api/github/import-candidates")
def import_candidates():
    """Projetos no repositório que não existem neste computador e ainda não foram oferecidos."""
    gh = services.github
    if not gh.connected:
        return jsonify([])
    try:
        folders = _remote_folders()
    except github_sync.GitHubError:
        return jsonify([])
    skip = (
        set(services.local_github_paths())
        | set(gh.state().get("offered", []))
        | services.gh_importer.importing_ids()
        | {d.name for d in PROJECTS.iterdir() if d.is_dir()}  # mesmo nome aqui: é o mesmo projeto
    )
    return jsonify(sorted(({"id": p, "name": p} for p in folders if p not in skip), key=lambda x: x["name"].lower()))


@bp.post("/api/github/offered")
def offered():
    services.mark_github_offered(json_body().get("ids") or [])
    return jsonify({"ok": True})


@bp.post("/api/github/import")
def import_project():
    """Põe um projeto do repositório na fila de importação e responde na hora (como o Drive)."""
    data = json_body()
    path = data.get("id")
    if not path:
        abort(400, "Falta o projeto do GitHub")
    if path in services.local_github_paths() or path in services.gh_importer.importing_ids():
        abort(409, "Esse projeto já está neste computador")
    name = services.free_project_name(path)
    services.gh_importer.add(name, path, path)
    return jsonify({"name": name, "queued": True})


@bp.post("/api/github/import/retry")
def import_retry():
    if not services.gh_importer.retry(json_body().get("name")):
        abort(404, "Essa importação não está com erro")
    return jsonify({"ok": True})


@bp.post("/api/github/import/dismiss")
def import_dismiss():
    if not services.gh_importer.dismiss(json_body().get("name")):
        abort(404, "Essa importação não está com erro")
    return jsonify({"ok": True})
