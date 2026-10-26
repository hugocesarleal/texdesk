# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Proteções do servidor local contra sites maliciosos (CSRF e DNS rebinding).

Cada teste reproduz um ataque que um site aberto no navegador conseguiria fazer.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# pasta de dados temporária: os testes nunca tocam nos projetos nem no Drive reais
os.environ["TEXDESK_DATA"] = tempfile.mkdtemp(prefix="texdesk-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

HOST = f"127.0.0.1:{server.PORT}"
OK = {server.CSRF_HEADER: "1"}


@pytest.fixture()
def client():
    server.app.config["TESTING"] = True
    c = server.app.test_client()
    r = c.post("/api/projects", headers=OK, json={"name": "Alvo", "template": "blank"}, base_url=f"http://{HOST}")
    assert r.status_code in (200, 409)
    yield c


def post(client, path, **kw):
    return client.post(path, base_url=f"http://{kw.pop('host', HOST)}", **kw)


def settings(client):
    return client.get("/api/projects/Alvo/settings", base_url=f"http://{HOST}").get_json()


# ---------------------------------------------------------------- uso legítimo

def test_interface_do_texdesk_funciona(client):
    r = post(client, "/api/projects/Alvo/settings", headers=OK, json={"autoCompile": True})
    assert r.status_code == 200 and settings(client)["autoCompile"] is True
    post(client, "/api/projects/Alvo/settings", headers=OK, json={"autoCompile": False})


def test_localhost_tambem_e_aceito(client):
    r = client.get("/api/projects", base_url=f"http://localhost:{server.PORT}")
    assert r.status_code == 200


# ---------------------------------------------------------------- ataques

def test_post_text_plain_de_outro_site_e_recusado(client):
    """Requisição 'simples' (sem preflight), como um fetch() no-cors de outro site."""
    r = post(client, "/api/projects/Alvo/settings", data=json.dumps({"shellEscape": True}),
             headers={"Content-Type": "text/plain", "Origin": "https://malicioso.example",
                      "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert settings(client)["shellEscape"] is False


def test_post_sem_o_cabecalho_do_texdesk_e_recusado(client):
    """Mesmo sem Origin/Sec-Fetch-Site (navegadores antigos), falta o cabeçalho próprio."""
    r = post(client, "/api/projects/Alvo/settings", json={"shellEscape": True})
    assert r.status_code == 403
    assert settings(client)["shellEscape"] is False


def test_upload_por_formulario_de_outro_site_e_recusado(client):
    """Um <form enctype=multipart/form-data> comum não precisa de preflight."""
    r = post(client, "/api/projects/Alvo/upload",
             data={"files": (io.BytesIO(b"\\immediate\\write18{calc}"), "ataque.tex")},
             headers={"Origin": "https://malicioso.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert not (server.PROJECTS / "Alvo" / "ataque.tex").exists()


def test_origem_de_outro_site_e_recusada_mesmo_com_cabecalho(client):
    r = post(client, "/api/projects/Alvo/settings", json={"shellEscape": True},
             headers={**OK, "Origin": "https://malicioso.example"})
    assert r.status_code == 403


def test_dns_rebinding_e_recusado(client):
    """Domínio do atacante que resolve para 127.0.0.1: chega com outro Host."""
    r = client.get("/api/drive/status", base_url=f"http://malicioso.example:{server.PORT}")
    assert r.status_code == 403
    r = post(client, "/api/projects/Alvo/settings", host=f"malicioso.example:{server.PORT}",
             headers=OK, json={"shellEscape": True})
    assert r.status_code == 403


def test_json_com_content_type_errado_e_recusado(client):
    r = post(client, "/api/projects/Alvo/settings", headers={**OK, "Content-Type": "text/plain"},
             data=json.dumps({"autoCompile": True}))
    assert r.status_code == 415


def test_nao_pode_ser_embutido_em_sites_de_terceiros(client):
    r = client.get("/", base_url=f"http://{HOST}")
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_upload_grande_demais_e_recusado(client, monkeypatch):
    monkeypatch.setitem(server.app.config, "MAX_CONTENT_LENGTH", 1024)
    r = post(client, "/api/projects/Alvo/upload", headers=OK,
             data={"files": (io.BytesIO(b"x" * 4096), "grande.bin")})
    assert r.status_code == 413
