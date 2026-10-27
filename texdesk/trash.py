# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Lixeira de projetos: um projeto excluído fica TRASH_DAYS dias antes de sumir de vez.

Cada item é uma pasta DATA/trash/<id> com o projeto (project/), o histórico de versões
dele (history/) e um info.json com o nome e a data. O PDF compilado não vai junto: é
gerado de novo ao abrir o projeto.
"""

import json
import shutil
import threading
import time
from pathlib import Path

from . import history
from .config import DATA, PROJECTS

TRASH = DATA / "trash"
TRASH_DAYS = 30

_lock = threading.Lock()


def _size(d: Path):
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


def put(name: str):
    """Move o projeto (e o histórico dele) para a lixeira. Devolve o id do item."""
    with _lock:
        tid = str(int(time.time() * 1000))
        while (TRASH / tid).exists():
            tid = str(int(tid) + 1)
        item = TRASH / tid
        item.mkdir(parents=True)
        src = PROJECTS / name
        info = {"name": name, "deleted": time.time(), "size": _size(src)}
        shutil.move(str(src), str(item / "project"))
        with history._lock:
            h = history.HISTORY / name
            if h.exists():
                shutil.move(str(h), str(item / "history"))
            history._last.pop(name, None)
        (item / "info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return tid


def _items():
    out = []
    if not TRASH.exists():
        return out
    for item in TRASH.iterdir():
        try:
            info = json.loads((item / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": item.name, **info})
    return out


def purge_old():
    """Apaga de vez o que está na lixeira há mais de TRASH_DAYS dias."""
    limit = time.time() - TRASH_DAYS * 86400
    for it in _items():
        if it["deleted"] < limit:
            remove(it["id"])


def list_items():
    purge_old()
    items = _items()
    for it in items:
        it["expires"] = it["deleted"] + TRASH_DAYS * 86400
    return sorted(items, key=lambda it: -it["deleted"])


def _item(tid: str) -> Path:
    if not tid.isdigit() or not (TRASH / tid / "info.json").exists():
        raise KeyError(tid)
    return TRASH / tid


def free_name(name: str):
    """O nome, ou "nome (restaurado)", "nome (restaurado 2)"… se já houver um projeto assim."""
    if not (PROJECTS / name).exists():
        return name
    n = 1
    while True:
        suffix = " (restaurado" + ("" if n == 1 else f" {n}") + ")"
        cand = name[: 80 - len(suffix)] + suffix
        if not (PROJECTS / cand).exists():
            return cand
        n += 1


def restore(tid: str):
    """Devolve o projeto aos projetos. Devolve o nome com que ele voltou."""
    with _lock:
        item = _item(tid)
        info = json.loads((item / "info.json").read_text(encoding="utf-8"))
        name = free_name(info["name"])
        shutil.move(str(item / "project"), str(PROJECTS / name))
        if (item / "history").exists():
            with history._lock:
                dest = history.HISTORY / name
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(item / "history"), str(dest))
        shutil.rmtree(item, ignore_errors=True)
        return name


def remove(tid: str):
    """Apaga o item de vez."""
    with _lock:
        shutil.rmtree(_item(tid), ignore_errors=True)


def empty():
    for it in _items():
        remove(it["id"])
