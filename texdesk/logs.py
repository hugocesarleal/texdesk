# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Registro (log) do TexDesk em logs/texdesk.log, com rotação.

Todos os módulos usam loggers com nome "texdesk.*" (logging.getLogger(__name__)), e o do
Flask ("texdesk.app") também, então tudo cai no mesmo arquivo. Erros vêm com o rastro
completo, para quem for investigar um problema (ou abrir uma issue).
"""

import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_FILE

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def setup(console=True):
    """Liga o log no arquivo (até 1 MB, guardando os 3 anteriores) e, opcionalmente, na tela."""
    global _configured
    if _configured:
        return
    _configured = True
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("texdesk")
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(file_handler)
    if console:  # na janela do TexDesk, só avisos e erros (o resto fica no arquivo)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter("  %(levelname)s: %(message)s"))
        root.addHandler(console_handler)
