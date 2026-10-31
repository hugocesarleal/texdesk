# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Atalho na área de trabalho, numa área de trabalho temporária."""

import json
import sys

import pytest

from texdesk import shortcut
from texdesk.config import DATA, ROOT


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXDESK_DESKTOP", str(tmp_path))
    state = DATA / shortcut.STATE_FILE
    state.unlink(missing_ok=True)
    yield tmp_path
    state.unlink(missing_ok=True)


@pytest.fixture
def fake_writer(monkeypatch):
    """Troca o criador do sistema por um que só grava o destino (sem PowerShell nem gio)."""
    made = []

    def write(path, target, root):
        path.write_text(str(target), encoding="utf-8")
        made.append((path, target, root))

    for name in ("_windows", "_linux", "_macos"):
        monkeypatch.setattr(shortcut, name, write)
    return made


def test_primeira_abertura_pergunta_e_cria(desktop, fake_writer):
    assert shortcut.status()["ask"] == "create"
    path = shortcut.create()
    assert path == str(shortcut.shortcut_file(desktop))
    assert fake_writer[0][1] == shortcut.launcher(ROOT)
    s = shortcut.status()
    assert s["ask"] is None and s["exists"]


def test_agora_nao_nao_pergunta_de_novo(desktop, fake_writer):
    shortcut.decline()
    assert shortcut.status()["ask"] is None
    assert not fake_writer


def test_pasta_movida_pergunta_e_atualiza_o_mesmo_atalho(desktop, fake_writer):
    shortcut.create()
    state = DATA / shortcut.STATE_FILE
    old = json.loads(state.read_text(encoding="utf-8"))
    state.write_text(json.dumps({**old, "root": "C:/pasta antiga/TexDesk"}), encoding="utf-8")
    s = shortcut.status()
    assert s["ask"] == "update" and s["oldRoot"] == "C:/pasta antiga/TexDesk" and s["root"] == str(ROOT)
    assert shortcut.create() == old["path"]  # reescreve o atalho que já existia
    assert shortcut.status()["ask"] is None


def test_recusar_a_atualizacao_nao_pergunta_de_novo(desktop, fake_writer):
    shortcut.create()
    state = DATA / shortcut.STATE_FILE
    state.write_text(json.dumps({**json.loads(state.read_text()), "root": "/antiga"}), encoding="utf-8")
    shortcut.decline()
    assert shortcut.status()["ask"] is None


def test_atalho_apagado_pergunta_de_novo(desktop, fake_writer):
    shortcut.create()
    shortcut.shortcut_file(desktop).unlink()
    assert shortcut.status()["ask"] == "create"
    shortcut.decline()  # "Agora não": aí para de perguntar
    assert shortcut.status()["ask"] is None
    shortcut.create()  # o botão do painel cria de novo e volta a acompanhar o atalho
    shortcut.shortcut_file(desktop).unlink()
    assert shortcut.status()["ask"] == "create"


def test_atalho_apagado_depois_de_recusar_a_atualizacao_pergunta(desktop, fake_writer):
    shortcut.create()
    state = DATA / shortcut.STATE_FILE
    state.write_text(json.dumps({**json.loads(state.read_text()), "root": "/antiga"}), encoding="utf-8")
    shortcut.decline()  # não quis atualizar
    shortcut.shortcut_file(desktop).unlink()
    assert shortcut.status()["ask"] == "create"


def test_desktop_do_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(shortcut.shutil, "which", lambda _: None)  # sem o gio
    root = tmp_path / 'Meus "programas" $HOME' / "TexDesk"
    path = tmp_path / "TexDesk.desktop"
    shortcut._linux(path, root / "iniciar.sh", root)
    text = path.read_text(encoding="utf-8")
    assert "Exec=" + shortcut._desktop_quote(root / "iniciar.sh") in text
    assert '\\"programas\\" \\$HOME' in text  # aspas e $ escapados, como pede a especificação
    assert f"Icon={root / 'static' / 'icons' / 'icon-512.png'}" in text and "Terminal=true" in text


@pytest.mark.skipif(sys.platform != "win32", reason="atalho .lnk só existe no Windows")
def test_atalho_de_verdade_no_windows(desktop):
    path = shortcut.create()
    assert path.endswith("TexDesk.lnk")
    data = open(path, "rb").read()
    assert data[:4] == b"\x4c\x00\x00\x00"  # cabeçalho de um .lnk
    assert "iniciar.bat".encode("utf-16-le") in data and "texdesk.ico".encode("utf-16-le") in data
