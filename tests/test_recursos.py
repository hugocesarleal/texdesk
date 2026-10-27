# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Lixeira, organização do painel, conflitos ao salvar, substituir, dicionário pessoal,
referências por DOI e o manifesto do aplicativo."""

import json
import os
import time

import pytest
from conftest import APP

from texdesk import config, online, spell, texttools, trash
from texdesk.security import CSRF_HEADER

BASE = f"http://127.0.0.1:{config.PORT}"
H = {CSRF_HEADER: "1"}


@pytest.fixture()
def c():
    return APP.test_client()


def req(c, method, path, **kw):
    return getattr(c, method)(path, base_url=BASE, headers=H, **kw)


@pytest.fixture()
def proj(c):
    name = "Projeto Recursos"
    req(c, "delete", f"/api/projects/{name}")
    assert req(c, "post", "/api/projects", json={"name": name, "template": "blank"}).status_code == 200
    yield name
    req(c, "delete", f"/api/projects/{name}")
    trash.empty()


# ---------------------------------------------------------------- lixeira


def test_excluir_vai_para_a_lixeira_e_volta(c, proj):
    req(c, "put", f"/api/projects/{proj}/file", json={"path": "main.tex", "content": "versão 1"})
    req(c, "post", f"/api/projects/{proj}/history", json={"label": "marco"})
    r = req(c, "delete", f"/api/projects/{proj}")
    assert r.status_code == 200
    assert not (config.PROJECTS / proj).exists()
    items = c.get("/api/trash", base_url=BASE).get_json()
    item = next(i for i in items if i["name"] == proj)
    assert item["expires"] - item["deleted"] == pytest.approx(trash.TRASH_DAYS * 86400)

    r = req(c, "post", f"/api/trash/{item['id']}/restore")
    assert r.get_json()["name"] == proj
    assert (config.PROJECTS / proj / "main.tex").read_text(encoding="utf-8") == "versão 1"
    # o histórico volta junto
    versions = c.get(f"/api/projects/{proj}/history", base_url=BASE).get_json()
    assert any(v["label"] == "marco" for v in versions)
    assert all(i["id"] != item["id"] for i in c.get("/api/trash", base_url=BASE).get_json())


def test_restaurar_com_nome_ocupado(c, proj):
    tid = trash.put(proj)
    assert req(c, "post", "/api/projects", json={"name": proj, "template": "blank"}).status_code == 200
    r = req(c, "post", f"/api/trash/{tid}/restore")
    novo = r.get_json()["name"]
    assert novo == f"{proj} (restaurado)"
    req(c, "delete", f"/api/projects/{novo}")


def test_lixeira_apaga_itens_antigos(c, proj):
    tid = trash.put(proj)
    # simula um item excluído há 31 dias
    info = trash.TRASH / tid / "info.json"
    meta = json.loads(info.read_text(encoding="utf-8"))
    meta["deleted"] = time.time() - 31 * 86400
    info.write_text(json.dumps(meta), encoding="utf-8")
    assert all(i["id"] != tid for i in c.get("/api/trash", base_url=BASE).get_json())
    assert not (trash.TRASH / tid).exists()


def test_apagar_de_vez_e_esvaziar(c, proj):
    tid = trash.put(proj)
    assert req(c, "delete", f"/api/trash/{tid}").status_code == 200
    assert not (trash.TRASH / tid).exists()
    assert req(c, "delete", "/api/trash/123").status_code == 404
    assert req(c, "post", "/api/trash/../x/restore").status_code in (404, 405)


# ---------------------------------------------------------------- etiquetas e projetos fixados


def test_etiquetas_e_fixar(c, proj):
    r = req(c, "post", f"/api/projects/{proj}/organize", json={"tags": [" TCC ", "tcc", "Artigos", ""], "pinned": True})
    assert r.get_json() == {"tags": ["TCC", "Artigos"], "pinned": True}
    item = next(p for p in c.get("/api/projects", base_url=BASE).get_json() if p["name"] == proj)
    assert item["tags"] == ["TCC", "Artigos"] and item["pinned"] is True
    # mudar as configurações do projeto não apaga as etiquetas
    req(c, "post", f"/api/projects/{proj}/settings", json={"autoCompile": True})
    item = next(p for p in c.get("/api/projects", base_url=BASE).get_json() if p["name"] == proj)
    assert item["tags"] == ["TCC", "Artigos"]


def test_nome_com_parenteses(c, proj):
    r = req(c, "post", f"/api/projects/{proj}/clone", json={"name": f"{proj} (cópia)"})
    assert r.status_code == 200
    req(c, "delete", f"/api/projects/{proj} (cópia)")


# ---------------------------------------------------------------- conflito ao salvar


def test_conflito_quando_o_arquivo_muda_fora(c, proj):
    url = f"/api/projects/{proj}/file"
    aberto = c.get(f"{url}?path=main.tex", base_url=BASE).get_json()
    # outro programa grava o arquivo depois que o editor o abriu
    p = config.PROJECTS / proj / "main.tex"
    p.write_text("mudou fora", encoding="utf-8")
    os.utime(p, (aberto["mtime"] + 5, aberto["mtime"] + 5))
    r = req(c, "put", url, json={"path": "main.tex", "content": "minha versão", "mtime": aberto["mtime"]})
    assert r.status_code == 409
    assert r.get_json()["conflict"] is True and r.get_json()["content"] == "mudou fora"
    assert p.read_text(encoding="utf-8") == "mudou fora"
    # o usuário escolhe manter a dele
    mine = {"path": "main.tex", "content": "minha versão", "mtime": aberto["mtime"]}
    r = req(c, "put", url, json={**mine, "force": True})
    assert r.status_code == 200
    assert p.read_text(encoding="utf-8") == "minha versão"
    # salvar com a data devolvida não dá conflito
    r2 = req(c, "put", url, json={"path": "main.tex", "content": "de novo", "mtime": r.get_json()["mtime"]})
    assert r2.status_code == 200


def test_arvore_tem_data_de_modificacao(c, proj):
    files = c.get(f"/api/projects/{proj}/files", base_url=BASE).get_json()
    assert next(f for f in files if f["path"] == "main.tex")["mtime"] > 0


# ---------------------------------------------------------------- substituir em todos os arquivos


def test_substituir(tmp_path):
    (tmp_path / "a.tex").write_bytes(b"Ola mundo\r\nmundo \\textbf{mundo}\r\n")
    (tmp_path / "b.tex").write_text("nada aqui\n", encoding="utf-8")
    (tmp_path / ".oculto.tex").write_text("mundo\n", encoding="utf-8")
    changed = texttools.replace(tmp_path, "mundo", "\\emph{terra}")
    assert changed == {"a.tex": 3}
    # barras invertidas ficam literais e as quebras de linha CRLF são mantidas
    assert (tmp_path / "a.tex").read_bytes() == b"Ola \\emph{terra}\r\n\\emph{terra} \\textbf{\\emph{terra}}\r\n"
    assert (tmp_path / ".oculto.tex").read_text(encoding="utf-8") == "mundo\n"


def test_substituir_regex_e_palavra(tmp_path):
    (tmp_path / "a.tex").write_text("cap 1, cap 22, capa\n", encoding="utf-8")
    assert texttools.replace(tmp_path, r"cap (\d+)", "Capítulo $1", regex=True) == {"a.tex": 2}
    assert (tmp_path / "a.tex").read_text(encoding="utf-8") == "Capítulo 1, Capítulo 22, capa\n"
    assert texttools.replace(tmp_path, "capa", "X", word=True, paths=["outro.tex"]) == {}


def test_substituir_pela_api_guarda_versao(c, proj):
    req(c, "put", f"/api/projects/{proj}/file", json={"path": "cap.tex", "content": "gato e gato"})
    r = req(c, "post", f"/api/projects/{proj}/replace", json={"q": "gato", "replacement": "cão"})
    assert r.get_json()["changed"] == {"cap.tex": 2}
    assert (config.PROJECTS / proj / "cap.tex").read_text(encoding="utf-8") == "cão e cão"
    versions = c.get(f"/api/projects/{proj}/history", base_url=BASE).get_json()
    assert versions[0]["label"].startswith("Antes de substituir")
    assert req(c, "post", f"/api/projects/{proj}/replace", json={"q": "(", "regex": True}).status_code == 400


# ---------------------------------------------------------------- dicionário pessoal


def test_dicionario_pessoal(c):
    spell.PERSONAL.unlink(missing_ok=True)
    assert c.get("/api/spell/dictionary", base_url=BASE).get_json() == []
    r = req(c, "post", "/api/spell/dictionary", json={"add": ["TexDesk", "texdesk", "Overleaf", ""]})
    assert r.get_json() == ["overleaf", "texdesk"]
    r = req(c, "post", "/api/spell/dictionary", json={"remove": ["OVERLEAF"]})
    assert r.get_json() == ["texdesk"]
    assert req(c, "post", "/api/spell/dictionary", json={"add": "texto"}).status_code == 400
    spell.PERSONAL.unlink(missing_ok=True)


# ---------------------------------------------------------------- DOI e versão nova (sem internet)


def test_normalizar_doi():
    assert online.normalize_doi("https://doi.org/10.1038/nature14539") == "10.1038/nature14539"
    assert online.normalize_doi(" doi:10.1000/ABC(1)x ") == "10.1000/ABC(1)x"
    assert online.normalize_doi("http://dx.doi.org/10.5555%2F12345678") == "10.5555/12345678"
    with pytest.raises(online.OnlineError):
        online.normalize_doi("nature14539")


def test_formatar_bibtex():
    raw = (
        " @article{LeCun_2015, title={Deep {L}earning}, volume={521}, "
        'journal="Nature", month=may, author={LeCun, Yann and Bengio, Yoshua}, abstract={Longo...}}'
    )
    key, bib = online.format_bibtex(raw)
    assert key == "LeCun_2015"
    assert bib == (
        "@article{LeCun_2015,\n"
        "  title   = {Deep {L}earning},\n"
        "  volume  = {521},\n"
        '  journal = "Nature",\n'
        "  month   = may,\n"
        "  author  = {LeCun, Yann and Bengio, Yoshua}\n"
        "}\n"
    )


def test_doi_invalido_pela_api(c):
    r = c.get("/api/doi?doi=abc", base_url=BASE)
    assert r.status_code == 400 and "DOI" in r.get_json()["error"]


def test_aviso_de_versao_desligado_nos_testes(c):
    assert c.get("/api/update", base_url=BASE).get_json() is None


def test_comparar_versoes():
    assert online._version_tuple("v0.10.0") > online._version_tuple("0.9.3")


# ---------------------------------------------------------------- aplicativo instalável


def test_manifesto(c):
    r = c.get("/manifest.webmanifest", base_url=BASE)
    assert r.status_code == 200 and r.mimetype == "application/manifest+json"
    data = r.get_json(force=True)
    assert data["start_url"] == "/" and data["display"] == "standalone"
    for icon in data["icons"]:
        assert c.get(icon["src"], base_url=BASE).status_code == 200


# ---------------------------------------------------------------- vários documentos no projeto


def test_compila_o_documento_aberto(tmp_path):
    from texdesk.storage import compile_target

    doc = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"
    (tmp_path / "main.tex").write_text(doc % r"\input{capitulos/um}", encoding="utf-8")
    (tmp_path / "roteiro.tex").write_text(doc % r"\include{anexo} % \input{capitulos/um}", encoding="utf-8")
    (tmp_path / "capitulos").mkdir()
    (tmp_path / "capitulos" / "um.tex").write_text(r"\input{capitulos/dois}", encoding="utf-8")
    (tmp_path / "capitulos" / "dois.tex").write_text("texto", encoding="utf-8")
    (tmp_path / "anexo.tex").write_text("anexo", encoding="utf-8")
    (tmp_path / "solto.tex").write_text("ninguém inclui", encoding="utf-8")
    # um documento completo compila a si mesmo
    assert compile_target(tmp_path, "main.tex", "roteiro.tex") == "roteiro.tex"
    # um capítulo compila quem o inclui, mesmo indiretamente (o \input comentado não conta)
    assert compile_target(tmp_path, "roteiro.tex", "capitulos/dois.tex") == "main.tex"
    assert compile_target(tmp_path, "main.tex", "anexo.tex") == "roteiro.tex"
    # o resto mantém o principal
    assert compile_target(tmp_path, "main.tex", "solto.tex") == "main.tex"
    assert compile_target(tmp_path, "main.tex", "referencias.bib") == "main.tex"
    assert compile_target(tmp_path, "main.tex", "") == "main.tex"


def test_compilar_desligado_mantem_o_principal(c, proj):
    from texdesk.storage import load_settings, project_dir

    doc = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    req(c, "put", f"/api/projects/{proj}/file", json={"path": "outro.tex", "content": doc})
    req(c, "post", f"/api/projects/{proj}/settings", json={"followOpen": False})
    req(c, "post", f"/api/projects/{proj}/compile", json={"open": "outro.tex"})
    assert load_settings(project_dir(proj))["main"] == "main.tex"
    req(c, "post", f"/api/projects/{proj}/settings", json={"followOpen": True})
    r = req(c, "post", f"/api/projects/{proj}/compile", json={"open": "outro.tex"}).get_json()
    assert load_settings(project_dir(proj))["main"] == "outro.tex"
    assert r.get("main", "outro.tex") == "outro.tex"
