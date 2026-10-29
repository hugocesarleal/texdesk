# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Inicia o TexDesk: python -m texdesk [--abrir]

--abrir  abre o navegador quando o servidor estiver pronto (usado pelo iniciar.bat/.sh).
Sai com o código 3 se já houver um TexDesk rodando (aí só abre o navegador).
"""

import logging
import sys
import threading
import urllib.request
import webbrowser

from . import __version__, logs
from .config import COMPILE_TIMEOUT, DATA, LOG_FILE, PORT, ROOT, URL

# não __name__: rodando como "python -m texdesk" ele vale "__main__", fora do log "texdesk"
log = logging.getLogger("texdesk.main")


def already_running():
    """No Windows, dois servidores conseguem abrir a mesma porta, e isso duplicaria a
    sincronização com o Drive. Então, antes de qualquer coisa, pergunta se já há um."""
    try:
        with urllib.request.urlopen(f"{URL}/api/drive/status", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def ensure_dependencies():
    """Confere as versões do requirements.txt e instala o que faltar ou estiver diferente.

    Quem atualiza o TexDesk (git pull ou um pacote novo por cima) não roda a instalação de
    novo; sem isto, uma dependência nova faria o servidor quebrar ao abrir.
    """
    import importlib.metadata
    import importlib.util
    import re
    import subprocess

    req = ROOT / "requirements.txt"
    pins = re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s#]+)", req.read_text(encoding="utf-8"), re.M)
    missing = []
    for name, version in pins:
        try:
            if importlib.metadata.version(name) != version:
                missing.append(f"{name} {version}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(f"{name} {version}")
    if not missing:
        return
    # o instalador do Python deixa desmarcar o pip; o ensurepip (da biblioteca padrão) o repõe
    if importlib.util.find_spec("pip") is None:
        print("\n  O pip não está instalado neste Python. Instalando...")
        if subprocess.call([sys.executable, "-m", "ensurepip", "--upgrade", "--default-pip"]) != 0:
            sys.exit(
                "\n  Não foi possível instalar o pip. Reinstale o Python pelo python.org deixando"
                '\n  marcada a opção "pip" e abra o TexDesk de novo.\n'
            )
    print(f"\n  Instalando dependências: {', '.join(missing)}...")
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(req)]
    if subprocess.call(cmd) != 0:
        sys.exit(
            "\n  Não foi possível instalar as dependências (veja o erro acima)."
            "\n  Confira a conexão com a internet e abra o TexDesk de novo.\n"
        )


def main():
    open_browser = "--abrir" in sys.argv
    if already_running():
        print(f"\n  O TexDesk já está rodando em {URL} (em segundo plano).")
        print("  Abrindo o navegador. Esta janela pode ser fechada.\n")
        if open_browser:
            webbrowser.open(URL)
        return 3

    ensure_dependencies()
    logs.setup()
    from waitress.server import create_server

    from . import services, updater
    from .app import create_app  # só aqui: criar o app liga a sincronização com o Drive

    updater.cleanup()  # o pacote e o backup de uma atualização anterior

    app = create_app()
    log.info("TexDesk %s iniciado em %s (dados em %s)", __version__, URL, DATA)
    print(f"\n  TexDesk {__version__} rodando em {URL}")
    print("  NÃO feche esta janela enquanto estiver usando (pode minimizar).")
    print("  Fechar esta janela desliga o editor e a sincronização com o Google Drive.")
    print(f"  Registro de erros: {LOG_FILE}\n")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(URL,)).start()
    # waitress: servidor de produção (o do Flask é só para desenvolvimento). Várias threads,
    # porque uma compilação longa não pode travar o resto da interface, e um tempo de
    # conexão maior que o limite de compilação, para não cortar a resposta no meio.
    server = create_server(
        app, host="127.0.0.1", port=PORT, threads=16, channel_timeout=COMPILE_TIMEOUT + 60, ident="TexDesk"
    )
    restart = threading.Event()

    def stop_for_update():
        """Chamado pelo atualizador: para o Drive e o servidor, e o main() abre o novo."""
        restart.set()
        services.syncer.stop()

        def close_all():  # na thread do servidor: sem conexões nem porta, o run() volta
            for channel in list(server._map.values()):
                channel.close()

        server.trigger.pull_trigger(close_all)

    updater.restart_hook = stop_for_update
    server.run()
    server.task_dispatcher.shutdown()
    if restart.is_set():
        print("\n  TexDesk atualizado. Reiniciando...\n")
        return updater.run_new_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
