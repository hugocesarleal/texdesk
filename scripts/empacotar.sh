#!/usr/bin/env bash
# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Monta o pacote de release de um sistema, já com o Tectonic e o biber dentro.
#   uso: scripts/empacotar.sh <alvo> <versão> <pasta de saída>
#   alvos: windows-x64, linux-x64, linux-arm64, macos-arm64, macos-x64
# Usado pelo workflow .github/workflows/release.yml (roda no Linux).
set -euo pipefail

ALVO="$1"; VERSAO="$2"; SAIDA="$(mkdir -p "$3" && cd "$3" && pwd)"
TECTONIC_VERSION=0.15.0
BIBER_VERSION=2.17
TECTONIC_URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$TECTONIC_VERSION"
BIBER_URL="https://sourceforge.net/projects/biblatex-biber/files/biblatex-biber/$BIBER_VERSION/binaries"

case "$ALVO" in
    windows-x64)  T=x86_64-pc-windows-msvc.zip;        B=Windows/biber-MSWIN64.zip ;;
    linux-x64)    T=x86_64-unknown-linux-musl.tar.gz;  B=Linux/biber-linux_x86_64.tar.gz ;;
    linux-arm64)  T=aarch64-unknown-linux-musl.tar.gz; B= ;;   # o biber 2.17 não tem versão ARM64 para Linux
    macos-arm64)  T=aarch64-apple-darwin.tar.gz;       B=MacOS/biber-darwin_universal.tar.gz ;;
    macos-x64)    T=x86_64-apple-darwin.tar.gz;        B=MacOS/biber-darwin_universal.tar.gz ;;
    *) echo "alvo desconhecido: $ALVO" >&2; exit 1 ;;
esac

NOME="texdesk-$VERSAO"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASTA="$TMP/$NOME"
mkdir -p "$PASTA"

# código: só o que está no git (sem .github/ e tests/, marcados como export-ignore)
git archive --format=tar HEAD | tar -x -C "$PASTA"
echo "$VERSAO" > "$PASTA/VERSION"
if [ "$ALVO" = windows-x64 ]; then
    rm -f "$PASTA/setup.sh" "$PASTA/iniciar.sh"
else
    rm -f "$PASTA/setup.ps1" "$PASTA/iniciar.bat"
fi

# ferramentas do sistema-alvo
mkdir -p "$PASTA/tools"
extrair() {  # extrair ARQUIVO.zip|ARQUIVO.tar.gz -> tools/
    case "$1" in
        *.zip) unzip -q -o "$1" -d "$PASTA/tools" ;;
        *)     tar -xzf "$1" -C "$PASTA/tools" ;;
    esac
}
curl -fsSL -o "$TMP/tectonic-$T" "$TECTONIC_URL/tectonic-$TECTONIC_VERSION-$T"
extrair "$TMP/tectonic-$T"
if [ -n "$B" ]; then
    curl -fsSL -A Wget -o "$TMP/$(basename "$B")" "$BIBER_URL/$B/download"
    extrair "$TMP/$(basename "$B")"
fi
# dicionários do corretor ortográfico (português e inglês; os outros são baixados no primeiro uso)
(cd "$PASTA" && python3 -m texdesk.spell pt_BR en_US)
chmod +x "$PASTA"/tools/* "$PASTA"/*.sh 2>/dev/null || true

# compacta
cd "$TMP"
if [ "$ALVO" = windows-x64 ]; then
    ARQ="$SAIDA/$NOME-$ALVO.zip"
    zip -q -r "$ARQ" "$NOME"
else
    ARQ="$SAIDA/$NOME-$ALVO.tar.gz"
    tar -czf "$ARQ" "$NOME"   # preserva a permissão de execução dos scripts e binários
fi
echo "$ARQ ($(du -h "$ARQ" | cut -f1))"
ls "$PASTA/tools"
