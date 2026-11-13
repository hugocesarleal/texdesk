# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Rotas do GitHub e o envio ao fechar o TexDesk, com o GitHub falso (sem internet)."""

import os
import time

import pytest
from conftest import APP
from fake_github import REPO, FakeGitHub

from texdesk import config, github_sync, services
from texdesk.security import CSRF_HEADER

BASE = f"http://127.0.0.1:{config.PORT}"
H = {CSRF_HEADER: "1"}


@pytest.fixture()
def gh(tmp_path, monkeypatch):
    """O TexDesk dos testes conectado a um GitHub falso, com commit 0,3 s depois da alteração."""
    fake = FakeGitHub()
    monkeypatch.setattr(github_sync, "COMMIT_DELAY", 0.3)
    client = github_sync.GitHubClient(tmp_path / "gh", "client-id-teste", token_backend=None, open_url=fake)
    manager = github_sync.GitSyncManager(client, config.PROJECTS, services.github_enabled)
    monkeypatch.setattr(services, "github", client)
    monkeypatch.setattr(services, "gitsync", manager)
    monkeypatch.setattr(services.gh_importer, "client", client)  # a fila usa o mesmo cliente
    yield fake
    manager.stopped = True
    with manager.cv:
        manager.cv.notify_all()


@pytest.fixture()
def c():
    client = APP.test_client()

    class Api:
        def get(self, path):
            return client.get(path, base_url=BASE)

        def post(self, path, **kw):
            return client.post(path, base_url=BASE, headers=H, **kw)

        def put(self, path, **kw):
            return client.put(path, base_url=BASE, headers=H, **kw)

        def delete(self, path):
            return client.delete(path, base_url=BASE, headers=H)

    return Api()


def wait(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def login(c, fake):
    r = c.post("/api/github/login/start").get_json()
    assert r["userCode"] == "ABCD-1234" and r["verificationUri"] == "https://github.com/login/device"
    assert c.post("/api/github/login/poll").get_json()["state"] == "pending"
    fake.authorized = True
    assert c.post("/api/github/login/poll").get_json()["state"] == "done"


def test_sem_app_configurado(c):
    st = c.get("/api/github/status").get_json()
    assert st["configured"] is False and st["connected"] is False
    assert c.post("/api/github/login/start").status_code == 502


def test_entrar_envia_todos_os_projetos(c, gh):
    c.delete("/api/projects/Com GitHub")
    c.post("/api/projects", json={"name": "Com GitHub"})
    login(c, gh)
    st = c.get("/api/github/status").get_json()
    assert st["connected"] and st["repo"] == REPO and st["syncAll"]
    assert c.get("/api/projects/Com GitHub/settings").get_json()["githubSync"] is True
    assert wait(lambda: "Com GitHub/main.tex" in gh.files())
    item = next(p for p in c.get("/api/projects").get_json() if p["name"] == "Com GitHub")
    assert wait(lambda: c.get("/api/projects/Com GitHub/github").get_json().get("lastCommit"))
    assert item["github"]["enabled"]
    # edição: fica pendente, com a hora do commit, e sai sozinha
    c.put("/api/projects/Com GitHub/file", json={"path": "main.tex", "content": "editado\n"})
    st = c.get("/api/projects/Com GitHub/github").get_json()
    assert st["pending"] and st["commitAt"] > time.time()
    assert wait(lambda: gh.files().get("Com GitHub/main.tex") == b"editado\n")
    # commit na hora (editor fechando)
    c.put("/api/projects/Com GitHub/file", json={"path": "main.tex", "content": "fechando\n"})
    github_sync.COMMIT_DELAY = 3600  # (o monkeypatch da fixture desfaz no fim)
    c.post("/api/projects/Com GitHub/github/commit")
    assert wait(lambda: gh.files().get("Com GitHub/main.tex") == b"fechando\n")
    c.delete("/api/projects/Com GitHub")


def test_importar_projeto_do_repositorio(c, gh):
    login(c, gh)
    gh.push_from_elsewhere({"Do Notebook/main.tex": b"\\documentclass{article}", "Do Notebook/fig.png": b"\x89PNG"})
    cands = c.get("/api/github/import-candidates").get_json()
    assert {"id": "Do Notebook", "name": "Do Notebook"} in cands
    c.delete("/api/projects/Do Notebook")
    assert c.post("/api/github/import", json={"id": "Do Notebook"}).get_json() == {
        "name": "Do Notebook",
        "queued": True,
    }
    item = next(p for p in c.get("/api/projects").get_json() if p["name"] == "Do Notebook")
    assert item["importing"]["source"] == "github"
    assert wait(lambda: (config.PROJECTS / "Do Notebook" / "fig.png").exists() and not services.gh_importer.items())
    assert c.get("/api/projects/Do Notebook/settings").get_json()["githubSync"] is True
    assert "Do Notebook" not in [x["id"] for x in c.get("/api/github/import-candidates").get_json()]
    c.delete("/api/projects/Do Notebook")


def test_copia_de_projeto_nao_herda_a_pasta_do_github(c, gh):
    c.delete("/api/projects/Original")
    c.delete("/api/projects/Copia")
    c.post("/api/projects", json={"name": "Original"})
    login(c, gh)
    assert wait(lambda: (config.PROJECTS / "Original" / github_sync.MANIFEST).exists())
    c.post("/api/projects/Original/clone", json={"name": "Copia"})
    assert not (config.PROJECTS / "Copia" / github_sync.MANIFEST).exists()
    c.delete("/api/projects/Original")
    c.delete("/api/projects/Copia")


@pytest.mark.skipif(os.name != "nt", reason="tratador do console do Windows")
def test_fechar_a_janela_chama_o_envio():
    import ctypes

    from texdesk.__main__ import on_close

    calls = []
    ref = on_close(lambda: calls.append(1))
    try:
        assert ref(0) == 0 and calls == []  # Ctrl+C: segue para o KeyboardInterrupt
        ref(2)  # janela do terminal fechada
        ref(6)  # computador desligando
        assert calls == [1, 1]
    finally:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(ref, False)


# ---------------------------------------------------------------- compartilhamento


def test_compartilhar_pelo_editor_e_receber_convite(c, gh, tmp_path):
    c.delete("/api/projects/Artigo Junto")
    c.post("/api/projects", json={"name": "Artigo Junto"})
    login(c, gh)
    assert wait(lambda: "Artigo Junto/main.tex" in gh.files())
    st = c.get("/api/projects/Artigo Junto/share").get_json()
    assert st["connected"] and st["shared"] is None
    r = c.post("/api/projects/Artigo Junto/share", json={"login": "@beltrana", "write": True}).get_json()
    full = "fulano/texdesk-artigo-junto"
    assert r["shared"]["repo"] == full and r["shared"]["mine"]
    assert r["people"] == [{"login": "beltrana", "avatar": None, "write": True, "pending": True, "invitation": 1000}]
    assert "main.tex" in gh.files(full) and "Artigo Junto/main.tex" not in gh.files()
    # usuário que não existe: erro claro
    bad = c.post("/api/projects/Artigo Junto/share", json={"login": "nao-existe-ninguem", "write": True})
    assert bad.status_code == 400 and "não encontrado" in bad.get_json()["error"]
    # projeto aparece como compartilhado na lista, com commit em 30 s
    c.put("/api/projects/Artigo Junto/file", json={"path": "main.tex", "content": "junto\n"})
    st = c.get("/api/projects/Artigo Junto/github").get_json()
    assert st["shared"]["mine"] and st["commitAt"] - time.time() <= github_sync.SHARED_DELAY
    # permissão e remoção
    r = c.post(
        "/api/projects/Artigo Junto/share/permission", json={"login": "beltrana", "write": False, "invitation": 1000}
    )
    assert r.get_json()["people"][0]["write"] is False
    r = c.post("/api/projects/Artigo Junto/share/remove", json={"login": "beltrana", "invitation": 1000})
    assert r.get_json()["people"] == []
    c.delete("/api/projects/Artigo Junto")


def test_aceitar_convite_baixa_o_projeto_so_leitura(c, gh, tmp_path):
    # fulano (outro computador) compartilha só para leitura com beltrana, que usa este TexDesk
    dono = github_sync.GitHubClient(tmp_path / "dono", "x", token_backend=None, open_url=gh)
    gh.login_as = "fulano"
    login_direto = dono.start_login()  # noqa: F841
    gh.authorized = True
    dono.poll_login()
    d = tmp_path / "dono-projetos" / "Relatorio"
    d.mkdir(parents=True)
    (d / "main.tex").write_bytes(b"do fulano\n")
    github_sync.share_project(dono, d, "Relatorio")
    dono.view("fulano/texdesk-relatorio").invite("beltrana", write=False)
    gh.authorized, gh.login_as = False, "beltrana"
    login(c, gh)
    (inv,) = c.get("/api/github/invitations").get_json()
    assert inv["name"] == "Relatorio" and inv["from"] == "fulano" and inv["write"] is False
    c.delete("/api/projects/Relatorio")
    r = c.post(f"/api/github/invitations/{inv['id']}/accept").get_json()
    assert r == {"name": "Relatorio", "queued": True}
    assert wait(lambda: (config.PROJECTS / "Relatorio" / "main.tex").exists() and not services.gh_importer.items())
    st = c.get("/api/projects/Relatorio/share").get_json()
    assert st["readOnly"] and st["shared"]["owner"] == "fulano" and not st["shared"]["mine"]
    # só leitura: o servidor recusa gravar
    put = c.put("/api/projects/Relatorio/file", json={"path": "main.tex", "content": "mexi\n"})
    assert put.status_code == 403 and "só para leitura" in put.get_json()["error"]
    assert c.post("/api/projects/Relatorio/upload", data={}).status_code == 403
    # sair do projeto: a cópia fica, sem sincronizar
    assert c.post("/api/projects/Relatorio/share/leave").get_json() == {"ok": True}
    assert not (config.PROJECTS / "Relatorio" / github_sync.MANIFEST).exists()
    assert (
        c.put("/api/projects/Relatorio/file", json={"path": "main.tex", "content": "agora é meu\n"}).status_code == 200
    )
    c.delete("/api/projects/Relatorio")


def test_duplicar_enquanto_a_sincronizacao_grava_o_manifesto(c, monkeypatch):
    # regressão: o .github.json.tmp sumia no meio da cópia e a duplicação falhava (Windows)
    c.delete("/api/projects/Orig Tmp")
    c.delete("/api/projects/Copia Tmp")
    c.post("/api/projects", json={"name": "Orig Tmp"})
    d = config.PROJECTS / "Orig Tmp"
    (d / ".github.json.tmp").write_text("{}")
    (d / ".drive.json").write_text("{}")
    assert c.post("/api/projects/Orig Tmp/clone", json={"name": "Copia Tmp"}).status_code == 200
    copia = config.PROJECTS / "Copia Tmp"
    assert (copia / "main.tex").exists()
    assert not (copia / ".github.json.tmp").exists() and not (copia / ".drive.json").exists()
    c.delete("/api/projects/Orig Tmp")
    c.delete("/api/projects/Copia Tmp")
