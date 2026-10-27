# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Erros inesperados viram JSON para a interface e ficam registrados no log."""

import logging

import pytest
from conftest import APP

from texdesk import config, logs
from texdesk.security import CSRF_HEADER

BASE = f"http://127.0.0.1:{config.PORT}"


@pytest.fixture()
def client(monkeypatch):
    logs.setup(console=False)
    monkeypatch.setitem(APP.config, "PROPAGATE_EXCEPTIONS", False)  # como em produção
    return APP.test_client()


def test_erro_interno_vira_json_e_vai_para_o_log(client, monkeypatch):
    def quebra():
        raise ValueError("falha de teste 12345")

    monkeypatch.setitem(APP.view_functions, "projects.list_templates", quebra)
    r = client.get("/api/templates", base_url=BASE)
    assert r.status_code == 500
    assert "Erro interno do TexDesk" in r.get_json()["error"]
    for h in logging.getLogger("texdesk").handlers:
        h.flush()
    log = config.LOG_FILE.read_text(encoding="utf-8")
    assert "falha de teste 12345" in log and "Traceback" in log  # com o rastro completo


def test_metodo_nao_permitido_vira_json(client):
    r = client.delete("/api/templates", base_url=BASE, headers={CSRF_HEADER: "1"})
    assert r.status_code == 405 and "error" in r.get_json()


def test_compilacao_fica_registrada(client):
    if not config.TECTONIC.exists():
        pytest.skip("Tectonic não instalado")
    h = {CSRF_HEADER: "1"}
    client.delete("/api/projects/Log Teste", base_url=BASE, headers=h)
    client.post("/api/projects", base_url=BASE, headers=h, json={"name": "Log Teste", "template": "blank"})
    client.post("/api/projects/Log Teste/compile", base_url=BASE, headers=h, json={})
    client.delete("/api/projects/Log Teste", base_url=BASE, headers=h)
    for hd in logging.getLogger("texdesk").handlers:
        hd.flush()
    assert "Compilação de Log Teste: success" in config.LOG_FILE.read_text(encoding="utf-8")
