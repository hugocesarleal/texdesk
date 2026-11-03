# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Modelos do IFMG, montados a partir de .zip falsos no formato do GitHub (sem internet)."""

import json

import pytest
from conftest import FAKE_REPOS, github_zip

from texdesk import external_templates as ext


def build(tid, tmp_path, files=None):
    return ext.build(tid, github_zip(ext.SOURCES[tid]["repo"], files or FAKE_REPOS[tid]), tmp_path)


def test_copia_so_os_arquivos_do_modelo_sem_mudar_nada(tmp_path):
    d = build("ifmg-slides", tmp_path)
    got = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())
    assert got == [
        ".template.json",
        "LICENSE",
        "biblatexfix.sty",
        "figuras/if_q.pdf",
        "ifslides2024.sty",
        "main.tex",
        "referencias.bib",
    ]
    assert (d / "main.tex").read_text() == FAKE_REPOS["ifmg-slides"]["apresentacao.tex"]
    assert (d / "figuras/if_q.pdf").read_bytes() == FAKE_REPOS["ifmg-slides"]["figuras/if_q.pdf"]
    meta = json.loads((d / ".template.json").read_text(encoding="utf-8"))
    assert meta["source"] == "https://github.com/ribeiromarcos/ifslides2024"
    assert meta["commit"] == "0123abc"


def test_arquivo_faltando_mantem_o_modelo_anterior(tmp_path):
    d = build("ifmg-artigo", tmp_path)
    files = dict(FAKE_REPOS["ifmg-artigo"])
    del files["iftex2024.cls"]
    with pytest.raises(ext.TemplateError, match="iftex2024.cls"):
        build("ifmg-artigo", tmp_path, files)
    assert (d / "iftex2024.cls").read_text() == "% classe"


def test_atualiza_por_cima_sem_sobrar_arquivo_antigo(tmp_path):
    d = build("ifmg-slides", tmp_path)
    (d / "sobra.txt").write_text("x")
    files = dict(FAKE_REPOS["ifmg-slides"], **{"referencias.bib": "@misc{novo}"})
    build("ifmg-slides", tmp_path, files)
    assert not (d / "sobra.txt").exists()
    assert (d / "referencias.bib").read_text() == "@misc{novo}"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ifmg-slides"]


def test_zip_invalido(tmp_path):
    with pytest.raises(ext.TemplateError, match="zip"):
        ext.build("ifmg-slides", b"isto nao e zip", tmp_path)


def test_baixa_da_branch_main_do_autor(tmp_path, monkeypatch):
    urls = []

    def fake_download(url):
        urls.append(url)
        tid = next(t for t, s in ext.SOURCES.items() if s["repo"] in url)
        return github_zip(ext.SOURCES[tid]["repo"], FAKE_REPOS[tid])

    monkeypatch.setattr(ext, "_download", fake_download)
    assert ext.missing(tmp_path) == ["ifmg-slides", "ifmg-artigo"]
    for tid in ext.SOURCES:
        ext.fetch(tid, tmp_path)
    assert urls == [
        "https://codeload.github.com/ribeiromarcos/ifslides2024/zip/refs/heads/main",
        "https://codeload.github.com/ribeiromarcos/iftex2024/zip/refs/heads/main",
    ]
    assert ext.missing(tmp_path) == []


def test_sem_internet(tmp_path, monkeypatch):
    def offline(url):
        raise OSError("sem rede")

    monkeypatch.setattr(ext, "_download", offline)
    with pytest.raises(ext.TemplateError, match="github.com/ribeiromarcos"):
        ext.fetch("ifmg-artigo", tmp_path)
    assert ext.missing(tmp_path) == ["ifmg-slides", "ifmg-artigo"]
