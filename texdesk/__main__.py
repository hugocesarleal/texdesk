# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Inicia o TexDesk: python -m texdesk [--abrir]

--abrir  abre o navegador quando o servidor estiver pronto (usado pelo iniciar.bat/.sh).
Sai com o código 3 se já houver um TexDesk rodando (aí só abre o navegador).
"""

import sys
import threading
import urllib.request
import webbrowser

from . import __version__
from .config import PORT, URL


def already_running():
    """No Windows, dois servidores conseguem abrir a mesma porta, e isso duplicaria a
    sincronização com o Drive. Então, antes de qualquer coisa, pergunta se já há um."""
    try:
        with urllib.request.urlopen(f"{URL}/api/drive/status", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def main():
    open_browser = "--abrir" in sys.argv
    if already_running():
        print(f"\n  O TexDesk já está rodando em {URL} (em segundo plano).")
        print("  Abrindo o navegador. Esta janela pode ser fechada.\n")
        if open_browser:
            webbrowser.open(URL)
        return 3

    from .app import create_app  # só aqui: criar o app liga a sincronização com o Drive

    app = create_app()
    print(f"\n  TexDesk {__version__} rodando em {URL}")
    print("  NÃO feche esta janela enquanto estiver usando (pode minimizar).")
    print("  Fechar esta janela desliga o editor e a sincronização com o Google Drive.\n")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(URL,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
