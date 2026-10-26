#!/usr/bin/env bash
# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Abre o TexDesk no Linux e no macOS (equivalente do iniciar.bat).
cd "$(dirname "$0")"

if [ ! -f tools/.setup-ok ] || [ ! -x .venv/bin/python ]; then
    ./setup.sh || { echo "A instalação não terminou. Veja a mensagem acima."; exit 1; }
fi

.venv/bin/python server.py --abrir
codigo=$?
if [ "$codigo" -ne 0 ] && [ "$codigo" -ne 3 ]; then   # 3 = já havia um TexDesk rodando
    echo
    echo "O servidor parou. Se apareceu algum erro acima, copie a mensagem."
fi
exit "$codigo"
