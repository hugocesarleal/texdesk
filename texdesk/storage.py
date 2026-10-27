# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Projetos no disco: caminhos seguros, configurações, árvore de arquivos."""
import json
import re
import threading
from pathlib import Path

from flask import abort

from .config import NAME_RE, PROJECTS, SETTINGS_FILE, TEXT_EXT

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def project_lock(name):
    """Um lock por projeto: impede duas compilações simultâneas do mesmo projeto."""
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def valid_name(name):
    return bool(NAME_RE.match(name)) and not name.startswith(".")


def project_dir(name):
    """Pasta do projeto, ou erro 400/404 (nome inválido ou projeto inexistente)."""
    if not valid_name(name):
        abort(400, "Nome de projeto inválido")
    d = PROJECTS / name
    if not d.is_dir():
        abort(404, "Projeto não encontrado")
    return d


def safe_path(base: Path, rel: str) -> Path:
    """Caminho relativo dentro de base; recusa caminhos absolutos e qualquer saída da pasta."""
    rel = (rel or "").replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):  # caminho absoluto
        abort(400, "Caminho inválido")
    rel = rel.rstrip("/")
    if not rel or any(part in ("..", "") for part in rel.split("/")):
        abort(400, "Caminho inválido")
    p = (base / rel).resolve()
    if base.resolve() not in p.parents:
        abort(400, "Caminho inválido")
    return p


def is_text(path: Path):
    return path.suffix.lower() in TEXT_EXT or path.suffix == ""


def is_hidden(rel: Path):
    """Arquivos internos (.project.json, .drive.json, .prism/…) não aparecem para o usuário."""
    return any(part.startswith(".") for part in rel.parts)


# ---------------------------------------------------------------- configurações do projeto

def load_settings(d: Path):
    f = d / SETTINGS_FILE
    s = {}
    if f.exists():
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            s = {}
    if not s.get("main") or not (d / s["main"]).exists():
        s["main"] = guess_main(d)
    s.setdefault("autoCompile", False)
    s.setdefault("shellEscape", False)
    s.setdefault("driveSync", False)
    return s


def save_settings(d: Path, s):
    (d / SETTINGS_FILE).write_text(json.dumps(s, indent=2), encoding="utf-8")


def guess_main(d: Path):
    """Documento principal: um .tex com \\documentclass e \\begin{document}."""
    texs = sorted(p for p in d.rglob("*.tex") if not is_hidden(p.relative_to(d)))
    candidates = []
    for p in texs:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^[^%\n]*\\documentclass", t, re.M) and "\\begin{document}" in t:
            rel = p.relative_to(d)
            # prefere main.tex, depois arquivos mais rasos, evitando exemplos/modelos
            score = (p.name.lower() != "main.tex", bool(re.search(r"exemplo|example|sample|template|modelo", p.name, re.I)),
                     len(rel.parts), rel.as_posix())
            candidates.append((score, rel.as_posix()))
    if candidates:
        return min(candidates)[1]
    return texs[0].relative_to(d).as_posix() if texs else "main.tex"


def tree(d: Path):
    """Arquivos e pastas visíveis do projeto, em ordem alfabética."""
    out = []
    for p in sorted(d.rglob("*"), key=lambda x: x.relative_to(d).as_posix().lower()):
        rel = p.relative_to(d)
        if is_hidden(rel):
            continue
        out.append({"path": rel.as_posix(), "type": "folder" if p.is_dir() else "file",
                    "text": p.is_file() and is_text(p), "size": p.stat().st_size if p.is_file() else 0})
    return out


def png_size(p: Path):
    """Largura e altura lidas do cabeçalho IHDR do PNG (sem abrir a imagem inteira)."""
    try:
        with open(p, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return None, None
