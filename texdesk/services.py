# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Conexão com o Google Drive e o processo de sincronização, compartilhados pelas rotas.

São criados uma vez, em init() (chamado por create_app), e não ao importar o módulo:
assim importar o TexDesk não liga nada sozinho.
"""

import json
import re
from pathlib import Path

from . import drive_sync
from .config import DRIVE_STATE, PROJECTS, SETTINGS_FILE
from .storage import load_settings, save_settings, touch

drive: drive_sync.DriveClient = None
syncer: drive_sync.SyncManager = None
importer: drive_sync.ImportQueue = None


def init():
    global drive, syncer, importer
    if syncer is not None:
        return
    drive = drive_sync.DriveClient(DRIVE_STATE)
    syncer = drive_sync.SyncManager(drive, PROJECTS, drive_enabled)
    syncer.mark_all()  # envia o que mudou enquanto o servidor estava desligado
    importer = drive_sync.ImportQueue(drive, PROJECTS, imported)


def drive_enabled(name):
    f = PROJECTS / name / SETTINGS_FILE
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")).get("driveSync"))
    except (OSError, ValueError):
        return False


def changed(name):
    """Chamado após qualquer alteração nos arquivos do projeto."""
    touch(name)
    syncer.mark_dirty(name)


def apply_sync_default(d: Path):
    """Projetos novos entram na sincronização se 'sincronizar todos' estiver ligado."""
    if drive.connected and drive.state().get("syncAll"):
        s = load_settings(d)
        s["driveSync"] = True
        save_settings(d, s)
        changed(d.name)


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


def local_folder_ids():
    """{id da pasta no Drive: nome do projeto local} dos projetos já ligados ao Drive."""
    out = {}
    for d in PROJECTS.iterdir():
        if d.is_dir():
            fid = drive_sync.load_manifest(d).get("folderId")
            if fid:
                out[fid] = d.name
    return out


def free_project_name(remote_name):
    """Nome de projeto local válido e livre para uma pasta vinda do Drive."""
    base = re.sub(r"\s+", " ", re.sub(r"[^\w\-. ]", " ", remote_name)).strip(" .")[:76] or "Projeto"
    reserved = importer.reserved() if importer else set()  # nomes de importações em andamento
    name, i = base, 2
    while (PROJECTS / name).exists() or name in reserved:
        name, i = f"{base}-{i}", i + 1
    return name
