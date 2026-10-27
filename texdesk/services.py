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
from .storage import load_settings, save_settings

drive: drive_sync.DriveClient = None
syncer: drive_sync.SyncManager = None


def init():
    global drive, syncer
    if syncer is not None:
        return
    drive = drive_sync.DriveClient(DRIVE_STATE)
    syncer = drive_sync.SyncManager(drive, PROJECTS, drive_enabled)
    syncer.mark_all()  # envia o que mudou enquanto o servidor estava desligado


def drive_enabled(name):
    f = PROJECTS / name / SETTINGS_FILE
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")).get("driveSync"))
    except (OSError, ValueError):
        return False


def changed(name):
    """Chamado após qualquer alteração nos arquivos do projeto."""
    syncer.mark_dirty(name)


def apply_sync_default(d: Path):
    """Projetos novos entram na sincronização se 'sincronizar todos' estiver ligado."""
    if drive.connected and drive.state().get("syncAll"):
        s = load_settings(d)
        s["driveSync"] = True
        save_settings(d, s)
        changed(d.name)


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
    name, i = base, 2
    while (PROJECTS / name).exists():
        name, i = f"{base}-{i}", i + 1
    return name
