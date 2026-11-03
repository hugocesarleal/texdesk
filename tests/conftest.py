# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Configuração comum dos testes.

O servidor é importado com TEXDESK_DATA apontando para uma pasta temporária: os testes
nunca tocam nos projetos, nos PDFs nem na conexão com o Google Drive reais.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

os.environ["TEXDESK_DATA"] = tempfile.mkdtemp(prefix="texdesk-test-")
os.environ["TEXDESK_KEYRING"] = "0"  # nunca tocar no cofre de senhas real do computador
os.environ["TEXDESK_UPDATE_CHECK"] = "0"  # nem consultar o GitHub
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from texdesk.app import create_app  # noqa: E402  (precisa do TEXDESK_DATA acima)

APP = create_app()  # uma aplicação para todos os testes
APP.config["TESTING"] = True


def github_zip(repo, files, commit="0123abc"):
    """Um .zip como o que o GitHub monta para uma branch: tudo dentro de "<repo>-main/"."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = repo.split("/")[1] + "-main/"
        z.writestr(top, "")
        for name, data in files.items():
            z.writestr(top + name, data)
        z.comment = commit.encode()
    return buf.getvalue()


# arquivos falsos dos repositórios de Marcos Roberto Ribeiro (os testes não usam a internet)
FAKE_REPOS = {
    "ifmg-slides": {
        "apresentacao.tex": "\\documentclass{beamer}\n\\begin{document}\nslides\n\\end{document}\n",
        "referencias.bib": "",
        "ifslides2024.sty": "% tema",
        "biblatexfix.sty": "% fix",
        "LICENSE": "GPL-3.0",
        "figuras/if_q.pdf": b"%PDF-1.4 falso",
        "README.md": "nao copiar",
        "apresentacao.pdf": b"%PDF-1.4 nao copiar",
    },
    "ifmg-artigo": {
        "exemplo_artigo.tex": "\\documentclass{iftex2024}\n\\begin{document}\nartigo\n\\end{document}\n",
        "exemplo_monografia.tex": "nao copiar",
        "referencias.bib": "",
        "iftex2024.cls": "% classe",
        "biblatexfix.sty": "% fix",
        "LICENSE": "GPL-3.0",
    },
}
