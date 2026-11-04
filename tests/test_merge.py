# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Junção de duas versões de um arquivo de texto (merge.py)."""

from texdesk.merge import apply_choice, merge3

BASE = "\\section{Introdução}\nO gato subiu no telhado. O cachorro latiu.\n\nSegundo parágrafo.\n\\end{document}\n"


def test_so_um_lado_mudou():
    outro = BASE.replace("Segundo", "Outro")
    assert merge3(BASE, BASE, outro) == (outro, [])
    assert merge3(BASE, outro, BASE) == (outro, [])
    assert merge3(BASE, outro, outro) == (outro, [])


def test_linhas_diferentes_se_juntam():
    meu = BASE.replace("\\section{Introdução}", "\\section{Introdução geral}")
    deles = BASE.replace("Segundo parágrafo.", "Segundo parágrafo, revisado.")
    texto, conflitos = merge3(BASE, meu, deles)
    assert conflitos == []
    assert "Introdução geral" in texto and "revisado" in texto


def test_frases_diferentes_do_mesmo_paragrafo_se_juntam():
    """No LaTeX um parágrafo é uma linha só: a junção desce até as palavras."""
    meu = BASE.replace("subiu", "pulou")
    deles = BASE.replace("latiu", "dormiu")
    texto, conflitos = merge3(BASE, meu, deles)
    assert conflitos == []
    assert "O gato pulou no telhado. O cachorro dormiu." in texto


def test_linhas_vizinhas_alteradas_se_juntam():
    base = "a\nb\nc\n"
    texto, conflitos = merge3(base, "a\nB\nc\n", "a\nb\nC\n")
    assert (texto, conflitos) == ("a\nB\nC\n", [])


def test_insercoes_nos_dois_lados_em_lugares_diferentes():
    meu = BASE.replace("\\end{document}", "Conclusão.\n\\end{document}")
    deles = "% comentário\n" + BASE
    texto, conflitos = merge3(BASE, meu, deles)
    assert conflitos == []
    assert texto.startswith("% comentário\n") and "Conclusão.\n\\end{document}" in texto


def test_mesmas_palavras_dos_dois_lados_e_conflito():
    meu = BASE.replace("subiu", "correu")
    deles = BASE.replace("subiu", "pulou").replace("Segundo", "Outro")
    texto, conflitos = merge3(BASE, meu, deles)
    # no trecho em conflito fica a versão deste computador; o resto é juntado
    assert "O gato correu" in texto and "Outro parágrafo." in texto
    assert conflitos == [
        {
            "line": 1,
            "mine": "O gato correu no telhado. O cachorro latiu.\n",
            "theirs": "O gato pulou no telhado. O cachorro latiu.\n",
        }
    ]
    # escolher a versão do outro computador troca só aquele trecho
    assert apply_choice(texto, conflitos[0]) == deles


def test_apagado_de_um_lado_e_alterado_do_outro_e_conflito():
    meu = BASE.replace("Segundo parágrafo.\n", "")
    deles = BASE.replace("Segundo", "Outro")
    texto, conflitos = merge3(BASE, meu, deles)
    assert texto == meu
    assert conflitos == [{"line": 3, "mine": "", "theirs": "Outro parágrafo.\n"}]
    assert apply_choice(texto, conflitos[0]) == deles


def test_escolha_procura_o_trecho_se_as_linhas_mudaram():
    c = {"line": 0, "mine": "linha minha\n", "theirs": "linha deles\n"}
    assert apply_choice("nova\nlinha minha\nfim\n", c) == "nova\nlinha deles\nfim\n"
    assert apply_choice("o trecho sumiu\n", c) is None


def test_quebras_de_linha_do_windows_sao_mantidas():
    base = "a\r\nb\r\nc\r\n"
    texto, conflitos = merge3(base, "A\r\nb\r\nc\r\n", "a\r\nb\r\nC\r\n")
    assert (texto, conflitos) == ("A\r\nb\r\nC\r\n", [])
