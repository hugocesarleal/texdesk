# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Atualização pelo próprio TexDesk, com um botão no painel.

Instalado por um pacote de release: baixa o pacote do sistema, confere o SHA-256 publicado
pelo GitHub, troca o código e as ferramentas e reinicia o servidor. Os dados (projetos, PDFs,
histórico, lixeira, conexão com o Drive) nunca são tocados.
Instalado com git clone: roda "git pull" e reinicia.

O reinício acontece no mesmo processo que o iniciar.bat/.sh abriu: o servidor antigo para de
atender, abre o novo como processo filho e espera por ele. Assim a janela continua a mesma.
"""

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__
from .config import ROOT
from .online import RELEASES_API, USER_AGENT, _version_tuple, update_check_enabled

log = logging.getLogger(__name__)

WORK_DIR = ".update"  # dentro da pasta do TexDesk: o pacote baixado, a extração e o backup
# a pasta tools/ é mesclada (guarda os dicionários baixados depois); as outras pastas do pacote
# (texdesk/, static/, templates/) são trocadas inteiras, para não sobrar arquivo antigo
MERGE_DIRS = {"tools"}

_state = {"stage": "idle", "percent": 0, "error": None, "version": None}
_lock = threading.Lock()
BOOT = time.time()  # muda quando o servidor reinicia: a interface sabe que o novo já abriu
restart_hook = None  # o __main__ registra aqui como parar o servidor


class UpdateError(Exception):
    """Falha que vira mensagem para o usuário."""


def platform_target(system=None, machine=None):
    """O alvo do pacote de release deste computador (windows-x64, linux-arm64…), ou None."""
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if not arch:
        return None
    if system.startswith("win"):
        return "windows-x64" if arch == "x64" else None
    if system.startswith("linux"):
        return f"linux-{arch}"
    if system == "darwin":
        return f"macos-{arch}"
    return None


def install_kind(root: Path = ROOT):
    """Como instalar: "git" (clonado), "package" (pacote de release) ou None (só o link)."""
    if (root / ".git").exists():
        return "git" if shutil.which("git") else None
    if (root / "VERSION").is_file() and platform_target():
        return "package"
    return None


def status():
    with _lock:
        return dict(_state, current=__version__, boot=BOOT)


def _set(**kw):
    with _lock:
        _state.update(kw)


def start(root: Path = ROOT):
    """Começa a atualização em segundo plano (a interface acompanha por status())."""
    if not update_check_enabled():
        raise UpdateError("A busca por versões novas está desligada (TEXDESK_UPDATE_CHECK=0)")
    kind = install_kind(root)
    if not kind:
        raise UpdateError("Esta instalação não pode ser atualizada sozinha. Baixe o pacote novo no GitHub.")
    with _lock:
        if _state["stage"] not in ("idle", "error"):
            raise UpdateError("A atualização já está em andamento")
        _state.update(stage="checking", percent=0, error=None, version=None)
    threading.Thread(target=_run, args=(root, kind), daemon=True, name="update").start()


def _run(root, kind):
    try:
        if kind == "git":
            _set(stage="installing")
            _git_pull(root)
        else:
            release = _get_json(RELEASES_API)
            version = (release.get("tag_name") or "").lstrip("v")
            if not version or _version_tuple(version) <= _version_tuple(__version__):
                raise UpdateError("Você já está na versão mais nova")
            _set(version=version)
            name = f"texdesk-{version}-{platform_target()}" + (".zip" if os.name == "nt" else ".tar.gz")
            asset = next((a for a in release.get("assets", []) if a.get("name") == name), None)
            if not asset:
                raise UpdateError(f"A versão {version} não tem pacote para este sistema ({name})")
            work = root / WORK_DIR
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir()
            archive = work / name
            _set(stage="downloading")
            _download(asset["browser_download_url"], archive, asset.get("size") or 0)
            _set(stage="installing", percent=100)
            verify(archive, asset.get("size"), asset.get("digest"))
            install_package(root, archive, version)
        log.info("Atualização instalada (%s); reiniciando o servidor", kind)
        _set(stage="restarting")
        if restart_hook:
            threading.Timer(0.5, restart_hook).start()  # dá tempo da interface ver "reiniciando"
    except UpdateError as e:
        log.warning("Atualização não concluída: %s", e)
        _set(stage="error", error=str(e))
    except Exception as e:  # rede, disco cheio, arquivo em uso…
        log.exception("Erro inesperado na atualização")
        _set(stage="error", error=f"A atualização falhou e nada foi alterado: {e}")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (URL fixa, https)
            return json.loads(r.read().decode("utf-8"))
    except OSError as e:
        raise UpdateError("Não foi possível falar com o GitHub. Confira a conexão com a internet.") from e


def _download(url, dest: Path, size: int):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:  # noqa: S310
            total = size or int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if total:
                    _set(percent=min(99, done * 100 // total))
    except OSError as e:
        raise UpdateError("O download do pacote falhou. Confira a conexão com a internet e tente de novo.") from e


def verify(archive: Path, size=None, digest=None):
    """Confere o tamanho e o SHA-256 que o GitHub publica para cada arquivo da release."""
    if size and archive.stat().st_size != size:
        raise UpdateError("O pacote baixado está incompleto. Tente de novo.")
    if digest:
        algo, _, expected = digest.partition(":")
        if algo != "sha256":
            raise UpdateError(f"Assinatura do pacote em formato desconhecido ({algo})")
        h = hashlib.sha256()
        with archive.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        if h.hexdigest() != expected.lower():
            raise UpdateError("O pacote baixado não confere com o publicado no GitHub. Nada foi alterado.")


def _safe_member(name: str):
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        raise UpdateError(f"Pacote inválido: caminho inseguro ({name})")


def extract(archive: Path, dest: Path):
    """Extrai o pacote recusando caminhos para fora da pasta e links."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                _safe_member(n)
            z.extractall(dest)
    else:
        with tarfile.open(archive, "r:gz") as t:
            members = t.getmembers()
            for m in members:
                _safe_member(m.name)
                if not (m.isfile() or m.isdir()):
                    raise UpdateError(f"Pacote inválido: {m.name} não é arquivo nem pasta")
            if hasattr(tarfile, "data_filter"):
                t.extractall(dest, members, filter="data")
            else:  # Python sem os filtros de extração (3.10/3.11 antigos): já conferido acima
                t.extractall(dest, members)  # noqa: S202
    tops = [p for p in dest.iterdir() if p.is_dir()]
    if len(tops) != 1 or not (tops[0] / "texdesk" / "__init__.py").is_file():
        raise UpdateError("Pacote inválido: não é um pacote do TexDesk")
    return tops[0]


def _same(a: Path, b: Path):
    if not b.is_file() or a.stat().st_size != b.stat().st_size:
        return False
    return a.read_bytes() == b.read_bytes()


def install_package(root: Path, archive: Path, version: str):
    """Troca o código pelo do pacote. Se algo falhar no meio, volta tudo como estava."""
    work = root / WORK_DIR
    new = extract(archive, work / "novo")
    found = (new / "VERSION").read_text(encoding="utf-8").strip() if (new / "VERSION").is_file() else ""
    if found != version:
        raise UpdateError(f"Pacote inválido: esperava a versão {version} e veio {found or 'nenhuma'}")
    backup = work / "antigo"
    backup.mkdir()
    done = []  # (destino, backup ou None) para desfazer
    try:
        for src in sorted(new.iterdir()):
            dst = root / src.name
            if src.is_dir() and src.name in MERGE_DIRS:
                _merge(src, dst)
            elif src.is_dir():
                old = backup / src.name
                if dst.exists():
                    dst.rename(old)
                    done.append((dst, old))
                else:
                    done.append((dst, None))
                src.rename(dst)
            elif not _same(src, dst):
                # o iniciar.bat em execução é relido pelo cmd depois que o Python sai: só é
                # trocado quando muda de verdade
                old = backup / src.name
                if dst.exists():
                    shutil.copy2(dst, old)
                done.append((dst, old if dst.exists() else None))
                shutil.copy2(src, dst)
    except Exception:
        log.exception("Falha ao instalar a atualização; restaurando a versão anterior")
        for dst, old in reversed(done):
            if dst.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
            elif dst.exists() and old is None:
                dst.unlink()
            if old is not None:
                if old.is_dir():
                    old.rename(dst)
                else:
                    shutil.copy2(old, dst)
        raise
    log.info("TexDesk atualizado de %s para %s", __version__, version)


def _merge(src: Path, dst: Path):
    """Copia as ferramentas novas por cima, sem apagar o que só existe na instalação."""
    for f in src.rglob("*"):
        target = dst / f.relative_to(src)
        if f.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not _same(f, target):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
            except OSError as e:  # ex.: tectonic.exe em uso por uma compilação: fica o antigo
                log.warning("Não foi possível atualizar %s: %s", target, e)


def cleanup(root: Path = ROOT):
    """Na abertura seguinte: apaga o pacote baixado e o backup da versão anterior."""
    shutil.rmtree(root / WORK_DIR, ignore_errors=True)


def _git_pull(root):
    r = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise UpdateError("O git pull falhou: " + (msg[-1] if msg else f"código {r.returncode}"))


def run_new_server():
    """Depois que o servidor antigo parou: abre o novo e espera por ele (mesma janela)."""
    time.sleep(0.5)
    return subprocess.call([sys.executable, "-m", "texdesk"], cwd=ROOT)
