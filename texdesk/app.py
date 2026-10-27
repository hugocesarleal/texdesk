# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Monta a aplicação Flask: segurança, rotas, erros e serviços."""
from flask import Flask, jsonify

from . import drive_sync, security, services
from .config import MAX_UPLOAD_MB, OUTPUT, PROJECTS, STATIC
from .routes import BLUEPRINTS


def create_app():
    PROJECTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    security.init_app(app)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
    _register_errors(app)
    services.init()
    return app


def _register_errors(app):
    """Erros sempre em JSON (a interface mostra a mensagem), nunca a página HTML do Flask."""
    def json_error(e):
        return jsonify({"error": e.description}), e.code

    for code in (400, 403, 404, 405, 409, 415):
        app.register_error_handler(code, json_error)

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": f"Arquivo grande demais (limite de {MAX_UPLOAD_MB} MB por envio)"}), 413

    @app.errorhandler(drive_sync.DriveError)
    def drive_error(e):
        return jsonify({"error": str(e)}), 502
