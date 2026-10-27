# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Compilação com o Tectonic e leitura dos resultados (PDF, log, mensagens)."""
import os
import re
import subprocess
import time
from pathlib import Path

from .config import COMPILE_TIMEOUT, OUTPUT, TECTONIC
from .latexlog import parse_log
from .storage import is_hidden, tree

# extensões dos arquivos intermediários do TeX (para limpar o que o shell-escape deixa no projeto)
INTERMEDIATE_EXT = {".aux", ".bbl", ".bcf", ".blg", ".idx", ".ilg", ".ind", ".log", ".out", ".toc", ".lof",
                    ".lot", ".xdv", ".fls", ".nav", ".snm", ".vrb", ".glo", ".gls", ".ist", ".pyg", ".aex",
                    ".pygtex", ".pygstyle", ".synctex", ".gz", ".xml"}


def compile_project(d: Path, name: str, main: str, main_path: Path, shell_escape: bool):
    """Compila o documento principal e devolve o resultado para a interface."""
    out = OUTPUT / name
    out.mkdir(parents=True, exist_ok=True)
    # \include{pasta/arq} grava pasta/arq.aux na saída: espelha as subpastas
    for sub in d.rglob("*"):
        rel = sub.relative_to(main_path.parent) if main_path.parent in sub.parents else None
        if sub.is_dir() and rel and not is_hidden(rel):
            (out / rel).mkdir(parents=True, exist_ok=True)
    stem = Path(main).stem
    for ext in (".pdf", ".log", ".synctex.gz"):
        (out / (stem + ext)).unlink(missing_ok=True)

    cmd = [str(TECTONIC), "--keep-logs", "--keep-intermediates", "--synctex",
           "--outdir", str(out), "--chatter", "minimal",
           # gera o PDF mesmo com erros (como -interaction=batchmode)
           "-Zcontinue-on-errors", f"-Zsearch-path={d}"]
    if shell_escape:
        # roda os comandos na pasta do documento, como os outros motores
        # (necessário p/ caminhos relativos em \inputminted etc.)
        cmd.append(f"-Zshell-escape-cwd={main_path.parent}")
    cmd.append(main_path.name)

    # com shell-escape o Tectonic grava os intermediários (.aux, .xdv, .pyg…) na pasta
    # do documento; eles são apagados depois para não sujar o projeto (nem o Drive)
    before = _snapshot(d) if shell_escape else None
    t0 = time.time()
    try:
        # tools/ no PATH para o Tectonic achar o biber (biblatex)
        env = {**os.environ, "PATH": str(TECTONIC.parent) + os.pathsep + os.environ.get("PATH", "")}
        proc = subprocess.run(cmd, cwd=main_path.parent, capture_output=True, timeout=COMPILE_TIMEOUT, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"status": "timedout", "message": f"Tempo limite de {COMPILE_TIMEOUT}s excedido",
                "entries": [], "log": ""}
    finally:
        if before is not None:
            _remove_created(d, before)
    elapsed = time.time() - t0
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")

    log_file = out / (stem + ".log")
    log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    main_dir_rel = main_path.parent.relative_to(d).as_posix()
    known = {f["path"] for f in tree(d) if f["type"] == "file"}
    entries = parse_log(log, main_dir_rel if main_dir_rel != "." else "", Path(main).as_posix(), known)
    entries += parse_tectonic_stderr(stderr, entries)
    pdf = out / (stem + ".pdf")
    has_pdf = pdf.exists()  # o PDF anterior foi apagado antes de compilar
    has_errors = proc.returncode != 0 or any(e["level"] == "error" for e in entries)
    return {
        "status": "failure" if not has_pdf else ("error" if has_errors else "success"),
        "pdf": f"/api/projects/{name}/output/{stem}.pdf?t={int(time.time() * 1000)}" if has_pdf else None,
        "entries": entries,
        "log": log,
        "stdout": stdout + stderr,
        "time": round(elapsed, 2),
    }


def _snapshot(d: Path):
    return set(d.rglob("*"))


def _remove_created(d: Path, before):
    """Apaga os intermediários do TeX que a compilação criou na pasta do projeto.

    Só mexe no que não existia antes E é intermediário (pela extensão ou por estar numa
    pasta _minted*): um arquivo que o usuário criar durante a compilação fica intacto.
    """
    def is_intermediate(p):
        rel = p.relative_to(d).parts
        return any(x.startswith("_minted") for x in rel) or p.suffix.lower() in INTERMEDIATE_EXT

    created = [p for p in d.rglob("*") if p not in before and is_intermediate(p)]
    for p in sorted(created, key=lambda x: len(x.parts), reverse=True):  # conteúdo antes das pastas
        try:
            if p.is_dir():
                p.rmdir()  # só remove se ficou vazia
            else:
                p.unlink()
        except OSError:
            pass


def parse_tectonic_stderr(stderr, existing):
    """Mensagens do próprio Tectonic (rede, arquivos ausentes) que não estão no .log."""
    def norm(msg):
        return msg.strip().rstrip(".")[:30]

    extra = []
    # o stderr repete as mensagens de cada passada; o .log só tem a última
    seen = {(e["line"], norm(e["message"])) for e in existing}
    for line in stderr.splitlines():
        m = re.match(r"^(error|warning): (?:(.+?):(\d+): )?(.*)$", line.strip())
        if not m:
            continue
        level, f, ln, msg = m.groups()
        if f or level == "warning":
            continue  # mensagens do TeX: já vêm do .log
        if re.match(r"(halted on potentially-recoverable error|the TeX engine had an error)", msg) \
                and any(e["level"] == "error" for e in existing):
            continue
        key = (None, norm(msg))
        if key in seen:
            continue
        seen.add(key)
        if re.search(r'shell-escape command "for \^%i in \(pygmentize', msg):
            level = "warning"  # sondagem do minted no Windows; o realce funciona mesmo assim
        extra.append({"level": level, "file": None, "line": None, "message": msg, "content": ""})
    return extra
