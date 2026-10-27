# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Proteções do servidor local contra sites maliciosos.

O servidor só escuta em 127.0.0.1, mas qualquer site aberto no navegador consegue mandar
requisições para ele. Sem estas barreiras, um site poderia ligar o shell-escape, enviar
um .tex com \\write18 e compilar, executando comandos no computador.
"""

from flask import abort, request

from .config import PORT

ALLOWED_HOSTS = {f"{h}:{PORT}" for h in ("127.0.0.1", "localhost", "[::1]")}
CSRF_HEADER = "X-TexDesk"  # enviado pelo front-end em toda requisição que altera algo


def check_request():
    # DNS rebinding: um domínio do atacante que resolve para 127.0.0.1 chega com outro Host
    if request.host.lower() not in ALLOWED_HOSTS:
        abort(403, "Host não permitido")
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None  # leituras: a política de mesma origem do navegador já impede outro site de ler
    # CSRF: requisições vindas de outro site (o navegador informa nesses cabeçalhos)
    if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
        abort(403, "Requisição de outro site recusada")
    origin = request.headers.get("Origin")
    if origin and origin.lower().split("://", 1)[-1] not in ALLOWED_HOSTS:
        abort(403, "Origem não permitida")
    # um cabeçalho próprio não pode ser enviado por outro site sem permissão (preflight de
    # CORS), e este servidor nunca concede essa permissão
    if request.headers.get(CSRF_HEADER) != "1":
        abort(403, "Requisição sem o cabeçalho do TexDesk")
    return None


def add_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # não pode ser embutido em sites de terceiros
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def json_body():
    """Corpo JSON da requisição; recusa outros tipos de conteúdo (ex.: text/plain)."""
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        abort(415, "Envie um JSON (Content-Type: application/json)")
    return data


def init_app(app):
    app.before_request(check_request)
    app.after_request(add_headers)
