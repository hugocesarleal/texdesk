# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Atalho do TexDesk na área de trabalho, com o logo, que abre o iniciar.bat/.sh.

Na primeira abertura (e de novo se o atalho for apagado) o painel pergunta se o usuário quer
o atalho, até ele responder "Agora não". O atalho aponta para a
pasta atual do TexDesk: se ela for movida, o painel percebe (a pasta guardada no estado é
outra) e pergunta se quer atualizar o atalho.

- Windows: TexDesk.lnk (criado pelo WScript.Shell, com o static/icons/texdesk.ico)
- Linux: TexDesk.desktop (abre o iniciar.sh num terminal)
- macOS: TexDesk.command (o Terminal abre e roda o iniciar.sh; o ícone vem do NSWorkspace)
"""

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import DATA, ROOT

log = logging.getLogger(__name__)

STATE_FILE = ".shortcut.json"  # nos dados do usuário: se o atalho foi criado, onde e para qual pasta
NAME = "TexDesk"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ShortcutError(Exception):
    """Falha que vira mensagem para o usuário."""


def _system():
    return "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"


def desktop_dir():
    """A pasta da área de trabalho (no Windows ela pode estar no OneDrive ou em outro disco)."""
    if os.environ.get("TEXDESK_DESKTOP"):  # os testes usam uma pasta temporária
        return Path(os.environ["TEXDESK_DESKTOP"])
    if _system() == "windows":
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:  # CSIDL_DESKTOPDIRECTORY
            return Path(buf.value)
    elif _system() == "linux" and shutil.which("xdg-user-dir"):
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Desktop"


def launcher(root: Path = ROOT):
    return root / ("iniciar.bat" if _system() == "windows" else "iniciar.sh")


def shortcut_file(desktop: Path):
    return desktop / (NAME + {"windows": ".lnk", "macos": ".command", "linux": ".desktop"}[_system()])


def _load():
    try:
        return json.loads((DATA / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state):
    (DATA / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def status():
    """{ask: "create" | "update" | None, path, oldRoot, root, system} para o painel."""
    state = _load()
    path = Path(state["path"]) if state.get("path") else shortcut_file(desktop_dir())
    exists = path.exists()
    ask = None
    if not launcher().is_file():
        ask = None  # instalação sem o script de iniciar (ex.: rodando só com python -m texdesk)
    elif state.get("declined"):
        ask = None  # respondeu "Agora não" (o botão no fim do painel ainda cria o atalho)
    elif not state.get("path") or not exists:
        ask = "create"  # primeira abertura, ou o atalho foi apagado
    elif state.get("root") != str(ROOT):
        ask = "update"  # a pasta do TexDesk mudou de lugar e o atalho aponta para a antiga
    return {
        "ask": ask,
        "exists": exists and bool(state.get("path")),
        "path": str(path),
        "root": str(ROOT),
        "oldRoot": state.get("root"),
        "system": _system(),
    }


def decline():
    """'Agora não': não pergunta de novo (o atalho continua disponível no painel)."""
    state = _load()
    if status()["ask"] == "update":
        state["root"] = str(ROOT)  # não pergunta de novo para esta pasta, mas pergunta se o atalho sumir
    else:
        state["declined"] = True  # não quer o atalho: criar pelo botão desfaz isto
    _save(state)


def create(root: Path = ROOT):
    """Cria (ou atualiza) o atalho na área de trabalho e devolve o caminho dele."""
    state = _load()
    target = launcher(root)
    if not target.is_file():
        raise ShortcutError(f"Não encontrei {target.name} na pasta do TexDesk")
    old = Path(state["path"]) if state.get("path") else None
    path = old if old and old.exists() else shortcut_file(desktop_dir())
    if not path.parent.is_dir():
        raise ShortcutError(f"Não encontrei a área de trabalho ({path.parent})")
    try:
        {"windows": _windows, "macos": _macos, "linux": _linux}[_system()](path, target, root)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Não foi possível criar o atalho em %s: %s", path, e)
        raise ShortcutError(f"Não foi possível criar o atalho: {e}") from e
    log.info("Atalho na área de trabalho: %s -> %s", path, target)
    _save({"path": str(path), "root": str(root)})
    return str(path)


def _windows(path: Path, target: Path, root: Path):
    # os caminhos vão por variáveis de ambiente: acentos e aspas no caminho não quebram o comando
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TD_LNK);"
        "$s.TargetPath = $env:TD_TARGET; $s.WorkingDirectory = $env:TD_DIR;"
        "$s.IconLocation = $env:TD_ICON + ',0'; $s.Description = 'TexDesk: editor LaTeX'; $s.Save()"
    )
    env = {
        **os.environ,
        "TD_LNK": str(path),
        "TD_TARGET": str(target),
        "TD_DIR": str(root),
        "TD_ICON": str(root / "static" / "icons" / "texdesk.ico"),
    }
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=NO_WINDOW,
    )
    if r.returncode != 0 or not path.exists():
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise OSError(lines[-1] if lines else f"PowerShell terminou com o código {r.returncode}")


def _desktop_quote(p: Path):
    """Caminho entre aspas para o Exec= de um .desktop (a especificação pede escapar \\ " ` $)."""
    s = str(p)
    for c in '\\"`$':
        s = s.replace(c, "\\" + c)
    return f'"{s}"'


def _linux(path: Path, target: Path, root: Path):
    icon = root / "static" / "icons" / "icon-512.png"
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Editor LaTeX\n"
        f"Exec={_desktop_quote(target)}\n"
        f"Path={root}\n"
        f"Icon={icon}\n"
        "Terminal=true\n"
        "Categories=Office;Publishing;\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    if shutil.which("gio"):  # GNOME: sem isto o atalho pede "Permitir executar" no primeiro clique
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"], capture_output=True, timeout=10)


def _macos(path: Path, target: Path, root: Path):
    path.write_text(f"#!/bin/bash\nexec {shlex.quote(str(target))}\n", encoding="utf-8")
    path.chmod(0o755)
    icon = root / "static" / "icons" / "icon-512.png"
    js = (
        "function run(argv) { ObjC.import('AppKit');"
        " $.NSWorkspace.sharedWorkspace.setIconForFileOptions("
        "$.NSImage.alloc.initWithContentsOfFile(argv[0]), argv[1], 0); }"
    )
    # o ícone é um extra: sem ele o atalho funciona do mesmo jeito
    subprocess.run(["osascript", "-l", "JavaScript", "-e", js, str(icon), str(path)], capture_output=True, timeout=30)
