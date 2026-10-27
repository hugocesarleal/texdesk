# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Projetos no disco: caminhos seguros, configurações, árvore de arquivos."""

import json
import re
import threading
import time
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
    try:  # tenta ler direto (em vez de "existe?" + ler: uma consulta a menos ao disco)
        s = json.loads((d / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
            score = (
                p.name.lower() != "main.tex",
                bool(re.search(r"exemplo|example|sample|template|modelo", p.name, re.I)),
                len(rel.parts),
                rel.as_posix(),
            )
            candidates.append((score, rel.as_posix()))
    if candidates:
        return min(candidates)[1]
    return texs[0].relative_to(d).as_posix() if texs else "main.tex"


def _read_tex(p: Path):
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def is_standalone(text: str):
    """Documento completo (compila sozinho), e não um capítulo incluído por outro."""
    return bool(re.search(r"^[^%\n]*\\documentclass", text, re.M)) and "\\begin{document}" in text


def _included(d: Path, p: Path):
    """Arquivos .tex que p inclui com \\input, \\include ou \\subfile (ignorando comentários)."""
    text = re.sub(r"(?<!\\)%.*", "", _read_tex(p))
    out = set()
    for arg in re.findall(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", text):
        name = arg.strip()
        if not name.endswith(".tex"):
            name += ".tex"
        for base in (p.parent, d):  # relativo ao arquivo ou à raiz do projeto
            f = (base / name).resolve()
            if f.is_file():
                out.add(f)
                break
    return out


def compile_target(d: Path, main: str, open_rel: str):
    """Documento a compilar quando o arquivo open_rel está aberto no editor.

    Um documento completo compila a si mesmo. Um capítulo compila o documento que o inclui
    (direta ou indiretamente), de preferência o último compilado (main). Qualquer outro arquivo
    mantém o último compilado.
    """
    if not open_rel or not open_rel.lower().endswith(".tex"):
        return main
    p = safe_path(d, open_rel)
    if not p.is_file():
        return main
    if is_standalone(_read_tex(p)):
        return open_rel
    target = p.resolve()

    def reaches(root: Path):
        seen, todo = set(), [root.resolve()]
        while todo:
            f = todo.pop()
            if f == target:
                return True
            if f not in seen:
                seen.add(f)
                todo.extend(_included(d, f) - seen)
        return False

    if (d / main).is_file() and reaches(d / main):
        return main
    for q in sorted(d.rglob("*.tex")):
        rel = q.relative_to(d)
        if not is_hidden(rel) and is_standalone(_read_tex(q)) and reaches(q):
            return rel.as_posix()
    return main


def tree(d: Path):
    """Arquivos e pastas visíveis do projeto, em ordem alfabética."""
    out = []
    for p in sorted(d.rglob("*"), key=lambda x: x.relative_to(d).as_posix().lower()):
        rel = p.relative_to(d)
        if is_hidden(rel):
            continue
        st = p.stat()
        is_file = p.is_file()
        out.append(
            {
                "path": rel.as_posix(),
                "type": "file" if is_file else "folder",
                "text": is_file and is_text(p),
                "size": st.st_size if is_file else 0,
                "mtime": st.st_mtime if is_file else 0,  # o editor percebe mudanças feitas fora dele
            }
        )
    return out


# ---------------------------------------------------------------- data de modificação (com cache)
# Descobrir quando um projeto mudou exige olhar todos os arquivos dele, e a lista de projetos
# é pedida a cada poucos segundos. Então: toda alteração feita pelo TexDesk avisa o cache
# (touch), e a releitura completa acontece no máximo a cada MTIME_TTL segundos, para pegar
# mudanças feitas fora do TexDesk (outro editor, o próprio Drive, o Explorer…).
MTIME_TTL = 60
_INTERNAL_FILES = {".project.json", ".thumbnail.png", ".drive.json"}
_mtimes: dict[str, tuple[float, float]] = {}  # projeto -> (última modificação, quando foi medida)


def project_mtime(d: Path):
    cached = _mtimes.get(d.name)
    now = time.time()
    if cached and now - cached[1] < MTIME_TTL:
        return cached[0]
    mtime = max(
        (p.stat().st_mtime for p in d.rglob("*") if p.is_file() and p.name not in _INTERNAL_FILES),
        default=d.stat().st_mtime,
    )
    _mtimes[d.name] = (mtime, now)
    return mtime


def touch(name):
    """O projeto acabou de ser alterado pelo TexDesk."""
    now = time.time()
    _mtimes[name] = (now, now)


def forget(name):
    _mtimes.pop(name, None)


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
