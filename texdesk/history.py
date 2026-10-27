# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Histórico de versões: cópias locais dos arquivos de texto de cada projeto.

Fica fora da pasta do projeto (em DATA/history/<projeto>), para não ir para o Drive nem
para o .zip. Cada versão é um JSON {caminho: hash}; o conteúdo vai para objects/,
comprimido e guardado uma vez só, então versões quase iguais quase não ocupam espaço.

Versões automáticas: antes da primeira gravação depois de AUTO_INTERVAL sem versão nova,
antes de apagar/mover arquivos e antes de restaurar. As com nome ficam para sempre; das
automáticas ficam as MAX_AUTO mais recentes.
"""

import difflib
import hashlib
import json
import shutil
import threading
import time
import zlib
from pathlib import Path

from .config import DATA
from .storage import is_hidden, is_text

HISTORY = DATA / "history"
AUTO_INTERVAL = 10 * 60
MAX_AUTO = 200
MAX_FILE = 2 * 1024 * 1024  # arquivos de texto maiores que isso não entram

_lock = threading.Lock()
_last: dict[str, float] = {}  # projeto -> hora da última versão (cache)


def _dir(name):
    return HISTORY / name


def _current(d: Path):
    """Arquivos de texto do projeto: {caminho: bytes}."""
    out = {}
    for p in d.rglob("*"):
        rel = p.relative_to(d)
        if p.is_file() and not is_hidden(rel) and is_text(p) and p.stat().st_size <= MAX_FILE:
            out[rel.as_posix()] = p.read_bytes()
    return out


def _put(name, data: bytes):
    h = hashlib.sha256(data).hexdigest()
    p = _dir(name) / "objects" / h[:2] / h
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(zlib.compress(data))
        tmp.replace(p)
    return h


def _get(name, h) -> bytes:
    return zlib.decompress((_dir(name) / "objects" / h[:2] / h).read_bytes())


def _snapshots(name):
    """Versões em ordem cronológica (a última é a mais recente)."""
    out = []
    for p in sorted((_dir(name) / "snapshots").glob("*.json")):
        try:
            out.append({"id": p.stem, **json.loads(p.read_text(encoding="utf-8"))})
        except (OSError, ValueError):
            continue
    return out


def _load(name, sid):
    if not sid.isdigit():
        raise KeyError(sid)
    p = _dir(name) / "snapshots" / f"{sid}.json"
    if not p.exists():
        raise KeyError(sid)
    return {"id": sid, **json.loads(p.read_text(encoding="utf-8"))}


def snapshot(d: Path, name: str, label: str = "", auto: bool = True):
    """Grava uma versão. Uma automática igual à anterior não é gravada (devolve None)."""
    with _lock:
        files = {path: _put(name, data) for path, data in _current(d).items()}
        snaps = _snapshots(name)
        if auto and snaps and snaps[-1]["files"] == files:
            _last[name] = time.time()
            return None
        now = time.time()
        sid = str(int(now * 1000))
        if snaps and sid <= snaps[-1]["id"]:  # duas no mesmo milissegundo
            sid = str(int(snaps[-1]["id"]) + 1)
        sd = _dir(name) / "snapshots"
        sd.mkdir(parents=True, exist_ok=True)
        body = {"time": now, "label": label.strip()[:120], "auto": auto, "files": files}
        (sd / f"{sid}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        _last[name] = now
        _prune(name)
        return sid


def maybe_snapshot(d: Path, name: str):
    """Versão automática se a última tiver mais de AUTO_INTERVAL (chamada antes de gravar)."""
    last = _last.get(name)
    if last is None:
        snaps = sorted((_dir(name) / "snapshots").glob("*.json"))
        last = int(snaps[-1].stem) / 1000 if snaps else 0
        _last[name] = last
    if time.time() - last >= AUTO_INTERVAL:
        snapshot(d, name)


def _prune(name):
    snaps = _snapshots(name)
    autos = [s for s in snaps if s["auto"] and not s["label"]]
    drop = autos[: max(0, len(autos) - MAX_AUTO)]
    if not drop:
        return
    for s in drop:
        (_dir(name) / "snapshots" / f"{s['id']}.json").unlink(missing_ok=True)
    used = {h for s in snaps if s not in drop for h in s["files"].values()}
    for p in (_dir(name) / "objects").glob("*/*"):
        if p.name not in used:
            p.unlink(missing_ok=True)


def list_versions(name):
    """Versões, da mais recente para a mais antiga, com quantos arquivos mudaram em cada uma."""
    snaps = _snapshots(name)
    out, prev = [], {}
    for s in snaps:
        f = s["files"]
        changed = sum(f.get(p) != prev.get(p) for p in set(f) | set(prev))
        out.append(
            {
                "id": s["id"],
                "time": s["time"],
                "label": s["label"],
                "auto": s["auto"],
                "files": len(f),
                "changed": changed,
            }
        )
        prev = f
    return out[::-1]


def compare(d: Path, name: str, sid: str):
    """Arquivos da versão comparados com o projeto agora: added/removed/modified/same."""
    snap = _load(name, sid)["files"]
    now = {p: hashlib.sha256(b).hexdigest() for p, b in _current(d).items()}
    out = []
    for p in sorted(set(snap) | set(now), key=str.lower):
        if p not in now:
            status = "removed"  # existia na versão e foi apagado depois
        elif p not in snap:
            status = "added"
        else:
            status = "same" if snap[p] == now[p] else "modified"
        out.append({"path": p, "status": status})
    return out


def file_diff(d: Path, name: str, sid: str, path: str):
    """Diferença linha a linha entre a versão e o arquivo atual."""
    snap = _load(name, sid)["files"]
    old = _get(name, snap[path]).decode("utf-8", "replace") if path in snap else ""
    cur = d / path
    new = cur.read_text(encoding="utf-8", errors="replace") if path in _current(d) else ""
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "versão", "atual", n=3, lineterm=""))
    return {"path": path, "old": old, "diff": lines[2:]}  # sem o cabeçalho ---/+++


def restore(d: Path, name: str, sid: str, path: str | None = None):
    """Volta um arquivo (ou o projeto inteiro) para a versão. Antes, guarda o estado atual."""
    snap = _load(name, sid)
    when = time.strftime("%d/%m %H:%M", time.localtime(snap["time"]))
    snapshot(d, name, label=f"Antes de restaurar {path or 'a versão'} de {when}", auto=False)
    files = snap["files"]
    targets = [path] if path else list(files)
    for p in targets:
        dest = d / p
        if p in files:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_get(name, files[p]))
        else:
            dest.unlink(missing_ok=True)
    if not path:  # o projeto inteiro: arquivos de texto criados depois da versão saem
        for p in set(_current(d)) - set(files):
            (d / p).unlink(missing_ok=True)
    return targets


def rename(old: str, new: str):
    with _lock:
        if _dir(old).exists() and not _dir(new).exists():
            _dir(old).rename(_dir(new))
        _last.pop(old, None)


def delete(name: str):
    with _lock:
        shutil.rmtree(_dir(name), ignore_errors=True)
        _last.pop(name, None)
