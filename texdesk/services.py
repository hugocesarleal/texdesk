# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Conexões com o Google Drive e o GitHub e as sincronizações, compartilhadas pelas rotas.

São criados uma vez, em init() (chamado por create_app), e não ao importar o módulo:
assim importar o TexDesk não liga nada sozinho.
"""

import json
import re
from pathlib import Path

from . import drive_sync, github_sync, history, remote_delete, trash
from .config import DATA, DRIVE_STATE, GITHUB_CLIENT_ID, GITHUB_STATE, PROJECTS, SETTINGS_FILE
from .storage import load_settings, save_settings, touch

drive: drive_sync.DriveClient = None
syncer: drive_sync.SyncManager = None
importer: drive_sync.ImportQueue = None
github: github_sync.GitHubClient = None
gitsync: github_sync.GitSyncManager = None
gh_importer: drive_sync.ImportQueue = None
remote_deletes: remote_delete.RemoteDeletes = None


def init():
    global drive, syncer, importer, github, gitsync, gh_importer, remote_deletes
    if syncer is not None:
        return
    drive = drive_sync.DriveClient(DRIVE_STATE)
    syncer = drive_sync.SyncManager(
        drive, PROJECTS, drive_enabled, before_change=before_drive_change, after_change=received_from_drive
    )
    syncer.mark_all()  # envia o que mudou enquanto o servidor estava desligado
    importer = drive_sync.ImportQueue(drive, PROJECTS, imported)
    github = github_sync.GitHubClient(GITHUB_STATE, GITHUB_CLIENT_ID)
    gitsync = github_sync.GitSyncManager(
        github, PROJECTS, github_enabled, before_change=before_github_change, after_change=received_from_github
    )
    # confere todos e envia o que ficou sem commit (TexDesk fechado antes dos 2 minutos)
    gitsync.mark_all()
    gh_importer = drive_sync.ImportQueue(
        github,
        PROJECTS,
        imported_from_github,
        restore=github_sync.restore_project,
        source="github",
        prefix=".importando-gh-",
        expected=(github_sync.GitHubError,),
    )
    # projeto apagado de vez da lixeira: também some do Drive e do GitHub
    remote_deletes = remote_delete.RemoteDeletes(
        DATA / ".remote-deletes.json",
        {
            "drive": _delete_drive_folder,
            "github-folder": _delete_github_folder,
            "github-repo": _delete_github_repo,
            "github-leave": _leave_github_repo,
        },
    )
    trash.before_remove = queue_remote_deletes


def _setting(name, key):
    f = PROJECTS / name / SETTINGS_FILE
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")).get(key))
    except (OSError, ValueError):
        return False


def drive_enabled(name):
    return _setting(name, "driveSync")


def github_enabled(name):
    return _setting(name, "githubSync")


def before_drive_change(d: Path, name, important):
    """Antes de alterar arquivos com o que veio do Drive, guarda o estado atual no histórico.

    Se algo daqui vai ser juntado com a versão do Drive ou substituído por ela, a versão ganha
    nome (fica para sempre); senão, é a automática de sempre (no máximo uma a cada 10 minutos).
    """
    if important:
        history.snapshot(d, name, label="Antes de receber alterações do Google Drive")
    else:
        history.maybe_snapshot(d, name)


def before_github_change(d: Path, name, important):
    """Como before_drive_change, para o que vem do GitHub."""
    if important:
        history.snapshot(d, name, label="Antes de receber alterações do GitHub")
    else:
        history.maybe_snapshot(d, name)


def received_from_drive(name):
    """Chegou algo do Drive: o editor recarrega, e o GitHub recebe a mudança no próximo commit."""
    touch(name)
    gitsync.mark_dirty(name)


def received_from_github(name):
    touch(name)
    syncer.mark_dirty(name)


def changed(name):
    """Chamado após qualquer alteração nos arquivos do projeto."""
    touch(name)
    syncer.mark_dirty(name)
    gitsync.mark_dirty(name)


def github_pending():
    """Há projeto esperando o commit do GitHub (ou sendo enviado agora)?"""
    return bool(gitsync and github.connected and (gitsync.due or gitsync.busy))


def flush(timeout):
    """Ao fechar o TexDesk: envia já o que esperava o commit do GitHub (até timeout segundos)."""
    if gitsync is None or not github.connected:
        return True
    return gitsync.flush(timeout)


def apply_sync_default(d: Path):
    """Projetos novos entram na sincronização se 'sincronizar todos' estiver ligado."""
    s = load_settings(d)
    on = False
    if drive.connected and drive.state().get("syncAll"):
        s["driveSync"] = on = True
    if github.connected and github.state().get("syncAll"):
        s["githubSync"] = on = True
    if on:
        save_settings(d, s)
        changed(d.name)


def set_github_all(enabled):
    """Liga/desliga o GitHub em todos os projetos (e nos novos)."""
    st = github.state()
    st["syncAll"] = bool(enabled)
    github.save_state(st)
    for d in PROJECTS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            s = load_settings(d)
            s["githubSync"] = bool(enabled)
            save_settings(d, s)
    if enabled:
        gitsync.mark_all()


def enable_sync(name):
    s = load_settings(PROJECTS / name)
    s["driveSync"] = True
    save_settings(PROJECTS / name, s)
    changed(name)  # se o nome local difere do Drive, a pasta lá é renomeada


def mark_offered(ids):
    """Projetos do Drive já oferecidos para importar (importados ou recusados): não pergunta de novo."""
    s = drive.state()
    s["offered"] = sorted(set(s.get("offered", [])) | set(ids))
    drive.save_state(s)


def imported(name, folder_id):
    """Chamado pela fila de importação quando um projeto do Drive chega inteiro."""
    enable_sync(name)
    mark_offered([folder_id])


def imported_from_github(name, path):
    s = load_settings(PROJECTS / name)
    s["githubSync"] = True
    save_settings(PROJECTS / name, s)
    mark_github_offered([path])
    touch(name)


def mark_github_offered(paths):
    s = github.state()
    s["offered"] = sorted(set(s.get("offered", [])) | set(paths))
    github.save_state(s)


def local_github_paths():
    """{pasta no repositório: nome do projeto local} dos projetos já ligados ao GitHub."""
    out = {}
    for d in PROJECTS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            m = github_sync.load_manifest(d)
            if m.get("repo"):  # compartilhado: o id é o repositório próprio dele
                out[github_sync.SHARED_PREFIX + m["repo"]] = d.name
                continue
            path = m.get("path")
            out[path or d.name] = d.name if path or github_enabled(d.name) else None
    return {k: v for k, v in out.items() if v}


def local_folder_ids():
    """{id da pasta no Drive: nome do projeto local} dos projetos já ligados ao Drive."""
    out = {}
    for d in PROJECTS.iterdir():
        if d.is_dir():
            fid = drive_sync.load_manifest(d).get("folderId")
            if fid:
                out[fid] = d.name
    return out


# ---------------------------------------------------------------- apagar do Drive e do GitHub


def queue_remote_deletes(project: Path):
    """Projeto saindo de vez da lixeira: o que ele tinha no Drive e no GitHub entra na fila."""
    items = []
    folder = drive_sync.load_manifest(project).get("folderId")
    if folder:
        items.append({"kind": "drive", "folder": folder, "name": project.name})
    m = github_sync.load_manifest(project)
    if m.get("repo"):
        me = (github.state().get("user") or "").lower()
        kind = "github-repo" if m["repo"].split("/")[0].lower() == me else "github-leave"
        items.append({"kind": kind, "repo": m["repo"]})
    elif m.get("path") and m.get("lastCommit"):
        items.append({"kind": "github-folder", "path": m["path"]})
    remote_deletes.add(items)


# Cada um devolve True quando terminou (ou não há o que fazer) e False para esperar. Nunca apaga o
# que um projeto deste computador ainda usa: ex., um projeto novo com o mesmo nome, que pegou a
# mesma pasta no Drive ou no repositório antes de o antigo sair da lixeira.
def _delete_drive_folder(item):
    if not drive.connected:
        return False
    if item["folder"] in local_folder_ids():
        return True
    try:
        drive.trash(item["folder"])  # lixeira do Drive: dá para recuperar por 30 dias
    except drive_sync.DriveError as e:
        if "404" not in str(e):
            raise
    return True


def _delete_github_folder(item):
    if not github.connected:
        return False
    if item["path"] in local_github_paths():
        return True
    github_sync.remove_folder(github, item["path"], f"{item['path']}: projeto apagado no TexDesk")
    return True


def _delete_github_repo(item):
    if not github.connected:
        return False
    if github_sync.SHARED_PREFIX + item["repo"] in local_github_paths():
        return True
    try:
        github_sync.delete_shared_repo(github, item["repo"])
    except github_sync.NeedsDeleteScope:
        return False  # espera a pessoa entrar com GitHub de novo
    return True


def _leave_github_repo(item):
    if not github.connected:
        return False
    if github_sync.SHARED_PREFIX + item["repo"] in local_github_paths():
        return True
    try:
        github.leave(item["repo"])
    except github_sync.GitHubError as e:
        if e.status != 404:  # (já sem acesso)
            raise
    return True


def pending_remote_deletes():
    """Exclusões ainda por fazer, para o painel: [{kind, ..., error}]."""
    if remote_deletes is None:
        return []
    return [dict(i, error=remote_deletes.errors.get(remote_deletes.key(i))) for i in remote_deletes.items()]


def read_only(name):
    """Projeto compartilhado com este usuário só para leitura (no GitHub)?"""
    return bool(github_sync.load_manifest(PROJECTS / name).get("readOnly"))


def ensure_writable(name):
    """Recusa alterar os arquivos de um projeto só de leitura (o GitHub também recusaria o envio)."""
    if read_only(name):
        from flask import abort

        abort(403, "Este projeto foi compartilhado com você só para leitura. Para editar, faça uma cópia.")


def free_project_name(remote_name):
    """Nome de projeto local válido e livre para uma pasta vinda do Drive."""
    base = re.sub(r"\s+", " ", re.sub(r"[^\w\-. ]", " ", remote_name)).strip(" .")[:76] or "Projeto"
    # nomes de importações em andamento (Drive e GitHub)
    reserved = (importer.reserved() if importer else set()) | (gh_importer.reserved() if gh_importer else set())
    name, i = base, 2
    while (PROJECTS / name).exists() or name in reserved:
        name, i = f"{base}-{i}", i + 1
    return name
