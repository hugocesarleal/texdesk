# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""GitHub: conexão ("Entrar com GitHub"), sincronização, projetos no repositório, importação
e compartilhamento de projetos (um repositório privado por projeto compartilhado)."""

from flask import Blueprint, abort, jsonify

from .. import github_sync, history, merge, services
from ..config import PROJECTS
from ..security import json_body
from ..storage import load_settings, project_dir, safe_path, save_settings

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
    items = [{"id": p, "name": p} for p in folders if p not in skip]
    # projetos compartilhados (dela ou com ela) que este computador ainda não tem
    try:
        shared = gh.shared_repos()
    except github_sync.GitHubError:
        shared = []
    for r in shared:
        rid = github_sync.SHARED_PREFIX + r["repo"]
        if rid not in skip:
            mine = r["owner"].lower() == (gh.state().get("user") or "").lower()
            items.append({"id": rid, "name": r["name"], "sharedBy": None if mine else r["owner"]})
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


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
    name = services.free_project_name(data.get("name") or path)
    services.gh_importer.add(name, path, data.get("name") or path)
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


# ---------------------------------------------------------------- compartilhamento


def _share_state(name):
    d = project_dir(name)
    gh = services.github
    m = github_sync.load_manifest(d)
    st = {
        "connected": gh.connected,
        "user": gh.state().get("user"),
        "shared": None,
        "readOnly": bool(m.get("readOnly")),
    }
    if m.get("repo"):
        owner = m["repo"].split("/")[0]
        st["shared"] = {
            "repo": m["repo"],
            "url": f"https://github.com/{m['repo']}",
            "owner": owner,
            "mine": owner.lower() == (st["user"] or "").lower(),
        }
    return d, m, st


@bp.get("/api/projects/<name>/share")
def share_status(name):
    """Com quem o projeto está compartilhado (para o dono) ou de quem é (para quem recebeu)."""
    d, m, st = _share_state(name)
    if st["shared"] and st["shared"]["mine"] and st["connected"]:
        try:
            st["people"] = services.github.view(m["repo"]).people()
        except github_sync.GitHubError as e:
            st["error"] = str(e)
    return jsonify(st)


@bp.post("/api/projects/<name>/share")
def share(name):
    """Convida alguém. Na primeira vez, leva o projeto para um repositório próprio (texdesk-<projeto>)."""
    d, m, st = _share_state(name)
    data = json_body()
    login, write = (data.get("login") or "").strip().lstrip("@"), bool(data.get("write", True))
    if not st["connected"]:
        abort(409, "Conecte o GitHub no painel de projetos primeiro")
    if st["shared"] and not st["shared"]["mine"]:
        abort(403, "Só quem compartilhou o projeto pode convidar pessoas")
    gh = services.github
    try:
        if not st["shared"]:
            s = load_settings(d)
            if not s.get("githubSync"):
                s["githubSync"] = True
                save_settings(d, s)
            # com a fila parada: nenhum commit deste projeto sai pelo caminho antigo no meio
            services.gitsync.forget(name)
            full = services.gitsync.exclusive(lambda: github_sync.share_project(gh, d, name))
        else:
            full = st["shared"]["repo"]
        if login:
            gh.view(full).invite(login, write)
    except github_sync.GitHubError as e:
        abort(400 if e.status in (None, 404, 422) else 502, str(e))
    return share_status(name)


@bp.post("/api/projects/<name>/share/permission")
def share_permission(name):
    d, m, st = _share_state(name)
    if not (st["shared"] and st["shared"]["mine"]):
        abort(403, "Só quem compartilhou o projeto pode mudar as permissões")
    data = json_body()
    try:
        services.github.view(m["repo"]).set_permission(
            data.get("login"), bool(data.get("write")), data.get("invitation")
        )
    except github_sync.GitHubError as e:
        abort(502, str(e))
    return share_status(name)


@bp.post("/api/projects/<name>/share/remove")
def share_remove(name):
    d, m, st = _share_state(name)
    if not (st["shared"] and st["shared"]["mine"]):
        abort(403, "Só quem compartilhou o projeto pode tirar o acesso de alguém")
    data = json_body()
    try:
        services.github.view(m["repo"]).remove(data.get("login"), data.get("invitation"))
    except github_sync.GitHubError as e:
        abort(502, str(e))
    return share_status(name)


@bp.post("/api/projects/<name>/share/leave")
def share_leave(name):
    """Sai de um projeto compartilhado por outra pessoa. A cópia daqui fica, sem sincronizar."""
    d, m, st = _share_state(name)
    if not st["shared"] or st["shared"]["mine"]:
        abort(400, "Este projeto não foi compartilhado com você por outra pessoa")
    try:
        services.github.leave(m["repo"])
    except github_sync.GitHubError as e:
        if e.status != 404:  # (já sem acesso: só desliga aqui)
            abort(502, str(e))
    services.gitsync.forget(name)
    (d / github_sync.MANIFEST).unlink(missing_ok=True)
    s = load_settings(d)
    s["githubSync"] = False
    save_settings(d, s)
    return jsonify({"ok": True})


@bp.get("/api/github/invitations")
def invitations():
    """Convites recebidos para projetos do TexDesk."""
    if not services.github.connected:
        return jsonify([])
    try:
        return jsonify(services.github.invitations())
    except github_sync.GitHubError:
        return jsonify([])


@bp.post("/api/github/invitations/<int:iid>/accept")
def accept(iid):
    """Aceita o convite e baixa o projeto em segundo plano (aparece na lista como "importando")."""
    gh = services.github
    inv = next((i for i in gh.invitations() if i["id"] == iid), None)
    if not inv:
        abort(404, "Convite não encontrado (já foi aceito ou cancelado)")
    try:
        gh.accept(iid)
    except github_sync.GitHubError as e:
        abort(502, str(e))
    name = services.free_project_name(inv["name"])
    services.gh_importer.add(name, github_sync.SHARED_PREFIX + inv["repo"], inv["name"])
    return jsonify({"name": name, "queued": True})


@bp.post("/api/github/invitations/<int:iid>/decline")
def decline(iid):
    try:
        services.github.decline(iid)
    except github_sync.GitHubError as e:
        abort(502, str(e))
    return jsonify({"ok": True})
