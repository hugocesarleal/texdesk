# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização com o GitHub, contra um GitHub falso em memória (sem internet)."""

import os
import time

import pytest
from fake_github import REPO, FakeGitHub

from texdesk import github_sync as gs


@pytest.fixture()
def gh():
    return FakeGitHub()


def connect(gh, state_dir):
    """Um computador conectado ao GitHub falso (login pelo fluxo de dispositivo)."""
    c = gs.GitHubClient(state_dir, "client-id-teste", token_backend=None, open_url=gh)
    gh.authorized = False
    c.start_login()
    assert c.poll_login() == {"state": "pending"}  # ainda não digitou o código
    gh.authorized = True
    assert c.poll_login()["state"] == "done"
    return c


@pytest.fixture()
def pc(gh, tmp_path):
    """Computador A: pasta de projetos e cliente conectado."""
    projects = tmp_path / "a" / "projects"
    projects.mkdir(parents=True)
    return projects, connect(gh, tmp_path / "a" / "state")


def new_project(projects, name="TCC"):
    d = projects / name
    (d / "capitulos").mkdir(parents=True)
    (d / "main.tex").write_bytes("\\documentclass{article}\n\\begin{document}\nOlá mundo.\n\\end{document}\n".encode())
    (d / "capitulos" / "intro.tex").write_bytes(b"Primeira frase. Segunda frase.\n")
    (d / "figura.png").write_bytes(b"\x89PNG\r\n\x1a\nimagem")
    (d / ".project.json").write_text('{"githubSync": true}')
    (d / ".thumbnail.png").write_bytes(b"miniatura")
    (d / ".drive.json").write_text("{}")
    return d


def touch_later(p, text):
    """Grava com mtime diferente (alguns sistemas têm resolução de 1-2 s)."""
    old = p.stat().st_mtime
    p.write_bytes(text.encode("utf-8"))  # bytes exatos (write_text troca o fim de linha no Windows)
    os.utime(p, (old + 5, old + 5))


# ---------------------------------------------------------------- conexão


def test_login_cria_o_repositorio_privado(gh, tmp_path):
    c = connect(gh, tmp_path / "state")
    assert c.connected and c.repo == REPO
    assert c.state()["syncAll"] is True  # todos os projetos entram
    assert ("POST", "/user/repos") in gh.calls
    # num segundo computador, o repositório que já existe é reaproveitado
    gh.calls.clear()
    connect(gh, tmp_path / "outro")
    assert ("POST", "/user/repos") not in gh.calls


def test_sem_client_id_nao_tenta_entrar(tmp_path, gh):
    c = gs.GitHubClient(tmp_path, "", token_backend=None, open_url=gh)
    with pytest.raises(gs.GitHubError, match="não tem o app do GitHub"):
        c.start_login()


# ---------------------------------------------------------------- envio


def test_primeiro_envio_uma_pasta_por_projeto(gh, pc):
    projects, c = pc
    d = new_project(projects)
    sent = gs.sync_project(c, d, "TCC")
    files = gh.files()
    assert set(files) == {"README.md", "TCC/main.tex", "TCC/capitulos/intro.tex", "TCC/figura.png", "TCC/.project.json"}
    assert files["TCC/figura.png"] == (d / "figura.png").read_bytes()  # binário intacto
    assert sent == 4
    assert gh.commits[gh.head]["message"].startswith("TCC: ")
    # sem mudanças: nenhuma escrita no GitHub
    gh.calls.clear()
    assert gs.sync_project(c, d, "TCC") == 0
    assert gh.writes() == []


def test_edicao_envia_so_o_arquivo_alterado(gh, pc):
    projects, c = pc
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    touch_later(d / "main.tex", "editado\n")
    gh.calls.clear()
    assert gs.sync_project(c, d, "TCC") == 1
    # texto vai direto na árvore: árvore + commit + ref, sem blob separado
    assert [w[1].rsplit("/", 1)[-1] for w in gh.writes()] == ["trees", "commits", "main"]
    assert gh.files()["TCC/main.tex"] == b"editado\n"
    assert gs.pending_changes(d) == []


def test_apagar_e_renomear(gh, pc):
    projects, c = pc
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    (d / "figura.png").unlink()
    gs.sync_project(c, d, "TCC")
    assert "TCC/figura.png" not in gh.files()
    novo = d.rename(projects / "TCC Final")
    gh.calls.clear()
    gs.sync_project(c, novo, "TCC Final")
    assert not any(p.startswith("TCC/") for p in gh.files())
    assert gh.files()["TCC Final/main.tex"] == (novo / "main.tex").read_bytes()
    assert ("POST", f"/repos/{REPO}/git/blobs") not in gh.calls  # nada foi reenviado
    assert "renomeado" in gh.commits[gh.head]["message"]


# ---------------------------------------------------------------- dois computadores


@pytest.fixture()
def two(gh, pc, tmp_path):
    projects_a, a = pc
    da = new_project(projects_a)
    gs.sync_project(a, da, "TCC")
    projects_b = tmp_path / "b" / "projects"
    projects_b.mkdir(parents=True)
    b = connect(gh, tmp_path / "b" / "state")
    db = projects_b / "TCC"
    gs.restore_project(b, "TCC", db, "TCC")
    return (a, da), (b, db)


def test_importar_em_outro_computador(two):
    (a, da), (b, db) = two
    for rel in ("main.tex", "capitulos/intro.tex", "figura.png"):
        assert (db / rel).read_bytes() == (da / rel).read_bytes()
    assert not (db / ".thumbnail.png").exists()
    assert gs.sync_project(b, db, "TCC") == 0  # já está igual: nada a enviar


def test_traz_o_que_o_outro_computador_mudou(two):
    (a, da), (b, db) = two
    touch_later(da / "main.tex", "versão do A\n")
    (da / "notas.txt").write_bytes(b"nova")
    gs.sync_project(a, da, "TCC")
    report = {}
    gs.sync_project(b, db, "TCC", push=False, report=report)
    assert (db / "main.tex").read_text(encoding="utf-8") == "versão do A\n"
    assert (db / "notas.txt").read_text(encoding="utf-8") == "nova"
    assert sorted(report["received"]) == ["main.tex", "notas.txt"]


def test_edicoes_nos_dois_computadores_sao_juntadas(two):
    (a, da), (b, db) = two
    touch_later(da / "capitulos" / "intro.tex", "Primeira frase do A. Segunda frase.\n")
    gs.sync_project(a, da, "TCC")
    touch_later(db / "capitulos" / "intro.tex", "Primeira frase. Segunda frase do B.\n")
    report = {}
    gs.sync_project(b, db, "TCC", report=report)
    juntado = "Primeira frase do A. Segunda frase do B.\n"
    assert (db / "capitulos" / "intro.tex").read_text(encoding="utf-8") == juntado
    assert report["conflicts"] == []
    assert gs._load_base  # (o resultado da junção vai no commit do B)
    gs.sync_project(a, da, "TCC", push=False)
    assert (da / "capitulos" / "intro.tex").read_text(encoding="utf-8") == juntado


def test_mesmas_palavras_viram_conflito_e_fica_o_daqui(two):
    (a, da), (b, db) = two
    touch_later(da / "capitulos" / "intro.tex", "Primeira frase do A. Segunda frase.\n")
    gs.sync_project(a, da, "TCC")
    touch_later(db / "capitulos" / "intro.tex", "Primeira frase do B. Segunda frase.\n")
    report = {}
    gs.sync_project(b, db, "TCC", report=report)
    assert len(report["conflicts"]) == 1 and report["conflicts"][0]["path"] == "capitulos/intro.tex"
    assert "do B" in (db / "capitulos" / "intro.tex").read_text(encoding="utf-8")


def test_apagado_no_outro_computador_e_apagado_aqui(two):
    (a, da), (b, db) = two
    (da / "figura.png").unlink()
    gs.sync_project(a, da, "TCC")
    gs.sync_project(b, db, "TCC", push=False)
    assert not (db / "figura.png").exists()


def test_commit_do_outro_computador_no_meio_do_envio(gh, two):
    (a, da), (b, db) = two
    touch_later(db / "main.tex", "do B\n")
    # enquanto o B monta o commit, o A envia outro arquivo: o B traz o do A e tenta de novo
    gh.before_ref_update = lambda: gh.push_from_elsewhere({"TCC/notas.txt": b"do A"})
    gs.sync_project(b, db, "TCC")
    assert gh.files()["TCC/main.tex"] == b"do B\n"
    assert gh.files()["TCC/notas.txt"] == b"do A"
    assert (db / "notas.txt").read_bytes() == b"do A"


def test_pasta_apagada_no_github_e_enviada_de_novo(gh, two):
    (a, da), (b, db) = two
    gh.push_from_elsewhere({p: None for p in list(gh.files()) if p.startswith("TCC/")})
    gs.sync_project(a, da, "TCC")
    assert (da / "main.tex").exists()  # nada é apagado aqui
    assert gh.files()["TCC/main.tex"] == (da / "main.tex").read_bytes()


# ---------------------------------------------------------------- fila: commit 2 min depois, e ao fechar


@pytest.fixture()
def manager(pc, monkeypatch):
    projects, c = pc
    monkeypatch.setattr(gs, "COMMIT_DELAY", 0.4)
    monkeypatch.setattr(gs, "RETRY_INTERVAL", 0.2)
    m = gs.GitSyncManager(c, projects, lambda name: True)
    yield projects, c, m
    m.stopped = True
    with m.cv:
        m.cv.notify_all()


def wait(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def commits(gh):
    n, sha = 0, gh.head
    while sha:
        n += 1
        parents = gh.commits[sha]["parents"]
        sha = parents[0] if parents else None
    return n


def test_edicoes_seguidas_viram_um_commit_so(gh, manager):
    projects, c, m = manager
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    before = commits(gh)
    for i in range(5):  # cinco salvamentos, cada um antes do prazo do anterior
        touch_later(d / "main.tex", f"versão {i}\n")
        m.mark_dirty("TCC")
        time.sleep(0.1)
    assert m.get_status("TCC")["pending"]
    assert commits(gh) == before  # ainda dentro dos "2 minutos"
    assert wait(lambda: not m.get_status("TCC")["pending"] and commits(gh) == before + 1)
    assert gh.files()["TCC/main.tex"] == b"versao 4\n".replace(b"versao", "versão".encode())
    assert m.get_status("TCC")["lastCommit"]["url"].startswith(f"https://github.com/{REPO}/commit/")


def test_fechar_envia_na_hora(gh, manager, monkeypatch):
    projects, c, m = manager
    monkeypatch.setattr(gs, "COMMIT_DELAY", 3600)  # o prazo nem chegaria
    d = new_project(projects)
    m.mark_dirty("TCC")
    assert m.flush(5) is True
    assert gh.files()["TCC/main.tex"] == (d / "main.tex").read_bytes()


def test_fechar_sem_internet_desiste_no_prazo(gh, manager, monkeypatch):
    projects, c, m = manager
    monkeypatch.setattr(gs, "COMMIT_DELAY", 3600)
    new_project(projects)
    m.mark_dirty("TCC")
    gh.offline = True
    t0 = time.time()
    assert m.flush(0.5) is False
    assert time.time() - t0 < 1.5


def test_o_que_ficou_sem_commit_vai_na_proxima_abertura(gh, pc, tmp_path):
    projects, c = pc
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    # editado e o TexDesk fechado antes do commit (sem fila rodando)
    touch_later(d / "main.tex", "editado com a janela fechando\n")
    assert gs.pending_changes(d) == ["main.tex"]
    m = gs.GitSyncManager(c, projects, lambda name: True)  # TexDesk aberto de novo
    try:
        m.mark_all()
        assert wait(lambda: gh.files()["TCC/main.tex"] == b"editado com a janela fechando\n")
    finally:
        m.stopped = True
        with m.cv:
            m.cv.notify_all()


def test_limite_do_github_espera_e_tenta_de_novo(gh, manager):
    projects, c, m = manager
    new_project(projects)
    gh.rate_limited = 1
    m.commit_now("TCC")
    assert wait(lambda: m.get_status("TCC")["state"] == "waiting")
    assert wait(lambda: "TCC/main.tex" in gh.files(), timeout=8)


def test_commit_rapido_so_tres_chamadas(gh, pc):
    # ao fechar a janela o Windows dá uns 5 s: o commit se apoia no último commit conhecido
    projects, c = pc
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    touch_later(d / "main.tex", "fechando a janela\n")
    gh.calls.clear()
    gs.sync_project(c, d, "TCC")
    assert [m for m, _ in gh.calls] == ["POST", "POST", "PATCH"]
    assert gh.files()["TCC/main.tex"] == b"fechando a janela\n"


def test_commit_rapido_com_envio_de_outro_computador_no_meio(gh, pc):
    projects, c = pc
    d = new_project(projects)
    gs.sync_project(c, d, "TCC")
    gh.push_from_elsewhere({"TCC/notas.txt": b"do outro"})  # o commit conhecido ficou velho
    touch_later(d / "main.tex", "daqui\n")
    gs.sync_project(c, d, "TCC")
    assert gh.files()["TCC/main.tex"] == b"daqui\n"
    assert gh.files()["TCC/notas.txt"] == b"do outro"  # nada do outro computador se perdeu
    assert (d / "notas.txt").read_bytes() == b"do outro"


# ---------------------------------------------------------------- README do repositório


def test_readme_lista_os_projetos_e_a_ultima_atualizacao(gh, pc, tmp_path):
    projects, c = pc
    gs.sync_project(c, new_project(projects, "TCC"), "TCC")
    readme = gh.files()["README.md"].decode()
    assert "| [TCC](TCC/) |" in readme and "**1 projeto**" in readme
    assert time.strftime("%d/%m/%Y") in readme
    # outro computador (sem o README em memória) envia outro projeto: os dois aparecem,
    # o mais recente primeiro, e o TCC mantém a data dele
    other = tmp_path / "outro" / "projects"
    other.mkdir(parents=True)
    c2 = connect(gh, tmp_path / "outro" / "state")
    gs.sync_project(c2, new_project(other, "Artigo Novo"), "Artigo Novo")
    readme2 = gh.files()["README.md"].decode()
    assert readme2.index("Artigo%20Novo") < readme2.index("[TCC]") and "**2 projetos**" in readme2
    assert gs._parse_readme(gh.files()["README.md"])["TCC"] == gs._parse_readme(readme.encode())["TCC"]


def test_readme_acompanha_projeto_renomeado(gh, pc):
    projects, c = pc
    d = new_project(projects, "TCC")
    gs.sync_project(c, d, "TCC")
    novo = d.rename(projects / "TCC Final")
    gs.sync_project(c, novo, "TCC Final")
    readme = gh.files()["README.md"].decode()
    assert "[TCC Final](TCC%20Final/)" in readme and "[TCC](TCC/)" not in readme


def test_enviar_agora_nao_espera_o_prazo(gh, manager, monkeypatch):
    projects, c, m = manager
    monkeypatch.setattr(gs, "COMMIT_DELAY", 3600)
    new_project(projects)
    m.mark_dirty("TCC")  # agendado para daqui a uma hora
    m.mark_all()  # "Enviar agora" no painel
    assert wait(lambda: "TCC/main.tex" in gh.files())


def test_readme_busca_a_data_das_pastas_que_ainda_nao_estavam_na_lista(gh, pc):
    projects, c = pc
    gh.push_from_elsewhere({"Antigo/main.tex": b"enviado antes do README"})
    gs.sync_project(c, new_project(projects, "TCC"), "TCC")
    data = gs._parse_readme(gh.files()["README.md"])
    assert data["Antigo"]["at"] == 1767323045  # 02/01/2026 03:04:05 UTC, do GitHub
    assert "| [Antigo](Antigo/) | —" not in gh.files()["README.md"].decode()  # a data aparece


def test_envio_ao_fechar_nao_busca_datas(gh, pc):
    projects, c = pc
    d = new_project(projects, "TCC")
    gs.sync_project(c, d, "TCC")
    gh.push_from_elsewhere({"Antigo/main.tex": b"x"})
    gs.sync_project(c, d, "TCC", push=False)  # conhece o commit novo
    touch_later(d / "main.tex", "fechando\n")
    c.hurry = True
    gh.calls.clear()
    gs.sync_project(c, d, "TCC")
    assert not any("/commits?" in path or path.endswith("/commits") and m == "GET" for m, path in gh.calls)
