# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Token do Google Drive no cofre de senhas do sistema, com um cofre falso em memória."""

import json
import os

import pytest

from texdesk.drive_sync import DriveClient
from texdesk.token_store import SERVICE, TokenStore

TOKEN = {"access_token": "ya29.teste", "refresh_token": "1//refresh-teste", "expires_at": 0}


class FakeKeyring:
    """Mesma interface do keyring (get/set/delete_password), guardando em memória."""

    def __init__(self, fail_on_set=False, corrupt=False):
        self.data = {}
        self.fail_on_set = fail_on_set
        self.corrupt = corrupt  # devolve algo diferente do que foi gravado

    def set_password(self, service, account, value):
        if self.fail_on_set:
            raise RuntimeError("cofre travado")
        self.data[(service, account)] = value

    def get_password(self, service, account):
        v = self.data.get((service, account))
        return "outra coisa" if (v and self.corrupt) else v

    def delete_password(self, service, account):
        self.data.pop((service, account))


def test_token_vai_para_o_cofre_e_nao_para_o_arquivo(tmp_path):
    kr = FakeKeyring()
    store = TokenStore(tmp_path, kr)
    store.save(TOKEN)
    assert store.location == "keyring"
    assert not (tmp_path / "token.json").exists()
    assert json.loads(kr.data[(SERVICE, store.account)]) == TOKEN
    assert TokenStore(tmp_path, kr).load() == TOKEN  # outra execução do servidor lê do cofre


def test_token_antigo_em_arquivo_e_migrado_para_o_cofre(tmp_path):
    (tmp_path / "token.json").write_text(json.dumps(TOKEN))
    kr = FakeKeyring()
    store = TokenStore(tmp_path, kr)
    assert not (tmp_path / "token.json").exists()
    assert store.load() == TOKEN


def test_migracao_que_nao_confere_mantem_o_arquivo(tmp_path):
    """Se o cofre não devolver exatamente o que foi gravado, o arquivo não é apagado."""
    (tmp_path / "token.json").write_text(json.dumps(TOKEN))
    TokenStore(tmp_path, FakeKeyring(corrupt=True))
    assert (tmp_path / "token.json").exists()


def test_sem_cofre_usa_arquivo_protegido(tmp_path):
    store = TokenStore(tmp_path, None)
    store.save(TOKEN)
    assert store.location == "file"
    assert json.loads((tmp_path / "token.json").read_text()) == TOKEN
    if os.name != "nt":
        assert (tmp_path / "token.json").stat().st_mode & 0o777 == 0o600


def test_cofre_com_erro_cai_para_o_arquivo(tmp_path):
    store = TokenStore(tmp_path, FakeKeyring(fail_on_set=True))
    store.save(TOKEN)
    assert store.location == "file"
    assert TokenStore(tmp_path, None).load() == TOKEN


def test_desconectar_apaga_do_cofre_e_do_arquivo(tmp_path):
    kr = FakeKeyring()
    store = TokenStore(tmp_path, kr)
    store.save(TOKEN)
    (tmp_path / "token.json").write_text("{}")
    store.delete()
    assert kr.data == {} and not (tmp_path / "token.json").exists()
    assert store.load() is None


def test_cada_pasta_de_dados_tem_a_sua_entrada(tmp_path):
    kr = FakeKeyring()
    a, b = TokenStore(tmp_path / "a", kr), TokenStore(tmp_path / "b", kr)
    a.save(TOKEN)
    assert b.load() is None


def test_drive_client_usa_o_cofre(tmp_path):
    kr = FakeKeyring()
    client = DriveClient(tmp_path / ".drive", token_backend=kr)
    assert not client.connected
    client._save_token(TOKEN)
    assert client.connected
    assert not (tmp_path / ".drive" / "token.json").exists()


@pytest.mark.parametrize("valor", ["0"])
def test_variavel_desliga_o_cofre(tmp_path, monkeypatch, valor):
    monkeypatch.setenv("TEXDESK_KEYRING", valor)
    assert TokenStore(tmp_path).location == "file"
