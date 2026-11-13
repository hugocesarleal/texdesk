# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Compartilhamento de projetos pelo GitHub: fulano compartilha, beltrana edita, ciclano só lê."""

import json
import os
import time

import pytest
from fake_github import REPO, FakeGitHub

from texdesk import github_sync as gs


def connect(gh, state_dir, login):
    c = gs.GitHubClient(state_dir, "client-id-teste", token_backend=None, open_url=gh)
    gh.authorized, gh.login_as = False, login
    c.start_login()
    gh.authorized = True
    assert c.poll_login()["state"] == "done"
    return c


def touch_later(p, text):
    old = p.stat().st_mtime if p.exists() else time.time()
    p.write_bytes(text.encode())
    os.utime(p, (old + 5, old + 5))


@pytest.fixture()
def gh():
    return FakeGitHub()


@pytest.fixture()
def dono(gh, tmp_path):
    """fulano, com o projeto TCC já no repositório principal, e depois compartilhado."""
    projects = tmp_path / "fulano" / "projects"
    d = projects / "TCC Engenharia"
    (d / "cap").mkdir(parents=True)
    (d / "main.tex").write_bytes(b"Texto do fulano.\n")
    (d / "cap" / "intro.tex").write_bytes(b"Primeira frase. Segunda frase.\n")
    c = connect(gh, tmp_path / "fulano" / "state", "fulano")
    gs.sync_project(c, d, "TCC Engenharia")
    full = gs.share_project(c, d, "TCC Engenharia")
    return c, d, full


def receive(gh, tmp_path, login, full):
    """login aceita o convite e baixa o projeto (como o painel faz)."""
    c = connect(gh, tmp_path / login / "state", login)
    (inv,) = c.invitations()
    c.accept(inv["id"])
    d = tmp_path / login / "projects" / inv["name"]
    gs.restore_project(c, gs.SHARED_PREFIX + full, d, inv["name"])
    return c, d, inv


def test_compartilhar_leva_o_projeto_para_um_repositorio_proprio(gh, dono):
    c, d, full = dono
    assert full == "fulano/texdesk-tcc-engenharia"
    files = gh.files(full)
    assert files["main.tex"] == b"Texto do fulano.\n" and files["cap/intro.tex"]
    assert json.loads(files[gs.SHARE_META]) == {"name": "TCC Engenharia", "owner": "fulano"}
    # saiu do repositório principal (onde o convidado veria todos os projetos)
    assert not any(p.startswith("TCC Engenharia/") for p in gh.files(REPO))
    assert "TCC Engenharia" not in gh.files(REPO)["README.md"].decode()
    m = gs.load_manifest(d)
    assert m["repo"] == full and "moveFrom" not in m
    assert not (d / gs.SHARE_META).exists()  # o arquivo de identificação fica só no GitHub
    # editar continua indo para o repositório próprio
    touch_later(d / "main.tex", "Editado depois de compartilhar.\n")
    gs.sync_project(c, d, "TCC Engenharia")
    assert gh.files(full)["main.tex"] == b"Editado depois de compartilhar.\n"


def test_convite_aceite_e_edicao_dos_dois_lados(gh, dono, tmp_path):
    c, d, full = dono
    repo = c.view(full)
    repo.invite("beltrana", write=True)
    assert repo.people() == [{"login": "beltrana", "avatar": None, "write": True, "pending": True, "invitation": 1000}]
    cb, db, inv = receive(gh, tmp_path, "beltrana", full)
    assert inv["name"] == "TCC Engenharia" and inv["from"] == "fulano" and inv["write"]
    assert (db / "cap" / "intro.tex").read_bytes() == b"Primeira frase. Segunda frase.\n"
    assert gs.load_manifest(db)["readOnly"] is False
    assert repo.people()[0]["pending"] is False
    # cada um muda uma frase; as duas edições se juntam
    touch_later(db / "cap" / "intro.tex", "Primeira frase da beltrana. Segunda frase.\n")
    gs.sync_project(cb, db, "TCC Engenharia")
    touch_later(d / "cap" / "intro.tex", "Primeira frase. Segunda frase do fulano.\n")
    gs.sync_project(c, d, "TCC Engenharia")
    juntado = b"Primeira frase da beltrana. Segunda frase do fulano.\n"
    assert (d / "cap" / "intro.tex").read_bytes() == juntado
    gs.sync_project(cb, db, "TCC Engenharia", push=False)
    assert (db / "cap" / "intro.tex").read_bytes() == juntado


def test_so_leitura_recebe_mas_nao_envia(gh, dono, tmp_path):
    c, d, full = dono
    c.view(full).invite("ciclano", write=False)
    cc, dc, inv = receive(gh, tmp_path, "ciclano", full)
    assert inv["write"] is False and gs.load_manifest(dc)["readOnly"] is True
    touch_later(dc / "main.tex", "tentativa do ciclano\n")
    gh.calls.clear()
    assert gs.sync_project(cc, dc, "TCC Engenharia") == 0
    assert gh.writes() == [] and gh.files(full)["main.tex"] == b"Texto do fulano.\n"
    touch_later(d / "cap" / "intro.tex", "Nova versão do fulano.\n")
    gs.sync_project(c, d, "TCC Engenharia")
    gs.sync_project(cc, dc, "TCC Engenharia")
    assert (dc / "cap" / "intro.tex").read_bytes() == "Nova versão do fulano.\n".encode()


def test_mudar_permissao_remover_e_sair(gh, dono, tmp_path):
    c, d, full = dono
    repo = c.view(full)
    repo.invite("beltrana", write=True)
    repo.set_permission("beltrana", False, invitation=1000)  # ainda pendente
    cb, db, inv = receive(gh, tmp_path, "beltrana", full)
    assert inv["write"] is False
    repo.set_permission("beltrana", True)  # já aceitou
    assert repo.people()[0]["write"] is True
    repo.remove("beltrana")
    assert repo.people() == []
    with pytest.raises(gs.GitHubError, match="404"):
        gs.sync_project(cb, db, "TCC Engenharia")  # sem acesso: a sincronização avisa
    repo.invite("ciclano", write=True)
    cc, dc, _ = receive(gh, tmp_path, "ciclano", full)
    cc.leave(full)
    assert repo.people() == []


def test_convites_que_nao_sao_do_texdesk_ficam_de_fora(gh, dono, tmp_path):
    c, d, full = dono
    gh.create_repo("fulano", "outro-repo", "não é do TexDesk")
    gh.invites[999] = {"repo": "fulano/outro-repo", "login": "beltrana", "write": True, "inviter": "fulano"}
    cb = connect(gh, tmp_path / "beltrana" / "state", "beltrana")
    assert cb.invitations() == []


def test_usuario_inexistente(gh, dono):
    c, d, full = dono
    with pytest.raises(gs.GitHubError, match="não encontrado"):
        c.view(full).invite("ninguem-existe", write=True)
    with pytest.raises(gs.GitHubError, match="dono"):
        c.view(full).invite("fulano", write=True)


def test_nome_ja_usado_ganha_numero(gh, tmp_path):
    gh.create_repo("fulano", "texdesk-tcc", "")
    c = connect(gh, tmp_path / "s", "fulano")
    assert c.create_shared_repo("TCC") == "fulano/texdesk-tcc-2"


def test_commit_em_30_segundos_nos_compartilhados(gh, dono, monkeypatch):
    c, d, full = dono
    m = gs.GitSyncManager(c, d.parent, lambda name: True)
    try:
        m.mark_dirty("TCC Engenharia")
        left = m.get_status("TCC Engenharia")["commitAt"] - time.time()
        assert 25 < left <= gs.SHARED_DELAY
        st = m.get_status("TCC Engenharia")
        assert st["shared"] == {"repo": full, "owner": "fulano", "mine": True}
        assert st["url"] == f"https://github.com/{full}"
    finally:
        m.stopped = True
        with m.cv:
            m.cv.notify_all()


def test_permissao_mudada_pelo_dono_e_percebida(gh, dono, tmp_path):
    c, d, full = dono
    c.view(full).invite("beltrana", write=True)
    cb, db, _ = receive(gh, tmp_path, "beltrana", full)
    m = gs.GitSyncManager(cb, db.parent, lambda name: True)
    try:
        c.view(full).set_permission("beltrana", False)  # o dono passa para "só ler"
        touch_later(db / "main.tex", "tentativa depois de virar leitora\n")
        m.commit_now("TCC Engenharia")
        end = time.time() + 5
        while time.time() < end and not gs.load_manifest(db).get("readOnly"):
            time.sleep(0.05)
        assert gs.load_manifest(db)["readOnly"] is True
        st = m.get_status("TCC Engenharia")
        assert st["readOnly"] and st["state"] != "error"  # segue recebendo, sem erro
        assert gh.files(full)["main.tex"] == b"Texto do fulano.\n"
        # e o contrário: volta a poder editar (conferido de tempos em tempos)
        c.view(full).set_permission("beltrana", True)
        m.PERMISSION_EVERY = 0
        m.check("TCC Engenharia")
        end = time.time() + 5
        while time.time() < end and gs.load_manifest(db).get("readOnly"):
            time.sleep(0.05)
        assert gs.load_manifest(db)["readOnly"] is False
    finally:
        m.stopped = True
        with m.cv:
            m.cv.notify_all()


def test_repositorio_compartilhado_so_tem_o_projeto(gh, dono):
    c, d, full = dono
    assert set(gh.files(full)) == {gs.SHARE_META, "main.tex", "cap/intro.tex"}  # sem README do GitHub
