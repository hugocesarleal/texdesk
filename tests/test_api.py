# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""API do servidor: projetos, arquivos, modelos e compilação."""

import io
import zipfile

import pytest
from conftest import APP, FAKE_REPOS, github_zip

from texdesk import config, external_templates
from texdesk.security import CSRF_HEADER
from texdesk.storage import load_settings

BASE = f"http://127.0.0.1:{config.PORT}"
H = {CSRF_HEADER: "1"}


@pytest.fixture()
def api():
    c = APP.test_client()

    class Api:
        def get(self, path, **kw):
            return c.get(path, base_url=BASE, **kw)

        def post(self, path, **kw):
            return c.post(path, base_url=BASE, headers=H, **kw)

        def put(self, path, **kw):
            return c.put(path, base_url=BASE, headers=H, **kw)

        def delete(self, path, **kw):
            return c.delete(path, base_url=BASE, headers=H, **kw)

    return Api()


@pytest.fixture()
def proj(api):
    name = "Projeto API"
    api.delete(f"/api/projects/{name}")
    assert api.post("/api/projects", json={"name": name, "template": "blank"}).status_code == 200
    yield name
    api.delete(f"/api/projects/{name}")


# ---------------------------------------------------------------- projetos


@pytest.fixture()
def ifmg(tmp_path, monkeypatch):
    """Modelos do IFMG montados de .zip falsos, numa pasta temporária."""
    for tid in external_templates.SOURCES:
        external_templates.build(tid, github_zip(external_templates.SOURCES[tid]["repo"], FAKE_REPOS[tid]), tmp_path)
    monkeypatch.setattr(external_templates, "EXTERNAL", tmp_path)


def test_modelos_disponiveis(api, ifmg):
    ids = [t["id"] for t in api.get("/api/templates").get_json()]
    assert ids == ["blank", "ifmg-slides", "ifmg-artigo", "abnt"]


def test_modelos_do_ifmg_ainda_nao_baixados(api, tmp_path, monkeypatch):
    monkeypatch.setattr(external_templates, "EXTERNAL", tmp_path / "vazia")
    ids = [t["id"] for t in api.get("/api/templates").get_json()]
    assert ids == ["blank", "abnt"]
    assert api.post("/api/projects", json={"name": "Sem IFMG", "template": "ifmg-slides"}).status_code == 200
    api.delete("/api/projects/Sem IFMG")


def test_criar_a_partir_de_modelo_nao_copia_metadados(api, ifmg):
    api.delete("/api/projects/Slides API")
    assert api.post("/api/projects", json={"name": "Slides API", "template": "ifmg-slides"}).status_code == 200
    files = {f["path"] for f in api.get("/api/projects/Slides API/files").get_json()}
    assert {"main.tex", "ifslides2024.sty", "LICENSE"} <= files
    assert not (config.PROJECTS / "Slides API" / ".template.json").exists()
    api.delete("/api/projects/Slides API")


def test_nome_invalido_ou_repetido(api, proj):
    assert api.post("/api/projects", json={"name": "../fora", "template": "blank"}).status_code == 400
    assert api.post("/api/projects", json={"name": proj, "template": "blank"}).status_code == 409


def test_renomear_e_duplicar(api, proj):
    assert api.post(f"/api/projects/{proj}/clone", json={"name": "Copia API"}).status_code == 200
    assert api.post("/api/projects/Copia API/rename", json={"name": "Copia API 2"}).status_code == 200
    names = [p["name"] for p in api.get("/api/projects").get_json()]
    assert "Copia API 2" in names and "Copia API" not in names
    api.delete("/api/projects/Copia API 2")


def test_zip_ida_e_volta(api, proj):
    api.put(f"/api/projects/{proj}/file", json={"path": "cap/a.tex", "content": "Olá"})
    data = api.get(f"/api/projects/{proj}/zip").data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {"main.tex", "cap/a.tex"} <= set(z.namelist())
        assert not [n for n in z.namelist() if n.startswith(".")]  # arquivos internos ficam de fora
    api.delete("/api/projects/Volta API")
    r = api.post("/api/projects/upload", data={"file": (io.BytesIO(data), "x.zip"), "name": "Volta API"})
    assert r.status_code == 200
    assert api.get("/api/projects/Volta API/file?path=cap/a.tex").get_json()["content"] == "Olá"
    api.delete("/api/projects/Volta API")


def test_data_de_modificacao_com_cache(api, proj, monkeypatch):
    import os
    import time

    from texdesk import storage

    def modified():
        return next(p["modified"] for p in api.get("/api/projects").get_json() if p["name"] == proj)

    before = modified()
    time.sleep(0.05)
    api.put(f"/api/projects/{proj}/file", json={"path": "main.tex", "content": "mudou"})
    assert modified() > before  # alteração pela API: atualiza na hora, sem reler o disco

    # alteração feita fora do TexDesk: aparece na próxima releitura (aqui, forçada com TTL 0)
    f = config.PROJECTS / proj / "externo.tex"
    f.write_text("x")
    future = time.time() + 3600
    os.utime(f, (future, future))
    assert modified() < future  # ainda no cache
    monkeypatch.setattr(storage, "MTIME_TTL", 0)
    assert modified() == pytest.approx(future)


# ---------------------------------------------------------------- arquivos


def test_escrever_ler_mover_apagar(api, proj):
    assert (
        api.put(f"/api/projects/{proj}/file", json={"path": "cap/intro.tex", "content": "Introdução"}).status_code
        == 200
    )
    assert api.get(f"/api/projects/{proj}/file?path=cap/intro.tex").get_json()["content"] == "Introdução"
    assert api.post(f"/api/projects/{proj}/move", json={"from": "cap/intro.tex", "to": "intro.tex"}).status_code == 200
    paths = {f["path"] for f in api.get(f"/api/projects/{proj}/files").get_json()}
    assert "intro.tex" in paths and "cap/intro.tex" not in paths
    assert api.delete(f"/api/projects/{proj}/file?path=intro.tex").status_code == 200
    assert api.get(f"/api/projects/{proj}/file?path=intro.tex").status_code == 404


@pytest.mark.parametrize(
    "path", ["../fora.tex", "../../server.py", "cap/../../fora.tex", "/etc/passwd", "C:/Windows/x"]
)
def test_caminhos_fora_do_projeto_sao_recusados(api, proj, path):
    assert api.put(f"/api/projects/{proj}/file", json={"path": path, "content": "x"}).status_code == 400
    assert api.get(f"/api/projects/{proj}/file", query_string={"path": path}).status_code == 400


def test_zip_com_caminho_malicioso_e_recusado(api):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.tex", "ok")
        z.writestr("../../escapou.txt", "não devia sair do projeto")
    api.delete("/api/projects/Zip Ruim")
    r = api.post("/api/projects/upload", data={"file": (io.BytesIO(buf.getvalue()), "x.zip"), "name": "Zip Ruim"})
    assert r.status_code == 400
    assert not (config.PROJECTS.parent / "escapou.txt").exists()
    api.delete("/api/projects/Zip Ruim")


def test_arquivos_internos_nao_aparecem_na_arvore(api, proj):
    paths = {f["path"] for f in api.get(f"/api/projects/{proj}/files").get_json()}
    assert not [p for p in paths if p.startswith(".")]


def test_configuracoes_e_documento_principal(api, proj):
    api.put(f"/api/projects/{proj}/file", json={"path": "outro.tex", "content": "x"})
    r = api.post(f"/api/projects/{proj}/settings", json={"main": "outro.tex", "autoCompile": True})
    assert r.get_json()["main"] == "outro.tex" and r.get_json()["autoCompile"] is True
    assert api.post(f"/api/projects/{proj}/settings", json={"main": "../fora.tex"}).status_code == 400


# ---------------------------------------------------------------- compilação (precisa do Tectonic)

needs_tectonic = pytest.mark.skipif(
    not config.TECTONIC.exists(), reason="Tectonic não instalado (rode setup.ps1 ou setup.sh)"
)


@needs_tectonic
def test_compilar_documento_simples(api, proj):
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    assert r["status"] == "success" and r["pdf"]
    assert api.get(r["pdf"]).data[:4] == b"%PDF"


@needs_tectonic
def test_compilar_com_erro_aponta_arquivo_e_linha(api, proj):
    api.put(f"/api/projects/{proj}/file", json={"path": "cap/intro.tex", "content": "ok\n\\naoexiste\n"})
    api.put(
        f"/api/projects/{proj}/file",
        json={
            "path": "main.tex",
            "content": "\\documentclass{article}\n\\begin{document}\n\\input{cap/intro}\n\\end{document}\n",
        },
    )
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    errors = [e for e in r["entries"] if e["level"] == "error"]
    assert r["status"] == "error" and r["pdf"]  # gera o PDF mesmo com erro
    assert (errors[0]["file"], errors[0]["line"]) == ("cap/intro.tex", 2)


@needs_tectonic
def test_compilar_com_bibliografia_resolve_citacao(api, proj):
    bib = "@book{knuth,\n  author = {Donald Knuth},\n  title = {The TeXbook},\n  year = {1984}\n}\n"
    tex = (
        "\\documentclass{article}\n\\begin{document}\n\\section{A}\\label{s}\nVer \\ref{s} e \\cite{knuth}.\n"
        "\\bibliographystyle{plain}\n\\bibliography{refs}\n\\end{document}\n"
    )
    api.put(f"/api/projects/{proj}/file", json={"path": "refs.bib", "content": bib})
    api.put(f"/api/projects/{proj}/file", json={"path": "main.tex", "content": tex})
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    assert r["status"] == "success" and r["pdf"]
    assert "undefined" not in r["log"] and "Rerun to get" not in r["log"]
    assert "stopping at" not in r["stdout"] and "Fontconfig" not in r["stdout"]


@needs_tectonic
def test_compilacao_reaproveita_a_anterior(api, proj):
    def compilar(corpo):
        tex = "\\documentclass{article}\n\\begin{document}\n" + corpo + "\n\\end{document}\n"
        api.put(f"/api/projects/{proj}/file", json={"path": "main.tex", "content": tex})
        return api.post(f"/api/projects/{proj}/compile", json={}).get_json()

    a = "\\section{A}\\label{a}\nVer \\ref{a}."
    r = compilar(a)  # a primeira começa do zero, com todas as passadas
    assert r["status"] == "success" and not r["rerun"] and "undefined" not in r["log"]
    # com a saída anterior, uma passada já resolve a referência
    r = compilar(a + " Mais texto.")
    assert r["status"] == "success" and not r["rerun"] and "undefined" not in r["log"]
    # referência nova: a passada pede outra, que deixa tudo certo
    b = a + "\n\\section{B}\\label{b}\nVer \\ref{b}."
    assert compilar(b)["rerun"] is True
    r = compilar(b)
    assert not r["rerun"] and "undefined" not in r["log"]


@needs_tectonic
def test_depois_de_um_erro_compila_do_zero(api, proj):
    api.put(
        f"/api/projects/{proj}/file",
        json={
            "path": "main.tex",
            "content": "\\documentclass{article}\n\\begin{document}\nok\n\\naoexiste\n\\end{document}\n",
        },
    )
    assert api.post(f"/api/projects/{proj}/compile", json={}).get_json()["status"] == "error"
    assert not (config.OUTPUT / proj / "main.texdesk-ok").exists()
    tex = "\\documentclass{article}\n\\begin{document}\n\\section{A}\\label{a}\nVer \\ref{a}.\n\\end{document}\n"
    api.put(f"/api/projects/{proj}/file", json={"path": "main.tex", "content": tex})
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    # do zero, com todas as passadas: a referência nova já sai certa, sem pedir outra
    assert r["status"] == "success" and not r["rerun"] and "undefined" not in r["log"]
    assert (config.OUTPUT / proj / "main.texdesk-ok").exists()


# ---------------------------------------------------------------- importação do Drive


def test_importacao_do_drive_aparece_na_lista_enquanto_baixa(api, tmp_path, monkeypatch):
    import threading
    import time

    from fake_drive import FakeDrive

    from texdesk import drive_sync, services

    drive = FakeDrive()
    pf = drive.create_folder("Do Drive", drive.root_folder())
    drive.upload(b"\\documentclass{article}", "main.tex", pf)
    gate = threading.Event()
    download = drive.download
    drive.download = lambda fid: (gate.wait(5), download(fid))[1]
    monkeypatch.setattr(services, "importer", drive_sync.ImportQueue(drive, config.PROJECTS, services.imported))

    r = api.post("/api/drive/import", json={"id": pf, "name": "Do Drive"}).get_json()
    assert r == {"name": "Do Drive", "queued": True}
    assert api.post("/api/drive/import", json={"id": pf, "name": "Do Drive"}).status_code == 409
    (item,) = [p for p in api.get("/api/projects").get_json() if p["name"] == "Do Drive"]
    assert item["importing"]["state"] in ("queued", "importing")
    gate.set()
    for _ in range(250):
        if not services.importer.items():
            break
        time.sleep(0.02)
    (item,) = [p for p in api.get("/api/projects").get_json() if p["name"] == "Do Drive"]
    assert "importing" not in item
    assert load_settings(config.PROJECTS / "Do Drive")["driveSync"]
    api.delete("/api/projects/Do Drive")


def test_escolha_no_conflito_com_outro_computador(api, proj):
    from texdesk import history, services

    f = config.PROJECTS / proj / "texto.tex"
    f.write_bytes(b"inicio\nO gato correu.\nfim\n")
    conflito = {"id": "c1", "path": "texto.tex", "line": 1, "mine": "O gato correu.\n", "theirs": "O gato pulou.\n"}
    services.syncer.status.setdefault(proj, {})["conflicts"] = [conflito, dict(conflito, id="c2")]
    assert [c["id"] for c in api.get(f"/api/projects/{proj}/drive").get_json()["conflicts"]] == ["c1", "c2"]

    # manter a deste computador: o arquivo fica como está
    assert api.post(f"/api/projects/{proj}/drive/conflict", json={"id": "c2", "use": "mine"}).status_code == 200
    assert f.read_bytes() == b"inicio\nO gato correu.\nfim\n"
    # usar a do outro computador: troca só o trecho, guardando antes no histórico
    antes = len(history.list_versions(proj))
    assert api.post(f"/api/projects/{proj}/drive/conflict", json={"id": "c1", "use": "theirs"}).status_code == 200
    assert f.read_bytes() == b"inicio\nO gato pulou.\nfim\n"
    assert len(history.list_versions(proj)) == antes + 1
    assert api.get(f"/api/projects/{proj}/drive").get_json()["conflicts"] == []
    assert api.post(f"/api/projects/{proj}/drive/conflict", json={"id": "c1", "use": "theirs"}).status_code == 404


def test_conferencia_do_drive_sem_conexao(api, proj):
    st = api.post(f"/api/projects/{proj}/drive/check").get_json()
    assert st["connected"] is False and st["conflicts"] == []


# ---------------------------------------------------------------- PDF guardado da última compilação


@needs_tectonic
def test_ao_reabrir_mostra_o_pdf_salvo_se_nada_mudou(api, proj):
    assert api.get(f"/api/projects/{proj}/compiled").get_json() == {"fresh": False}  # nunca compilado
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    assert r["status"] == "success"
    last = api.get(f"/api/projects/{proj}/compiled?open=main.tex").get_json()
    assert last["fresh"] and last["status"] == "success" and last["main"] == "main.tex"
    assert last["entries"] == r["entries"] and last["log"] == r["log"]
    assert api.get(last["pdf"]).data[:4] == b"%PDF"
    # mudou um arquivo: precisa compilar de novo
    api.put(
        f"/api/projects/{proj}/file",
        json={"path": "main.tex", "content": "\\documentclass{article}\\begin{document}novo\\end{document}\n"},
    )
    assert api.get(f"/api/projects/{proj}/compiled").get_json() == {"fresh": False}
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    if r["rerun"]:  # passada de referências pendente: o PDF ainda não vale
        assert api.get(f"/api/projects/{proj}/compiled").get_json() == {"fresh": False}
        r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()  # a que o editor faz sozinho
    assert not r["rerun"]
    assert api.get(f"/api/projects/{proj}/compiled").get_json()["fresh"]
    # arquivo novo também conta
    api.put(f"/api/projects/{proj}/file", json={"path": "notas.txt", "content": "x"})
    assert api.get(f"/api/projects/{proj}/compiled").get_json() == {"fresh": False}


@needs_tectonic
def test_compilacao_sem_pdf_nao_deixa_pdf_salvo(api, proj):
    api.post(f"/api/projects/{proj}/compile", json={})
    api.put(
        f"/api/projects/{proj}/file",
        json={"path": "main.tex", "content": "\\documentclass{article}\n\\begin{document}\n"},
    )
    r = api.post(f"/api/projects/{proj}/compile", json={}).get_json()
    assert r["status"] == "failure"
    assert api.get(f"/api/projects/{proj}/compiled").get_json() == {"fresh": False}
