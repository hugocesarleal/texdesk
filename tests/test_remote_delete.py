# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Projeto apagado de vez da lixeira: some também do Google Drive e do GitHub (falsos)."""

import time

import pytest
from conftest import APP
from fake_drive import FakeDrive
from fake_github import REPO, FakeGitHub

from texdesk import config, drive_sync, github_sync, remote_delete, services, trash
from texdesk.security import CSRF_HEADER

BASE = f"http://127.0.0.1:{config.PORT}"
H = {CSRF_HEADER: "1"}


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


def connect(gh, state_dir, login="fulano"):
    cl = github_sync.GitHubClient(state_dir, "x", token_backend=None, open_url=gh)
    gh.authorized, gh.login_as = False, login
    cl.start_login()
    gh.authorized = True
    assert cl.poll_login()["state"] == "done"
    return cl


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    """Drive e GitHub falsos, conectados; a fila de exclusões roda à mão (run_once)."""
    gh, drive = FakeGitHub(), FakeDrive()
    client = connect(gh, tmp_path / "gh")
    monkeypatch.setattr(services, "github", client)
    monkeypatch.setattr(services, "drive", drive)
    monkeypatch.setattr(drive, "connected", True, raising=False)
    monkeypatch.setattr(drive, "state", lambda: {}, raising=False)  # (sem "sincronizar todos")
    q = remote_delete.RemoteDeletes.__new__(remote_delete.RemoteDeletes)  # sem a thread
    q.file, q.lock, q.errors = tmp_path / "fila.json", __import__("threading").Lock(), {}
    q.wake = __import__("threading").Event()
    q.handlers = {
        "drive": services._delete_drive_folder,
        "github-folder": services._delete_github_folder,
        "github-repo": services._delete_github_repo,
        "github-leave": services._leave_github_repo,
    }
    monkeypatch.setattr(services, "remote_deletes", q)
    return gh, drive, client, q


def make_project(c, name):
    c.delete(f"/api/projects/{name}")
    for it in trash.list_items():
        if it["name"] == name:
            trash.remove(it["id"])
    c.post("/api/projects", json={"name": name})
    return config.PROJECTS / name


def sync_both(gh, drive, client, d, name):
    drive_sync.sync_project(drive, d, name)
    github_sync.sync_project(client, d, name)


def test_apagado_de_vez_some_do_drive_e_do_github(c, remote):
    gh, drive, client, q = remote
    d = make_project(c, "Para Apagar")
    sync_both(gh, drive, client, d, "Para Apagar")
    folder = drive_sync.load_manifest(d)["folderId"]
    assert "Para Apagar/main.tex" in gh.files() and drive.exists(folder)
    tid = c.delete("/api/projects/Para Apagar").get_json()["trash"]
    # na lixeira do TexDesk: continua no Drive e no GitHub (dá para restaurar como estava)
    assert q.items() == [] and drive.exists(folder) and "Para Apagar/main.tex" in gh.files()
    c.delete(f"/api/trash/{tid}")  # apagar de vez
    assert {i["kind"] for i in q.items()} == {"drive", "github-folder"}
    assert q.run_once() == 0 and q.items() == []
    assert not drive.exists(folder)  # (na lixeira do Drive)
    assert not any(p.startswith("Para Apagar/") for p in gh.files())
    assert "Para Apagar" not in gh.files()["README.md"].decode()
    assert "projeto apagado no TexDesk" in gh.commits[gh.head]["message"]


def test_restaurar_da_lixeira_nao_apaga_nada(c, remote):
    gh, drive, client, q = remote
    d = make_project(c, "Volta")
    sync_both(gh, drive, client, d, "Volta")
    tid = c.delete("/api/projects/Volta").get_json()["trash"]
    c.post(f"/api/trash/{tid}/restore", json={})
    assert q.items() == [] and "Volta/main.tex" in gh.files()
    c.delete("/api/projects/Volta")


def test_projeto_novo_com_o_mesmo_nome_nao_perde_a_pasta(c, remote):
    gh, drive, client, q = remote
    d = make_project(c, "Mesmo Nome")
    sync_both(gh, drive, client, d, "Mesmo Nome")
    tid = c.delete("/api/projects/Mesmo Nome").get_json()["trash"]
    c.post("/api/projects", json={"name": "Mesmo Nome"})  # um projeto novo, com o mesmo nome
    d2 = config.PROJECTS / "Mesmo Nome"
    sync_both(gh, drive, client, d2, "Mesmo Nome")  # pega a mesma pasta no Drive e no GitHub
    c.delete(f"/api/trash/{tid}")  # o antigo sai de vez da lixeira
    q.run_once()
    assert drive.exists(drive_sync.load_manifest(d2)["folderId"])
    assert "Mesmo Nome/main.tex" in gh.files()
    c.delete("/api/projects/Mesmo Nome")


def test_compartilhado_apaga_o_repositorio_do_dono(c, remote):
    gh, drive, client, q = remote
    d = make_project(c, "Junto")
    github_sync.sync_project(client, d, "Junto")
    full = github_sync.share_project(client, d, "Junto")
    client.view(full).invite("beltrana", write=True)
    tid = c.delete("/api/projects/Junto").get_json()["trash"]
    c.delete(f"/api/trash/{tid}")
    assert [i["kind"] for i in q.items()] == ["github-repo"]
    q.run_once()
    assert full not in gh.repos and REPO in gh.repos  # o principal nunca é apagado
    assert not gh.invites  # o convite pendente sumiu junto


def test_acesso_antigo_sem_permissao_de_apagar_espera_reconectar(c, remote, tmp_path):
    gh, drive, client, q = remote
    d = make_project(c, "Antigo")
    github_sync.sync_project(client, d, "Antigo")
    full = github_sync.share_project(client, d, "Antigo")
    gh.scope = "repo"  # entrou antes da versão que pede delete_repo
    t = client.tokens.load()
    client.tokens.save(dict(t, scope="repo"))
    tid = c.delete("/api/projects/Antigo").get_json()["trash"]
    c.delete(f"/api/trash/{tid}")
    assert q.run_once() == 1 and full in gh.repos  # fica esperando
    assert c.get("/api/github/status").get_json()["needsReconnect"] is True
    gh.scope = "repo,delete_repo"  # entrou com GitHub de novo
    client.tokens.save(dict(t, scope="repo,delete_repo"))
    assert q.run_once() == 0 and full not in gh.repos


def test_compartilhado_por_outra_pessoa_so_sai_do_projeto(c, remote, tmp_path):
    gh, drive, client, q = remote
    # beltrana compartilha com fulano (este TexDesk)
    dono = connect(gh, tmp_path / "dono", "beltrana")
    dd = tmp_path / "dono-proj" / "Dela"
    dd.mkdir(parents=True)
    (dd / "main.tex").write_bytes(b"dela\n")
    full = github_sync.share_project(dono, dd, "Dela")
    dono.view(full).invite("fulano", write=True)
    gh.login_as = "fulano"
    (inv,) = client.invitations()
    client.accept(inv["id"])
    c.delete("/api/projects/Dela")
    github_sync.restore_project(client, github_sync.SHARED_PREFIX + full, config.PROJECTS / "Dela", "Dela")
    tid = c.delete("/api/projects/Dela").get_json()["trash"]
    c.delete(f"/api/trash/{tid}")
    assert [i["kind"] for i in q.items()] == ["github-leave"]
    q.run_once()
    assert full in gh.repos and "fulano" not in gh.repos[full]["collaborators"]  # o projeto dela fica


def test_sem_internet_fica_para_depois(c, remote):
    gh, drive, client, q = remote
    d = make_project(c, "Offline")
    github_sync.sync_project(client, d, "Offline")
    tid = c.delete("/api/projects/Offline").get_json()["trash"]
    c.delete(f"/api/trash/{tid}")
    gh.offline = True
    assert q.run_once() == 1 and q.items()
    gh.offline = False
    time.sleep(0.01)
    assert q.run_once() == 0 and not any(p.startswith("Offline/") for p in gh.files())
