# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Ferramentas do editor: busca no projeto, contagem de palavras, histórico e corretor."""

import pytest
from conftest import APP

from texdesk import config, history, spell, texttools
from texdesk.security import CSRF_HEADER

BASE = f"http://127.0.0.1:{config.PORT}"
H = {CSRF_HEADER: "1"}


@pytest.fixture()
def c():
    return APP.test_client()


@pytest.fixture()
def proj(c):
    name = "Projeto Ferramentas"
    c.delete(f"/api/projects/{name}", base_url=BASE, headers=H)
    assert (
        c.post("/api/projects", base_url=BASE, headers=H, json={"name": name, "template": "blank"}).status_code == 200
    )
    yield name
    c.delete(f"/api/projects/{name}", base_url=BASE, headers=H)


def put(c, proj, path, content):
    r = c.put(f"/api/projects/{proj}/file", base_url=BASE, headers=H, json={"path": path, "content": content})
    assert r.status_code == 200


# ---------------------------------------------------------------- busca no projeto


def test_busca_em_todos_os_arquivos(c, proj):
    put(c, proj, "cap/um.tex", "Primeira linha\nA Uva e a uva\n")
    put(c, proj, "main.tex", "nada aqui\n")
    r = c.get(f"/api/projects/{proj}/search?q=uva", base_url=BASE).get_json()
    assert [(m["path"], m["line"], m["col"]) for m in r["results"]] == [("cap/um.tex", 2, 2), ("cap/um.tex", 2, 10)]
    r = c.get(f"/api/projects/{proj}/search?q=uva&case=1", base_url=BASE).get_json()
    assert len(r["results"]) == 1


def test_busca_palavra_inteira_e_expressao_regular(tmp_path):
    (tmp_path / "a.tex").write_text("uva uvas \\label{fig:1}\n", encoding="utf-8")
    assert len(texttools.search(tmp_path, "uva", word=True)["results"]) == 1
    assert texttools.search(tmp_path, r"fig:\d", regex=True)["results"][0]["col"] == 16


def test_busca_com_expressao_invalida_e_recusada(c, proj):
    assert c.get(f"/api/projects/{proj}/search?q=(&regex=1", base_url=BASE).status_code == 400


def test_busca_ignora_arquivos_internos(tmp_path):
    (tmp_path / ".project.json").write_text('{"uva": 1}', encoding="utf-8")
    assert texttools.search(tmp_path, "uva")["results"] == []


# ---------------------------------------------------------------- contagem de palavras


def test_contagem_de_palavras(tmp_path):
    (tmp_path / "cap.tex").write_text("Texto do capítulo incluído.\n", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{palavras}\n\\begin{document}\n"
        "\\section{Introdução ao tema}\\label{sec:intro}\n"
        "Um texto com \\textbf{cinco} palavras. % comentário não conta\n"
        "Fórmula $a+b$ e \\cite{x}.\n"
        "\\begin{equation} x = 1 \\end{equation}\n"
        "\\begin{figure}\\caption{Legenda curta}\\end{figure}\n"
        "\\input{cap}\n\\end{document}\n",
        encoding="utf-8",
    )
    r = texttools.word_count(tmp_path, "main.tex")
    assert r["headers"] == 3
    assert r["captions"] == 2
    assert r["inlineMath"] == 1 and r["displayMath"] == 1
    assert r["text"] == 5 + 2 + 4  # "Um texto com cinco palavras" + "Fórmula e" + cap.tex
    assert [f["path"] for f in r["files"]] == ["main.tex", "cap.tex"]


def test_contagem_pela_api(c, proj):
    r = c.get(f"/api/projects/{proj}/wordcount", base_url=BASE).get_json()
    assert r["words"] > 0 and r["files"][0]["path"] == "main.tex"


# ---------------------------------------------------------------- histórico de versões


def test_historico_salvar_comparar_restaurar(c, proj):
    url = f"/api/projects/{proj}/history"
    orig = c.get(f"/api/projects/{proj}/file?path=main.tex", base_url=BASE).get_json()["content"]
    sid = c.post(url, base_url=BASE, headers=H, json={"label": "Antes"}).get_json()["id"]
    put(c, proj, "main.tex", orig + "\nNovo parágrafo.\n")
    put(c, proj, "extra.tex", "arquivo novo\n")

    files = {f["path"]: f["status"] for f in c.get(f"{url}/{sid}", base_url=BASE).get_json()}
    assert files == {"main.tex": "modified", "extra.tex": "added"}
    diff = c.get(f"{url}/{sid}/diff?path=main.tex", base_url=BASE).get_json()["diff"]
    assert "+Novo parágrafo." in diff

    r = c.post(f"{url}/{sid}/restore", base_url=BASE, headers=H, json={})
    assert sorted(r.get_json()["restored"]) == ["main.tex"]
    assert c.get(f"/api/projects/{proj}/file?path=main.tex", base_url=BASE).get_json()["content"] == orig
    assert c.get(f"/api/projects/{proj}/file?path=extra.tex", base_url=BASE).status_code == 404

    # o estado de antes da restauração virou uma versão, então dá para desfazer
    versions = c.get(url, base_url=BASE).get_json()
    assert versions[0]["label"].startswith("Antes de restaurar") and versions[-1]["label"] == "Antes"


def test_versao_automatica_antes_de_editar(c, proj, monkeypatch):
    monkeypatch.setattr(history, "AUTO_INTERVAL", 0)
    put(c, proj, "main.tex", "versão 1\n")
    put(c, proj, "main.tex", "versão 2\n")
    v = history.list_versions(proj)
    assert len(v) >= 2 and all(x["auto"] for x in v)
    # nenhuma versão automática repetida: a última tem o conteúdo "versão 1"
    assert c.get(f"/api/projects/{proj}/history/{v[0]['id']}/diff?path=main.tex", base_url=BASE).get_json()["old"] == (
        "versão 1\n"
    )


def test_versoes_automaticas_antigas_sao_descartadas(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MAX_AUTO", 3)
    name = "limite-historico"
    history.delete(name)
    (tmp_path / "main.tex").write_text("0", encoding="utf-8")
    history.snapshot(tmp_path, name, label="fica", auto=False)
    for i in range(1, 7):
        (tmp_path / "main.tex").write_text(str(i), encoding="utf-8")
        history.snapshot(tmp_path, name)
    v = history.list_versions(name)
    assert len(v) == 4 and v[-1]["label"] == "fica"
    objects = list((history.HISTORY / name / "objects").glob("*/*"))
    assert len(objects) == 4  # conteúdos das versões descartadas foram apagados
    history.delete(name)


def test_historico_acompanha_renomear_e_excluir(c, proj):
    c.post(f"/api/projects/{proj}/history", base_url=BASE, headers=H, json={"label": "x"})
    c.post(f"/api/projects/{proj}/rename", base_url=BASE, headers=H, json={"name": proj + " 2"})
    assert len(history.list_versions(proj + " 2")) == 1
    c.delete(f"/api/projects/{proj} 2", base_url=BASE, headers=H)
    assert not (history.HISTORY / (proj + " 2")).exists()


def test_versao_inexistente(c, proj):
    assert c.get(f"/api/projects/{proj}/history/123", base_url=BASE).status_code == 404
    assert c.get(f"/api/projects/{proj}/history/..%2F..", base_url=BASE).status_code in (404, 400)


# ---------------------------------------------------------------- corretor ortográfico

needs_dict = pytest.mark.skipif(
    not (spell.DICT_DIR / "pt_BR.dic").exists(), reason="dicionário pt_BR não instalado (rode setup.ps1 ou setup.sh)"
)


@needs_dict
def test_corretor_portugues(c):
    r = c.post(
        "/api/spell", base_url=BASE, headers=H, json={"lang": "pt_BR", "words": ["detecção", "acurácia", "textto"]}
    )
    assert r.get_json()["unknown"] == ["textto"]
    s = c.get("/api/spell/suggest?lang=pt_BR&word=textto", base_url=BASE).get_json()
    assert s[0] == "texto"


def test_corretor_idioma_invalido(c):
    assert c.post("/api/spell", base_url=BASE, headers=H, json={"lang": "xx", "words": ["a"]}).status_code == 400
