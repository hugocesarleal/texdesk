# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Funções auxiliares da compilação (sem rodar o Tectonic)."""

import pytest

from texdesk.compiler import clean_output, uses_bibliography


@pytest.mark.parametrize(
    "content, expected",
    [
        (r"\bibliography{refs}", True),
        (r"\addbibresource{refs.bib}", True),
        (r"texto \printbibliography[heading=none]", True),
        (r"% \bibliography{refs}", False),
        (r"sem nada \bibliographystyle{plain}", False),
        (r"100\% certo", False),
    ],
)
def test_detecta_bibliografia(tmp_path, content, expected):
    (tmp_path / "cap").mkdir()
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (tmp_path / "cap" / "fim.tex").write_text(content + "\n", encoding="utf-8")
    assert uses_bibliography(tmp_path) is expected


def test_ignora_pastas_ocultas(tmp_path):
    (tmp_path / ".drive").mkdir()
    (tmp_path / ".drive" / "x.tex").write_text("\\bibliography{a}\n", encoding="utf-8")
    assert uses_bibliography(tmp_path) is False


def test_saida_sem_ruido_e_sem_repeticoes():
    out = clean_output(
        "Fontconfig error: Cannot load default config file: No such file: (null)\n"
        "warning: main.tex:3: Overfull \\hbox\n"
        "warning: internal consistency problem when checking if main.bbl changed\n"
        "warning: main.tex:3: Overfull \\hbox\n"
        "warning: TeX rerun seems needed, but stopping at 6 passes\n"
        "note: Writing main.pdf\n"
    )
    assert out.splitlines()[:2] == ["warning: main.tex:3: Overfull \\hbox", "note: Writing main.pdf"]
    assert "Fontconfig" not in out and "consistency" not in out and "stopping" not in out
    assert "1 linha(s) repetida(s)" in out


def test_saida_limpa_fica_igual():
    assert clean_output("note: Writing main.pdf\n") == "note: Writing main.pdf"
