#!/usr/bin/env bash
# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Abre o TexDesk no Linux e no macOS (equivalente do iniciar.bat).
cd "$(dirname "$0")"

# instala na primeira vez, e de novo se o ambiente Python (.venv) sumir ou quebrar
if [ ! -f tools/.setup-ok ] || ! .venv/bin/python -c '' 2>/dev/null; then
    ./setup.sh || { echo "A instalação não terminou. Veja a mensagem acima."; exit 1; }
fi

.venv/bin/python -m texdesk --abrir
codigo=$?
if [ "$codigo" -ne 0 ] && [ "$codigo" -ne 3 ]; then   # 3 = já havia um TexDesk rodando
    echo
    echo "O servidor parou. Se apareceu algum erro acima, copie a mensagem."
fi
exit "$codigo"
