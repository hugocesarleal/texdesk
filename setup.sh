#!/usr/bin/env bash
# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Instala o TexDesk no Linux e no macOS: ambiente Python (.venv), Tectonic, biber
# e os pacotes LaTeX dos modelos. É o equivalente do setup.ps1 (Windows).
set -euo pipefail
cd "$(dirname "$0")"

TECTONIC_VERSION=0.15.0
BIBER_VERSION=2.17   # casa com o biblatex 3.17 do pacote padrão do Tectonic
BIBER_URL=https://sourceforge.net/projects/biblatex-biber/files/biblatex-biber/$BIBER_VERSION/binaries

verde() { printf '\033[32m%s\033[0m\n' "$*"; }
amarelo() { printf '\033[33m%s\033[0m\n' "$*"; }
erro() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

baixar() {  # baixar URL -> stdout
    if command -v curl >/dev/null; then curl -fsSL -A Wget "$1"
    elif command -v wget >/dev/null; then wget -qO- "$1"
    else erro "É preciso ter o curl ou o wget instalado."
    fi
}

# ---- sistema e processador
case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)          TECTONIC_TARGET=x86_64-unknown-linux-musl;  BIBER_FILE=Linux/biber-linux_x86_64.tar.gz ;;
    Linux-aarch64|Linux-arm64) TECTONIC_TARGET=aarch64-unknown-linux-musl; BIBER_FILE= ;;
    Darwin-arm64)          TECTONIC_TARGET=aarch64-apple-darwin;      BIBER_FILE=MacOS/biber-darwin_universal.tar.gz ;;
    Darwin-x86_64)         TECTONIC_TARGET=x86_64-apple-darwin;       BIBER_FILE=MacOS/biber-darwin_universal.tar.gz ;;
    *) erro "Sistema não suportado: $(uname -s) $(uname -m). Veja o README." ;;
esac

# ---- Python 3.10+ num ambiente isolado (.venv); muitas distribuições bloqueiam o
#      "pip install" direto no Python do sistema (PEP 668)
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || erro "Python 3 não encontrado. Instale o Python 3.10 ou mais novo."
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || erro "É preciso o Python 3.10 ou mais novo (encontrado: $("$PY" --version 2>&1))."
if [ ! -x .venv/bin/python ]; then
    echo "Criando o ambiente Python (.venv)..."
    "$PY" -m venv .venv || erro "Não foi possível criar o .venv. No Debian/Ubuntu: sudo apt install python3-venv"
fi
echo "Instalando dependências Python..."
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

# ---- Tectonic (motor LaTeX)
mkdir -p tools
if [ ! -x tools/tectonic ]; then
    echo "Baixando o Tectonic $TECTONIC_VERSION ($TECTONIC_TARGET)..."
    baixar "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$TECTONIC_VERSION/tectonic-$TECTONIC_VERSION-$TECTONIC_TARGET.tar.gz" \
        | tar -xz -C tools
    chmod +x tools/tectonic
fi

# ---- biber (bibliografias com biblatex)
if [ ! -x tools/biber ]; then
    if [ -n "$BIBER_FILE" ]; then
        echo "Baixando o biber $BIBER_VERSION..."
        baixar "$BIBER_URL/$BIBER_FILE/download" | tar -xz -C tools
        chmod +x tools/biber
    else
        amarelo "O biber $BIBER_VERSION não tem versão para $(uname -m). Projetos com biblatex precisarão"
        amarelo "do biber do sistema (ex.: sudo apt install biber); o resto funciona normalmente."
    fi
fi

# macOS: arquivos baixados ganham a marca de "quarentena", que impede a execução
if [ "$(uname -s)" = Darwin ]; then xattr -dr com.apple.quarantine tools 2>/dev/null || true; fi

tools/tectonic --version
[ -x tools/biber ] && tools/biber --version

# ---- dicionários do corretor ortográfico (português e inglês; os outros no primeiro uso)
echo "Baixando os dicionários do corretor ortográfico..."
.venv/bin/python -m texdesk.spell pt_BR en_US

# ---- pré-baixa os pacotes LaTeX dos modelos (ficam no cache do Tectonic, compartilhado
#      por todos os projetos): o primeiro documento de cada modelo compila em segundos
echo
echo "Preparando os pacotes LaTeX dos modelos (só na primeira vez; pode levar alguns minutos)..."
export PATH="$PWD/tools:$PATH"   # para o Tectonic achar o biber
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
for tpl in templates/*/; do
    name="$(basename "$tpl")"
    cp -R "$tpl" "$work/$name"
    mkdir -p "$work/$name/out"
    printf '  %-14s' "$name"
    inicio=$SECONDS
    if (cd "$work/$name" && "$OLDPWD/tools/tectonic" --keep-logs --outdir out --chatter minimal main.tex \
            >out/stdout.txt 2>out/stderr.txt); then
        verde "pronto ($((SECONDS - inicio)) s)"
    else
        # não impede a instalação: o que faltar é baixado na primeira compilação
        amarelo "não foi possível (sem internet?); os pacotes serão baixados na primeira compilação"
    fi
done

date -u +%Y-%m-%dT%H:%M:%S > tools/.setup-ok   # o iniciar.sh roda este script até existir
echo
verde "Pronto! Rode ./iniciar.sh para abrir o TexDesk."
