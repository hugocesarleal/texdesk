# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""SyncTeX: código -> PDF e PDF -> código, com o .synctex.gz do fixture."""
from conftest import FIXTURES
from synctex import SyncTex

PROJ = FIXTURES / "projeto_com_erros"
ST = SyncTex(PROJ / "out" / "main.synctex.gz", PROJ, PROJ)

PAGE_W, PAGE_H = 612, 792  # página carta, em pontos PDF


def inside_page(box):
    return 0 <= box["x"] <= PAGE_W and 0 <= box["y"] <= PAGE_H


def test_codigo_para_pdf_no_arquivo_principal():
    boxes = ST.view("main.tex", 12)
    assert boxes and boxes[0]["page"] == 1 and inside_page(boxes[0])


def test_codigo_para_pdf_em_arquivo_incluido():
    boxes = ST.view("capitulos/intro.tex", 2)
    assert boxes and inside_page(boxes[0])


def test_ordem_vertical_acompanha_o_codigo():
    """A introdução (incluída antes) fica acima do texto final no PDF."""
    intro = ST.view("capitulos/intro.tex", 1)[0]
    fim = ST.view("main.tex", 12)[0]
    assert intro["y"] < fim["y"]


def test_pdf_para_codigo_volta_para_perto_da_linha():
    box = ST.view("main.tex", 12)[0]
    hit = ST.edit(box["page"], box["x"] + 2, box["y"] + box["h"] / 2)
    assert hit["file"] == "main.tex" and abs(hit["line"] - 12) <= 1


def test_pdf_para_codigo_em_arquivo_incluido():
    box = ST.view("capitulos/intro.tex", 2)[0]
    hit = ST.edit(box["page"], box["x"] + 2, box["y"] + box["h"] / 2)
    assert hit["file"] == "capitulos/intro.tex"


def test_arquivo_que_nao_esta_no_documento():
    assert ST.view("nao-existe.tex", 1) == []
