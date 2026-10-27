# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Leitor do log do TeX: erros e avisos no arquivo e na linha certos."""

from conftest import FIXTURES

from texdesk.latexlog import parse_log, unwrap

LOG = (FIXTURES / "projeto_com_erros" / "out" / "main.log").read_text(encoding="utf-8")
KNOWN = {"main.tex", "capitulos/intro.tex"}


def by_level(entries, level):
    return [e for e in entries if e["level"] == level]


def test_erro_em_arquivo_incluido_aponta_para_o_arquivo_certo():
    """\\input{capitulos/intro} aparece no log sem extensão: "(capitulos/intro"."""
    errors = by_level(parse_log(LOG, "", "main.tex", KNOWN), "error")
    assert [(e["file"], e["line"], e["message"]) for e in errors] == [
        ("capitulos/intro.tex", 2, "Undefined control sequence.")
    ]
    assert "\\comandoquenaoexiste" in errors[0]["content"]


def test_sem_lista_de_arquivos_ainda_reconhece_caminho_com_pasta():
    errors = by_level(parse_log(LOG, "", "main.tex"), "error")
    assert errors[0]["file"] == "capitulos/intro.tex"


def test_aviso_de_referencia_indefinida_com_linha():
    warnings = by_level(parse_log(LOG, "", "main.tex", KNOWN), "warning")
    ref = [w for w in warnings if "sec:inexistente" in w["message"]]
    assert ref and ref[0]["file"] == "main.tex" and ref[0]["line"] == 7


def test_caixa_overfull():
    boxes = by_level(parse_log(LOG, "", "main.tex", KNOWN), "typesetting")
    assert boxes and boxes[0]["line"] == 9 and boxes[0]["message"].startswith("Overfull \\hbox")


def test_erros_vem_antes_dos_avisos():
    levels = [e["level"] for e in parse_log(LOG, "", "main.tex", KNOWN)]
    assert levels == sorted(levels, key=["error", "warning", "typesetting"].index)


def test_documento_principal_em_subpasta():
    """Com o documento em tese/main.tex, os caminhos do log são relativos a tese/."""
    log = "(./main.tex\n(./cap1.tex\n! Undefined control sequence.\nl.4 \\foo\n\n)\n)"
    errors = by_level(parse_log(log, "tese", "tese/main.tex", {"tese/main.tex", "tese/cap1.tex"}), "error")
    assert errors[0]["file"] == "tese/cap1.tex" and errors[0]["line"] == 4


def test_input_sem_pasta_e_sem_extensao_precisa_da_lista_de_arquivos():
    log = "(./main.tex\n(intro\n! Missing $ inserted.\nl.3 x^2\n\n)\n)"
    with_known = by_level(parse_log(log, "", "main.tex", {"main.tex", "intro.tex"}), "error")
    assert with_known[0]["file"] == "intro.tex"
    # sem a lista, "(intro" poderia ser só texto entre parênteses: fica no arquivo de fora
    assert by_level(parse_log(log, "", "main.tex"), "error")[0]["file"] == "main.tex"


def test_erro_de_pacote_tira_o_prefixo():
    log = "(./main.tex\n! LaTeX Error: File `inexistente.sty' not found.\n\nl.3 \\usepackage{inexistente}\n)"
    e = by_level(parse_log(log), "error")[0]
    assert e["message"] == "File `inexistente.sty' not found." and e["line"] == 3


def test_arquivo_do_sistema_e_marcado_como_externo():
    log = "(/usr/share/texmf/tex/latex/base/article.cls\n! Undefined control sequence.\nl.10 \\x\n)"
    e = by_level(parse_log(log), "error")[0]
    assert e.get("external") is True


def test_linhas_quebradas_em_79_colunas_sao_reunidas():
    long_line = "x" * 79
    assert unwrap(long_line + "\nfim") == [long_line + "fim"]
    assert unwrap("curta\noutra") == ["curta", "outra"]
