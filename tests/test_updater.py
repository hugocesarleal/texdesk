# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Atualização pelo painel, com pacotes falsos numa pasta temporária (sem internet)."""

import hashlib
import io
import tarfile
import zipfile

import pytest

from texdesk import updater


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("win32", "AMD64", "windows-x64"),
        ("win32", "ARM64", None),
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("darwin", "arm64", "macos-arm64"),
        ("darwin", "x86_64", "macos-x64"),
        ("freebsd13", "amd64", None),
        ("linux", "riscv64", None),
    ],
)
def test_pacote_de_cada_sistema(system, machine, expected):
    assert updater.platform_target(system, machine) == expected


def test_tipo_de_instalacao(tmp_path):
    assert updater.install_kind(tmp_path) is None  # sem VERSION nem .git: só o link
    (tmp_path / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    assert updater.install_kind(tmp_path) == "package"
    (tmp_path / ".git").mkdir()
    assert updater.install_kind(tmp_path) in ("git", None)  # None se o git não estiver instalado


def _files(version):
    return {
        "VERSION": f"{version}\n",
        "iniciar.bat": "@echo off\r\n",
        "requirements.txt": "flask==3.0.0\n",
        "texdesk/__init__.py": f'__version__ = "{version}"\n',
        "static/app.js": f"// {version}\n",
        "tools/tectonic.exe": f"tectonic {version}",
        "tools/dict/pt_BR.dic": "palavras",
    }


def make_package(path, version, kind="tar", files=None):
    files = files or _files(version)
    top = f"texdesk-{version}/"
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as z:
            for name, content in files.items():
                z.writestr(name if name.startswith(("/", "..")) else top + name, content)
    else:
        with tarfile.open(path, "w:gz") as t:
            for name, content in files.items():
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name if name.startswith(("/", "..")) else top + name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return path


@pytest.fixture
def install(tmp_path):
    """Uma instalação 0.1.0 com dados do usuário e um dicionário baixado depois."""
    root = tmp_path / "TexDesk"
    for name, content in _files("0.1.0").items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (root / "static" / "antigo.js").write_text("removido na versão nova", encoding="utf-8")
    (root / "projects" / "TCC").mkdir(parents=True)
    (root / "projects" / "TCC" / "main.tex").write_text("meu texto", encoding="utf-8")
    (root / "output" / "TCC").mkdir(parents=True)
    (root / ".drive").mkdir()
    (root / ".drive" / "token.json").write_text("segredo", encoding="utf-8")
    (root / "tools" / "dict" / "de_DE.dic").write_text("baixado depois", encoding="utf-8")
    (root / "tools" / ".setup-ok").write_text("", encoding="utf-8")
    (root / updater.WORK_DIR).mkdir()
    return root


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_instala_o_pacote_e_preserva_os_dados(install, kind):
    pkg = make_package(install / updater.WORK_DIR / ("p.zip" if kind == "zip" else "p.tar.gz"), "0.2.0", kind)
    updater.install_package(install, pkg, "0.2.0")
    read = lambda p: (install / p).read_text(encoding="utf-8")  # noqa: E731
    assert read("VERSION").strip() == "0.2.0"
    assert '"0.2.0"' in read("texdesk/__init__.py")
    assert read("static/app.js") == "// 0.2.0\n"
    assert not (install / "static" / "antigo.js").exists()  # a pasta de código é trocada inteira
    assert read("tools/tectonic.exe") == "tectonic 0.2.0"
    # o que é do usuário fica como estava
    assert read("projects/TCC/main.tex") == "meu texto"
    assert read(".drive/token.json") == "segredo"
    assert read("tools/dict/de_DE.dic") == "baixado depois"
    assert (install / "tools" / ".setup-ok").exists()
    updater.cleanup(install)
    assert not (install / updater.WORK_DIR).exists()


def test_pacote_de_outra_versao_nao_e_instalado(install):
    pkg = make_package(install / updater.WORK_DIR / "p.tar.gz", "0.3.0")
    with pytest.raises(updater.UpdateError, match="esperava a versão 0.2.0"):
        updater.install_package(install, pkg, "0.2.0")
    assert '"0.1.0"' in (install / "texdesk" / "__init__.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["../fora.txt", "/etc/passwd"])
def test_recusa_caminhos_para_fora_da_pasta(install, bad):
    files = _files("0.2.0") | {bad: "x"}
    pkg = make_package(install / updater.WORK_DIR / "p.tar.gz", "0.2.0", files=files)
    with pytest.raises(updater.UpdateError, match="caminho inseguro"):
        updater.install_package(install, pkg, "0.2.0")
    assert not (install.parent / "fora.txt").exists()


def test_falha_no_meio_volta_a_versao_anterior(install, monkeypatch):
    pkg = make_package(install / updater.WORK_DIR / "p.tar.gz", "0.2.0")
    real_copy = updater.shutil.copy2

    def copy_that_fails(src, dst, *a, **kw):
        if str(dst).endswith("requirements.txt"):
            raise OSError("disco cheio")
        return real_copy(src, dst, *a, **kw)

    monkeypatch.setattr(updater.shutil, "copy2", copy_that_fails)
    (install / "requirements.txt").write_text("flask==2.0.0\n", encoding="utf-8")  # muda: será copiado
    with pytest.raises(OSError):
        updater.install_package(install, pkg, "0.2.0")
    assert '"0.1.0"' in (install / "texdesk" / "__init__.py").read_text(encoding="utf-8")
    assert (install / "static" / "antigo.js").exists()
    assert (install / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"


def test_confere_tamanho_e_sha256(tmp_path):
    f = tmp_path / "pacote.zip"
    f.write_bytes(b"conteudo do pacote")
    digest = "sha256:" + hashlib.sha256(b"conteudo do pacote").hexdigest()
    updater.verify(f, f.stat().st_size, digest)
    with pytest.raises(updater.UpdateError, match="incompleto"):
        updater.verify(f, 999, digest)
    with pytest.raises(updater.UpdateError, match="não confere"):
        updater.verify(f, None, "sha256:" + "0" * 64)


def test_atualizacao_desligada_nao_comeca(monkeypatch):
    monkeypatch.setenv("TEXDESK_UPDATE_CHECK", "0")
    with pytest.raises(updater.UpdateError, match="desligada"):
        updater.start()
