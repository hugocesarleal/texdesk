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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
