# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""TexDesk — editor e compilador LaTeX local.

Servidor Flask que gerencia projetos e arquivos, compila com o Tectonic (motor XeTeX
que baixa pacotes sob demanda), lê o log do TeX e, se ligado, sincroniza os projetos
com o Google Drive. Para rodar: ``python -m texdesk``.
"""

__version__ = "0.3.0"
