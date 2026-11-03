# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Modelos de outros autores, baixados direto do repositório de quem os mantém.

Os modelos do IFMG, de Marcos Roberto Ribeiro, não vêm com o TexDesk: a instalação baixa a
versão mais recente (branch main) de cada repositório e monta o modelo em tools/templates,
com os arquivos exatamente como estão lá. A pasta tools/ é preservada nas atualizações.
Se a instalação foi feita sem internet, ou o TexDesk foi atualizado de uma versão que trazia
os modelos, o servidor baixa o que faltar ao abrir.

Uso na linha de comando (pela instalação): python -m texdesk.external_templates
"""

import io
import json
import logging
import shutil
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .config import TEMPLATE_META, TOOLS
from .online import USER_AGENT

log = logging.getLogger(__name__)

EXTERNAL = TOOLS / "templates"
MAX_SIZE = 30 * 1024 * 1024  # os dois repositórios têm menos de 1 MB

# modelo -> repositório, documento de exemplo (vira o main.tex) e o que mais copiar dele
# ("pasta/" copia a pasta inteira)
SOURCES = {
    "ifmg-slides": {
        "repo": "ribeiromarcos/ifslides2024",
        "main": "apresentacao.tex",
        "files": ["referencias.bib", "ifslides2024.sty", "biblatexfix.sty", "LICENSE", "figuras/"],
        "name": "Slides IFMG",
        "description": "Apresentação com o tema ifslides2024 (Beamer), de Marcos Roberto Ribeiro.",
        "order": 2,
    },
    "ifmg-artigo": {
        "repo": "ribeiromarcos/iftex2024",
        "main": "exemplo_artigo.tex",
        "files": ["referencias.bib", "iftex2024.cls", "biblatexfix.sty", "LICENSE"],
        "name": "Artigo IFMG",
        "description": "Artigo acadêmico com a classe iftex2024, nas normas ABNT do IFMG, de Marcos Roberto Ribeiro.",
        "order": 3,
    },
}


class TemplateError(Exception):
    pass


def archive_url(repo: str) -> str:
    return f"https://codeload.github.com/{repo}/zip/refs/heads/main"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise TemplateError("O arquivo baixado é grande demais")
    return data


def build(tid: str, archive: bytes, dest_root: Path = EXTERNAL) -> Path:
    """Monta o modelo a partir do .zip do repositório. Só troca o modelo antigo se der certo."""
    src = SOURCES[tid]
    try:
        z = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as e:
        raise TemplateError("O arquivo baixado não é um .zip válido") from e
    # o GitHub põe tudo numa pasta "<repositório>-main/"; caminhos relativos a ela
    files = {}
    for info in z.infolist():
        parts = PurePosixPath(info.filename).parts
        if info.is_dir() or len(parts) < 2 or ".." in parts:
            continue
        files[PurePosixPath(*parts[1:]).as_posix()] = info
    wanted = {"main.tex": src["main"]}
    for f in src["files"]:
        if f.endswith("/"):
            found = [p for p in files if p.startswith(f)]
            if not found:
                raise TemplateError(f"A pasta {f} não está no repositório {src['repo']}")
            wanted.update({p: p for p in found})
        else:
            wanted[f] = f
    missing = [orig for orig in wanted.values() if orig not in files]
    if missing:
        raise TemplateError(f"Faltam arquivos no repositório {src['repo']}: {', '.join(missing)}")

    dest_root.mkdir(parents=True, exist_ok=True)
    new = dest_root / f".{tid}.novo"
    old = dest_root / f".{tid}.antigo"
    for d in (new, old):
        shutil.rmtree(d, ignore_errors=True)
    for target, orig in wanted.items():
        out = new / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(z.read(files[orig]))
    meta = {
        "name": src["name"],
        "description": src["description"],
        "order": src["order"],
        "source": f"https://github.com/{src['repo']}",
        "commit": z.comment.decode("ascii", "ignore").strip() or None,  # o GitHub grava o commit ali
    }
    (new / TEMPLATE_META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    dest = dest_root / tid
    if dest.exists():
        dest.rename(old)
    new.rename(dest)
    shutil.rmtree(old, ignore_errors=True)
    return dest


def fetch(tid: str, dest_root: Path = EXTERNAL) -> Path:
    try:
        data = _download(archive_url(SOURCES[tid]["repo"]))
    except OSError as e:
        raise TemplateError(f"Não foi possível baixar de github.com/{SOURCES[tid]['repo']}: {e}") from e
    return build(tid, data, dest_root)


def missing(dest_root: Path = EXTERNAL) -> list[str]:
    return [tid for tid in SOURCES if not (dest_root / tid / "main.tex").is_file()]


def fetch_missing_async():
    """Ao abrir o servidor: baixa, em segundo plano, os modelos que ainda não estão aqui."""
    todo = missing()
    if not todo:
        return

    def run():
        for tid in todo:
            try:
                fetch(tid)
                log.info("Modelo %s baixado de %s", tid, SOURCES[tid]["repo"])
            except TemplateError as e:
                log.warning("Modelo %s não baixado: %s", tid, e)

    threading.Thread(target=run, name="modelos", daemon=True).start()


def main():
    """Pela instalação: baixa a versão mais recente de todos os modelos."""
    ok = True
    for tid, src in SOURCES.items():
        print(f"  {src['name']:<14}", end="", flush=True)
        try:
            fetch(tid)
            print(f"pronto (github.com/{src['repo']})")
        except TemplateError as e:
            ok = False
            print(f"não foi possível: {e}")
    if not ok:
        print("  O TexDesk tenta baixar de novo quando for aberto.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
