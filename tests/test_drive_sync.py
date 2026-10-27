# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização com o Google Drive, contra um Drive falso em memória."""

import os
import time

import pytest
from fake_drive import FakeDrive

from texdesk import drive_sync as ds


@pytest.fixture()
def drive():
    return FakeDrive()


@pytest.fixture()
def project(tmp_path):
    d = tmp_path / "Relatorio"
    (d / "capitulos").mkdir(parents=True)
    (d / "main.tex").write_text("\\documentclass{report}\n\\begin{document}\n\\end{document}\n")
    (d / "capitulos" / "introducao.tex").write_text("\\chapter{Introdução}\n")
    (d / "capitulos" / "metodologia.tex").write_text("\\chapter{Metodologia}\n")
    (d / ".project.json").write_text('{"main": "main.tex"}')
    (d / ".thumbnail.png").write_bytes(b"png")
    return d


def folder_of(drive, name):
    return drive.find_child(drive.root_folder(), name, True)


def touch_later(path, text):
    """Grava com mtime diferente do anterior (alguns sistemas têm resolução de 1-2 s)."""
    old = path.stat().st_mtime
    path.write_text(text)
    os.utime(path, (old + 5, old + 5))


# ---------------------------------------------------------------- envio


def test_envio_inicial_espelha_os_arquivos(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    remote = drive.tree(folder_of(drive, "Relatorio"))
    # miniatura e manifesto não vão para o Drive; .project.json (configurações) vai
    assert set(remote) == {"main.tex", "capitulos/introducao.tex", "capitulos/metodologia.tex", ".project.json"}


def test_sem_mudancas_nao_chama_o_drive(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.calls.clear()
    assert ds.sync_project(drive, project, "Relatorio") == 0
    assert drive.calls == []


def test_edicao_envia_so_o_arquivo_alterado(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    touch_later(project / "main.tex", "% editado\n")
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.calls == [("upload", "main.tex", True)]  # atualização, não arquivo novo
    assert drive.tree(folder_of(drive, "Relatorio"))["main.tex"] == (project / "main.tex").read_bytes()


def test_arquivo_tocado_sem_mudar_conteudo_nao_e_reenviado(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    st = (project / "main.tex").stat()
    os.utime(project / "main.tex", (st.st_atime, st.st_mtime + 10))
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.uploads() == []


def test_renomear_e_apagar_vai_para_a_lixeira(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    (project / "capitulos" / "introducao.tex").rename(project / "intro.tex")
    (project / "capitulos" / "metodologia.tex").unlink()
    (project / "capitulos").rmdir()
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert set(drive.tree(folder_of(drive, "Relatorio"))) == {"main.tex", "intro.tex", ".project.json"}
    assert ("trash", "capitulos") in drive.calls


def test_renomear_projeto_renomeia_a_pasta(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    novo = project.rename(project.parent / "Relatorio Final")
    drive.calls.clear()
    ds.sync_project(drive, novo, "Relatorio Final")
    assert drive.calls == [("rename", "Relatorio Final")]


# ---------------------------------------------------------------- restauração


def test_restaurar_baixa_arquivos_identicos(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    pf = folder_of(drive, "Relatorio")
    dest = tmp_path / "outra-maquina" / "Relatorio"
    n = ds.restore_project(drive, pf, dest, "Relatorio")
    remote = drive.tree(pf)
    assert n == len(remote)
    assert all((dest / k).read_bytes() == v for k, v in remote.items())
    drive.calls.clear()
    ds.sync_project(drive, dest, "Relatorio")
    assert drive.calls == []  # depois de restaurar, nada a enviar


def test_restaurar_com_outro_nome_renomeia_a_pasta(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    dest = tmp_path / "x" / "Relatorio-2"
    ds.restore_project(drive, folder_of(drive, "Relatorio"), dest, "Relatorio")
    drive.calls.clear()
    ds.sync_project(drive, dest, "Relatorio-2")
    assert drive.calls == [("rename", "Relatorio-2")]


def test_restaurar_com_subpastas_nunca_perde_arquivos(tmp_path):
    """Regressão: downloads em paralelo para a mesma subpasta pulavam arquivos no Windows."""
    for i in range(40):
        drive = FakeDrive()
        src = tmp_path / f"src{i}" / "R"
        (src / "a" / "b").mkdir(parents=True)
        for rel in ("main.tex", "a/1.tex", "a/2.tex", "a/b/3.tex", "a/b/4.tex"):
            (src / rel).write_text(rel)
        ds.sync_project(drive, src, "R")
        dest = tmp_path / f"dest{i}" / "R"
        assert ds.restore_project(drive, folder_of(drive, "R"), dest, "R") == 5
        assert {p.relative_to(dest).as_posix() for p in dest.rglob("*.tex")} == {
            "main.tex",
            "a/1.tex",
            "a/2.tex",
            "a/b/3.tex",
            "a/b/4.tex",
        }


def test_nomes_perigosos_vindos_do_drive_sao_ignorados(drive, tmp_path):
    pf = drive.create_folder("P", drive.root_folder())
    drive.upload(b"ok", "main.tex", pf)
    drive.upload(b"mal", "..", pf)
    drive.upload(b"mal", "C:x.tex", pf)
    drive.upload(b"mal", "a\\b.tex", pf)
    dest = tmp_path / "proj" / "P"
    assert ds.restore_project(drive, pf, dest, "P") == 1
    assert {p.name for p in dest.iterdir()} == {"main.tex", ds.MANIFEST}
    assert not (tmp_path / "proj" / "..").is_file()


# ---------------------------------------------------------------- pastas e arquivos mexidos no Drive


def test_pasta_apagada_no_drive_e_recriada(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.trash_tree(folder_of(drive, "Relatorio"))
    drive.verified.clear()  # nova execução do servidor
    ds.sync_project(drive, project, "Relatorio")
    assert len(drive.tree(folder_of(drive, "Relatorio"))) == 4


def test_conferencia_sem_mudancas_so_verifica_uma_vez(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.verified.clear()
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.calls == [("exists",)]
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.calls == []


def test_arquivo_apagado_no_drive_e_reenviado(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.files[ds.load_manifest(project)["files"]["main.tex"]["id"]]["trashed"] = True
    touch_later(project / "main.tex", "nova versão\n")
    ds.sync_project(drive, project, "Relatorio")
    assert drive.tree(folder_of(drive, "Relatorio"))["main.tex"] == (project / "main.tex").read_bytes()


def test_pasta_apagada_durante_a_execucao_e_recriada_na_tentativa_seguinte(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    old = folder_of(drive, "Relatorio")
    drive.trash_tree(old)
    touch_later(project / "main.tex", "mudou\n")
    with pytest.raises(ds.DriveError):
        ds.sync_project(drive, project, "Relatorio")
    ds.sync_project(drive, project, "Relatorio")
    new = folder_of(drive, "Relatorio")
    assert new not in (None, old) and len(drive.tree(new)) == 4


def test_pasta_existente_com_mesmo_nome_nao_duplica(drive, tmp_path):
    """Projeto local com o nome de uma pasta que já está no Drive (ex.: outro computador)."""
    root = drive.root_folder()
    pf = drive.create_folder("Artigo", root)
    drive.upload(b"versao antiga", "main.tex", pf)
    drive.upload(b"PNG-igual", "fig.png", drive.create_folder("img", pf))
    drive.upload(b"so no drive", "notas.txt", pf)
    local = tmp_path / "Artigo"
    (local / "img").mkdir(parents=True)
    (local / "main.tex").write_bytes(b"versao nova")
    (local / "img" / "fig.png").write_bytes(b"PNG-igual")
    (local / "novo.tex").write_bytes(b"novo")
    drive.calls.clear()

    ds.sync_project(drive, local, "Artigo")

    assert sorted(drive.uploads()) == [("upload", "main.tex", True), ("upload", "novo.tex", False)]
    names = [f["name"] for f in drive.files.values() if not f["trashed"]]
    assert names.count("main.tex") == 1 and names.count("fig.png") == 1 and names.count("Artigo") == 1
    remote = drive.tree(pf)
    assert remote["notas.txt"] == b"so no drive"  # só existia no Drive: intacto
    assert remote["main.tex"] == b"versao nova"
    drive.calls.clear()
    ds.sync_project(drive, local, "Artigo")
    assert not [c for c in drive.calls if c[0] in ("upload", "trash")]


# ---------------------------------------------------------------- processo em segundo plano


def test_envia_no_maximo_a_cada_intervalo(drive, tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "SYNC_INTERVAL", 0.5)
    proj = tmp_path / "P"
    proj.mkdir()
    (proj / "main.tex").write_text("x")
    syncs = []
    real = ds.sync_project
    monkeypatch.setattr(ds, "sync_project", lambda c, d, n: (syncs.append(time.time()), real(c, d, n))[1])

    m = ds.SyncManager(drive, tmp_path, lambda name: True)
    t0 = time.time()
    while time.time() - t0 < 2.2:  # edição contínua, como alguém digitando
        (proj / "main.tex").write_text(f"edit {time.time()}")
        m.mark_dirty("P")
        time.sleep(0.05)
    time.sleep(1.2)  # a última alteração ainda precisa subir

    gaps = [b - a for a, b in zip(syncs, syncs[1:], strict=False)]
    assert syncs and all(g >= 0.45 for g in gaps), gaps
    assert len(syncs) <= 7  # ~2,2 s / 0,5 s, e não um envio por tecla
    st = m.get_status("P")
    assert st["state"] == "synced" and not st["pending"]
    assert drive.tree(drive.find_child(drive.root_folder(), "P", True))["main.tex"] == (proj / "main.tex").read_bytes()
