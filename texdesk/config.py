# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Caminhos e constantes do TexDesk."""
import os
import re
from pathlib import Path

# pasta do TexDesk (onde estão static/, templates/ e tools/)
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
TOOLS = ROOT / "tools"
TECTONIC = TOOLS / ("tectonic.exe" if os.name == "nt" else "tectonic")

# dados do usuário (projetos, PDFs, conexão com o Drive). TEXDESK_DATA permite usar outra
# pasta; os testes usam isso para nunca tocar nos projetos reais
DATA = Path(os.environ.get("TEXDESK_DATA", ROOT)).resolve()
PROJECTS = DATA / "projects"
OUTPUT = DATA / "output"
DRIVE_STATE = DATA / ".drive"

PORT = int(os.environ.get("PORT", 5050))
URL = f"http://127.0.0.1:{PORT}"

# arquivos internos dentro de cada projeto (ocultos na árvore de arquivos)
SETTINGS_FILE = ".project.json"
THUMB_FILE = ".thumbnail.png"
TEMPLATE_META = ".template.json"  # descrição de um modelo (fica fora do projeto criado)

NAME_RE = re.compile(r"^[\w\-. ]{1,80}$", re.UNICODE)  # nome de projeto válido
TEXT_EXT = {".tex", ".bib", ".cls", ".sty", ".bst", ".txt", ".md", ".csv", ".dat",
            ".tikz", ".cfg", ".def", ".ltx", ".dtx", ".ins", ".bbx", ".cbx", ".lbx",
            ".json", ".xml", ".py", ".m", ".r", ".gp", ".asy", ".lua", ".bbl", ".log"}

COMPILE_TIMEOUT = 600  # segundos
MAX_UPLOAD_MB = 500    # limite por requisição (upload de arquivos ou de projeto .zip)
