# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização com o Google Drive, contra um Drive falso em memória."""

import os
import threading
import time

import pytest
from fake_drive import FakeDrive

from texdesk import drive_sync as ds


@pytest.fixture()
def drive(tmp_path):
    return FakeDrive(tmp_path / "estado-drive")


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
    path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
    os.utime(path, (old + 5, old + 5))


# ---------------------------------------------------------------- envio


def test_envio_inicial_espelha_os_arquivos(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    remote = drive.tree(folder_of(drive, "Relatorio"))
    # miniatura e manifesto não vão para o Drive; .project.json (configurações) e a versão vão
    assert set(remote) == {
        "main.tex",
        "capitulos/introducao.tex",
        "capitulos/metodologia.tex",
        ".project.json",
        ds.VERSION_FILE,
    }


def test_sem_mudancas_so_le_o_arquivo_de_versao(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.calls.clear()
    assert ds.sync_project(drive, project, "Relatorio") == 0
    assert drive.calls == [("download", ds.VERSION_FILE)]


def test_edicao_envia_so_o_arquivo_alterado(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    touch_later(project / "main.tex", "% editado\n")
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    # atualização, não arquivo novo; a versão vai por último
    assert drive.uploads() == [("upload", "main.tex", True), ("upload", ds.VERSION_FILE, True)]
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
    assert set(drive.tree(folder_of(drive, "Relatorio"))) == {"main.tex", "intro.tex", ".project.json", ds.VERSION_FILE}
    assert ("trash", "capitulos") in drive.calls


def test_renomear_projeto_renomeia_a_pasta(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    novo = project.rename(project.parent / "Relatorio Final")
    drive.calls.clear()
    ds.sync_project(drive, novo, "Relatorio Final")
    assert drive.calls == [("rename", "Relatorio Final"), ("download", ds.VERSION_FILE)]


# ---------------------------------------------------------------- restauração


def test_restaurar_baixa_arquivos_identicos(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    pf = folder_of(drive, "Relatorio")
    dest = tmp_path / "outra-maquina" / "Relatorio"
    n = ds.restore_project(drive, pf, dest, "Relatorio")
    remote = drive.tree(pf)
    assert n == len(remote) - 1  # o arquivo de versão não conta
    assert all((dest / k).read_bytes() == v for k, v in remote.items())
    drive.calls.clear()
    ds.sync_project(drive, dest, "Relatorio")
    assert drive.calls == [("download", ds.VERSION_FILE)]  # depois de restaurar, nada a enviar nem baixar


def test_restaurar_com_outro_nome_renomeia_a_pasta(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    dest = tmp_path / "x" / "Relatorio-2"
    ds.restore_project(drive, folder_of(drive, "Relatorio"), dest, "Relatorio")
    drive.calls.clear()
    ds.sync_project(drive, dest, "Relatorio-2")
    assert drive.calls == [("rename", "Relatorio-2"), ("download", ds.VERSION_FILE)]


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


# ---------------------------------------------------------------- importação em segundo plano


def wait_imports(q, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if all(j["state"] == "error" for j in q.items()):
            return
        time.sleep(0.02)
    raise AssertionError("a importação não terminou")


def test_importa_em_segundo_plano_e_so_mostra_o_projeto_inteiro(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    pf = folder_of(drive, "Relatorio")
    projects = tmp_path / "projects"
    projects.mkdir()
    gate = threading.Event()
    download = drive.download

    def slow_download(fid):
        gate.wait(5)  # segura o download para ver o estado "importando"
        return download(fid)

    drive.download = slow_download
    done = []
    q = ds.ImportQueue(drive, projects, lambda name, fid: done.append((name, fid)))
    q.add("Relatorio", pf, "Relatorio")
    assert q.reserved() == {"Relatorio"}
    assert q.importing_ids() == {pf}
    time.sleep(0.2)
    (job,) = q.items()
    assert job["state"] == "importing" and job["total"] == 4 and job["done"] == 0
    assert not (projects / "Relatorio").exists()  # pela metade não aparece como projeto
    gate.set()
    wait_imports(q)
    assert q.items() == []
    assert done == [("Relatorio", pf)]
    assert (projects / "Relatorio" / "capitulos" / "introducao.tex").is_file()
    assert [d.name for d in projects.iterdir()] == ["Relatorio"]  # sem a pasta oculta temporária


def test_falha_na_importacao_fica_na_lista_e_pode_repetir(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    pf = folder_of(drive, "Relatorio")
    projects = tmp_path / "projects"
    projects.mkdir()
    download = drive.download

    def offline(fid):
        raise ds.DriveError("sem conexão")

    drive.download = offline
    done = []
    q = ds.ImportQueue(drive, projects, lambda name, fid: done.append(name))
    q.add("Relatorio", pf, "Relatorio")
    wait_imports(q)
    (job,) = q.items()
    assert job["state"] == "error" and "sem conexão" in job["error"]
    assert list(projects.iterdir()) == []
    drive.download = download
    assert q.retry("Relatorio")
    wait_imports(q)
    assert done == ["Relatorio"] and q.items() == []
    drive.download = offline
    q.add("Outro", pf, "Relatorio")
    wait_imports(q)
    assert q.dismiss("Outro") and q.items() == []
    assert not q.dismiss("Outro")


def test_projeto_criado_com_o_mesmo_nome_durante_a_importacao(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    projects = tmp_path / "projects"
    projects.mkdir()
    gate = threading.Event()
    download = drive.download
    drive.download = lambda fid: (gate.wait(5), download(fid))[1]
    done = []
    q = ds.ImportQueue(drive, projects, lambda name, fid: done.append(name))
    q.add("Relatorio", folder_of(drive, "Relatorio"), "Relatorio")
    time.sleep(0.1)
    (projects / "Relatorio").mkdir()  # o usuário criou um projeto com esse nome enquanto isso
    gate.set()
    wait_imports(q)
    assert done == ["Relatorio-2"]
    assert (projects / "Relatorio-2" / "main.tex").is_file()


def test_importacao_interrompida_e_limpa_ao_abrir(drive, tmp_path):
    projects = tmp_path / "projects"
    (projects / (ds.IMPORT_PREFIX + "Meio")).mkdir(parents=True)
    ds.ImportQueue(drive, projects, lambda *a: None)
    assert list(projects.iterdir()) == []


# ---------------------------------------------------------------- pastas e arquivos mexidos no Drive


def test_pasta_apagada_no_drive_e_recriada(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.trash_tree(folder_of(drive, "Relatorio"))
    drive.verified.clear()  # nova execução do servidor
    ds.sync_project(drive, project, "Relatorio")
    assert len(drive.tree(folder_of(drive, "Relatorio"))) == 5


def test_conferencia_sem_mudancas_so_verifica_uma_vez(drive, project):
    ds.sync_project(drive, project, "Relatorio")
    drive.verified.clear()
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.calls == [("exists",), ("download", ds.VERSION_FILE)]
    drive.calls.clear()
    ds.sync_project(drive, project, "Relatorio")
    assert drive.calls == [("download", ds.VERSION_FILE)]


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
    assert new not in (None, old) and len(drive.tree(new)) == 5


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

    # main.tex: diferente nos dois lados e sem versão comum, fica o modificado por último (o local)
    assert sorted(drive.uploads()) == [
        ("upload", ds.VERSION_FILE, False),
        ("upload", "main.tex", True),
        ("upload", "novo.tex", False),
    ]
    names = [f["name"] for f in drive.files.values() if not f["trashed"]]
    assert names.count("main.tex") == 1 and names.count("fig.png") == 1 and names.count("Artigo") == 1
    remote = drive.tree(pf)
    assert remote["notas.txt"] == b"so no drive"
    assert (local / "notas.txt").read_bytes() == b"so no drive"  # só existia no Drive: foi baixado
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
    monkeypatch.setattr(ds, "sync_project", lambda *a, **k: (syncs.append(time.time()), real(*a, **k))[1])

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


# ---------------------------------------------------------------- dois computadores no mesmo Drive


def dois_computadores(drive, project, tmp_path):
    """O projeto sincronizado neste computador (A) e importado em outro (B)."""
    ds.sync_project(drive, project, "Relatorio")
    outro = drive.outro_computador(tmp_path / "estado-B")
    b = tmp_path / "B" / "Relatorio"
    ds.restore_project(outro, folder_of(drive, "Relatorio"), b, "Relatorio")
    return outro, b


def test_alteracao_feita_em_outro_computador_chega(drive, project, tmp_path):
    """O problema original: B abria o projeto e continuava com a versão antiga."""
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "main.tex", "versão nova\n")
    ds.sync_project(drive, project, "Relatorio")
    drive.calls.clear()
    report = {}
    ds.sync_project(outro, b, "Relatorio", report=report)
    assert (b / "main.tex").read_text() == "versão nova\n"
    assert report["received"] == ["main.tex"]
    assert drive.uploads() == []  # nada volta para o Drive
    assert ds.read_version(b) == ds.read_version(project)
    drive.calls.clear()
    ds.sync_project(outro, b, "Relatorio")
    assert drive.calls == [("download", ds.VERSION_FILE)]  # daí em diante, só a conferência


def test_versao_antiga_nunca_sobrescreve_a_nova_do_drive(drive, project, tmp_path):
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "main.tex", "versão nova\n")
    ds.sync_project(drive, project, "Relatorio")
    # B edita outro arquivo sem ter recebido a mudança de A
    touch_later(b / "capitulos" / "introducao.tex", "\\chapter{Introdução editada em B}\n")
    ds.sync_project(outro, b, "Relatorio")
    remote = drive.tree(folder_of(drive, "Relatorio"))
    assert remote["main.tex"] == (project / "main.tex").read_bytes()
    assert (b / "main.tex").read_bytes() == remote["main.tex"]
    assert remote["capitulos/introducao.tex"] == (b / "capitulos" / "introducao.tex").read_bytes()
    ds.sync_project(drive, project, "Relatorio")
    assert (project / "capitulos" / "introducao.tex").read_bytes() == remote["capitulos/introducao.tex"]


def test_versao_sobe_a_cada_envio(drive, project, tmp_path):
    ds.sync_project(drive, project, "Relatorio")
    v1 = ds.read_version(project)
    touch_later(project / "main.tex", "mudou\n")
    ds.sync_project(drive, project, "Relatorio")
    v2 = ds.read_version(project)
    assert v2["version"] == v1["version"] + 1 and v2["rev"] != v1["rev"]
    assert drive.tree(folder_of(drive, "Relatorio"))[ds.VERSION_FILE] == (project / ds.VERSION_FILE).read_bytes()


def test_mesmo_arquivo_alterado_nos_dois_e_juntado(drive, project, tmp_path):
    (project / "texto.tex").write_bytes(b"O gato subiu no telhado. O cachorro latiu.\n\nFim.\n")
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "texto.tex", "O gato pulou no telhado. O cachorro latiu.\n\nFim.\n")
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "texto.tex", "O gato subiu no telhado. O cachorro dormiu.\n\nFim.\n")
    report = {}
    ds.sync_project(outro, b, "Relatorio", report=report)
    juntado = "O gato pulou no telhado. O cachorro dormiu.\n\nFim.\n"
    assert (b / "texto.tex").read_text() == juntado
    assert report["conflicts"] == [] and report["received"] == ["texto.tex"]
    assert drive.tree(folder_of(drive, "Relatorio"))["texto.tex"] == (b / "texto.tex").read_bytes()
    ds.sync_project(drive, project, "Relatorio")
    assert (project / "texto.tex").read_text() == juntado


def test_mesmo_trecho_alterado_nos_dois_vira_conflito(drive, project, tmp_path):
    (project / "texto.tex").write_bytes(b"O gato subiu no telhado.\n")
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "texto.tex", b"O gato pulou no telhado.\n")
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "texto.tex", b"O gato correu no telhado.\n")
    report = {}
    ds.sync_project(outro, b, "Relatorio", report=report)
    # fica a versão deste computador, e o conflito vai para o usuário escolher
    assert (b / "texto.tex").read_bytes() == b"O gato correu no telhado.\n"
    assert report["conflicts"] == [
        {"path": "texto.tex", "line": 0, "mine": "O gato correu no telhado.\n", "theirs": "O gato pulou no telhado.\n"}
    ]
    assert drive.tree(folder_of(drive, "Relatorio"))["texto.tex"] == b"O gato correu no telhado.\n"


def test_arquivo_apagado_em_outro_computador_e_apagado_aqui(drive, project, tmp_path):
    outro, b = dois_computadores(drive, project, tmp_path)
    (project / "capitulos" / "metodologia.tex").unlink()
    ds.sync_project(drive, project, "Relatorio")
    report = {}
    ds.sync_project(outro, b, "Relatorio", report=report)
    assert not (b / "capitulos" / "metodologia.tex").exists()
    assert report["received"] == ["capitulos/metodologia.tex"]


def test_arquivo_apagado_la_mas_editado_aqui_continua(drive, project, tmp_path):
    outro, b = dois_computadores(drive, project, tmp_path)
    (project / "capitulos" / "metodologia.tex").unlink()
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "capitulos" / "metodologia.tex", "\\chapter{Metodologia revisada}\n")
    ds.sync_project(outro, b, "Relatorio")
    assert (b / "capitulos" / "metodologia.tex").read_text() == "\\chapter{Metodologia revisada}\n"
    remote = drive.tree(folder_of(drive, "Relatorio"))
    assert remote["capitulos/metodologia.tex"] == (b / "capitulos" / "metodologia.tex").read_bytes()
    ds.sync_project(drive, project, "Relatorio")
    assert (project / "capitulos" / "metodologia.tex").is_file()  # volta para A também


def test_arquivo_novo_em_subpasta_nova_chega(drive, project, tmp_path):
    outro, b = dois_computadores(drive, project, tmp_path)
    (project / "figuras").mkdir()
    (project / "figuras" / "grafico.png").write_bytes(b"PNG")
    ds.sync_project(drive, project, "Relatorio")
    drive.calls.clear()
    ds.sync_project(outro, b, "Relatorio")
    assert (b / "figuras" / "grafico.png").read_bytes() == b"PNG"
    assert not [c for c in drive.calls if c[0] in ("mkdir", "upload", "trash")]


def test_binario_alterado_nos_dois_fica_o_modificado_por_ultimo(drive, project, tmp_path):
    (project / "fig.png").write_bytes(b"PNG-base")
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "fig.png", b"PNG-de-A")
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "fig.png", b"PNG-de-B")
    fid = ds.load_manifest(project)["files"]["fig.png"]["id"]
    drive.files[fid]["modified"] = (b / "fig.png").stat().st_mtime + 60  # a de A é mais nova
    ds.sync_project(outro, b, "Relatorio")
    assert (b / "fig.png").read_bytes() == b"PNG-de-A"

    touch_later(b / "fig.png", b"PNG-de-B-2")
    ds.sync_project(outro, b, "Relatorio")
    touch_later(project / "fig.png", b"PNG-de-A-2")
    os.utime(project / "fig.png", (1, 1))  # a de A é mais antiga
    ds.sync_project(drive, project, "Relatorio")
    assert (project / "fig.png").read_bytes() == b"PNG-de-B-2"
    assert drive.tree(folder_of(drive, "Relatorio"))["fig.png"] == b"PNG-de-B-2"


def sem_versao(drive, d):
    """Deixa o projeto como uma versão anterior do TexDesk deixava: sem arquivo de versão."""
    m = ds.load_manifest(d)
    if m.get("versionId") in drive.files:
        drive.files[m["versionId"]]["trashed"] = True
    m.pop("versionId", None)
    m.pop("rev", None)
    ds.save_manifest(d, m)
    (d / ds.VERSION_FILE).unlink(missing_ok=True)


def test_projeto_de_versao_anterior_ganha_arquivo_de_versao(drive, project, tmp_path):
    outro, b = dois_computadores(drive, project, tmp_path)
    sem_versao(drive, project)
    sem_versao(outro, b)
    # A, ainda na versão anterior do TexDesk, enviou uma mudança
    drive.put(folder_of(drive, "Relatorio"), "main.tex", b"mudado em A\n")
    # B, na versão nova: conferência completa, recebe a mudança e cria o arquivo de versão
    report = {}
    ds.sync_project(outro, b, "Relatorio", report=report)
    assert (b / "main.tex").read_bytes() == b"mudado em A\n"
    assert report["received"] == ["main.tex"]
    v = ds.read_version(b)
    assert v and ds.load_manifest(b)["rev"] == v["rev"]
    assert drive.tree(folder_of(drive, "Relatorio"))[ds.VERSION_FILE] == (b / ds.VERSION_FILE).read_bytes()
    # A atualiza o TexDesk: passa a usar o mesmo arquivo de versão
    ds.sync_project(drive, project, "Relatorio")
    assert ds.read_version(project) == v and (project / "main.tex").read_bytes() == b"mudado em A\n"


def test_arquivo_alterado_durante_a_conferencia_fica_para_a_proxima(drive, project, tmp_path):
    (project / "texto.tex").write_bytes(b"linha 1\nlinha 2\nlinha 3\n")
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "texto.tex", b"linha 1 de A\nlinha 2\nlinha 3\n")
    ds.sync_project(drive, project, "Relatorio")

    def digitando(d, important):  # o usuário salva bem na hora em que o Drive responde
        touch_later(b / "texto.tex", b"linha 1\nlinha 2\nlinha 3 de B\n")

    ds.sync_project(outro, b, "Relatorio", before_change=digitando)
    assert (b / "texto.tex").read_bytes() == b"linha 1\nlinha 2\nlinha 3 de B\n"  # não foi sobrescrito
    assert drive.tree(folder_of(drive, "Relatorio"))["texto.tex"] == b"linha 1 de A\nlinha 2\nlinha 3\n"
    ds.sync_project(outro, b, "Relatorio")  # a próxima junta as duas
    assert (b / "texto.tex").read_bytes() == b"linha 1 de A\nlinha 2\nlinha 3 de B\n"


def test_historico_antes_de_receber(drive, project, tmp_path):
    (project / "texto.tex").write_bytes(b"a\nb\n")
    outro, b = dois_computadores(drive, project, tmp_path)
    chamadas = []
    touch_later(project / "texto.tex", b"A\nb\n")
    ds.sync_project(drive, project, "Relatorio")
    ds.sync_project(outro, b, "Relatorio", before_change=lambda d, imp: chamadas.append(imp))
    assert chamadas == [False]  # só baixou: versão automática
    touch_later(project / "texto.tex", b"A\nb de A\n")
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "texto.tex", b"A de B\nb\n")
    ds.sync_project(outro, b, "Relatorio", before_change=lambda d, imp: chamadas.append(imp))
    assert chamadas == [False, True]  # juntou: versão com nome


def test_outro_computador_publica_no_meio_do_envio(drive, project, tmp_path):
    """Se A publica uma versão enquanto B envia, B traz a mudança de A antes de publicar."""
    outro, b = dois_computadores(drive, project, tmp_path)
    upload = outro.upload
    feito = []

    def upload_com_a_no_meio(data, name, parent, file_id=None):
        r = upload(data, name, parent, file_id)
        if not feito:
            feito.append(1)
            touch_later(project / "main.tex", "de A\n")
            ds.sync_project(drive, project, "Relatorio")
        return r

    outro.upload = upload_com_a_no_meio
    touch_later(b / "capitulos" / "introducao.tex", "de B\n")
    ds.sync_project(outro, b, "Relatorio")
    assert (b / "main.tex").read_text() == "de A\n"
    remote = drive.tree(folder_of(drive, "Relatorio"))
    assert remote["capitulos/introducao.tex"] == (b / "capitulos" / "introducao.tex").read_bytes()
    assert ds.read_version(b)["rev"] == ds.load_manifest(b)["rev"]
    assert remote[ds.VERSION_FILE] == (b / ds.VERSION_FILE).read_bytes()


def test_gerenciador_informa_o_que_chegou_e_os_conflitos(drive, project, tmp_path):
    (project / "texto.tex").write_bytes(b"O gato subiu.\n")
    outro, b = dois_computadores(drive, project, tmp_path)
    touch_later(project / "texto.tex", b"O gato pulou.\n")
    touch_later(project / "main.tex", "novo main\n")
    ds.sync_project(drive, project, "Relatorio")
    touch_later(b / "texto.tex", b"O gato correu.\n")
    antes = []
    m = ds.SyncManager(outro, b.parent, lambda n: True, before_change=lambda d, n, imp: antes.append((n, imp)))
    t0 = time.time()
    m.mark_dirty("Relatorio", check_only=True)
    end = time.time() + 5
    while time.time() < end and (m.get_status("Relatorio").get("checkedAt") or 0) < t0:
        time.sleep(0.02)
    m.stop()
    st = m.get_status("Relatorio")
    assert st["state"] == "synced"
    assert st["received"]["files"] == ["main.tex"]
    (c,) = st["conflicts"]
    assert c["path"] == "texto.tex" and c["theirs"] == "O gato pulou.\n" and c["id"]
    assert antes == [("Relatorio", True)]
    assert m.pop_conflict("Relatorio", c["id"]) == c
    assert m.get_status("Relatorio")["conflicts"] == []
