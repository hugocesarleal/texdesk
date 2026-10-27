# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Corretor ortográfico offline, com os dicionários Hunspell do LibreOffice.

Os dicionários ficam em tools/dictionaries. A instalação já baixa português e inglês;
os outros idiomas são baixados na primeira vez que forem usados (com o hash conferido).
A leitura dos dicionários é feita pelo spylls, uma implementação do Hunspell em Python.

Uso na linha de comando (pela instalação): python -m texdesk.spell pt_BR en_US
"""

import hashlib
import json
import logging
import sys
import threading
import urllib.request

from .config import DATA, TOOLS

logger = logging.getLogger(__name__)

DICT_DIR = TOOLS / "dictionaries"
SOURCE = "https://raw.githubusercontent.com/LibreOffice/dictionaries/libreoffice-24.8.4.2/"
# idioma -> (caminho no repositório do LibreOffice, nome, sha256 do .aff, sha256 do .dic)
LANGUAGES = {
    "pt_BR": (
        "pt_BR/pt_BR",
        "Português (Brasil)",
        "21d8ad2a769a60e17e2b5ea4ef11d4d593a58b9e2a82d642ef82d6a4c5523865",
        "a38bfb26b68ece2834e79fe83e48d5792652970ace12db89d1b9674bf9933183",
    ),
    "pt_PT": (
        "pt_PT/pt_PT",
        "Português (Portugal)",
        "975a209fcc892cb382fa5f34a28c391a39668661ce373ae071287809c5fcae24",
        "9d90cfd9fb15312db71fbe46c11f871df67684dae7c218ab270142e7ae68c377",
    ),
    "en_US": (
        "en/en_US",
        "Inglês (EUA)",
        "e746c882dd6f303c2c46e7452804b9201115a6942cfeb15f18f8edf774d2e24e",
        "f0b1a234bd178bdd01875b2a392a9647f888b8fe879f79c52aae62c2759b3647",
    ),
    "en_GB": (
        "en/en_GB",
        "Inglês (Reino Unido)",
        "04755f317851defd8b9f77fd7e5d60f495221fad926d0df346cd9b61b646bfc2",
        "e070c64007d0f6a3423d028a53da099934b5f967dc0ef6d01b631ec2119659d4",
    ),
    "es_ES": (
        "es/es_ES",
        "Espanhol",
        "892039d59db11d747061b81c3a92a52d48ba0e055b5835af1943cbd3c2fba85b",
        "21cbea1e258f1fa98a035efd4e700ef41d9e6a8f07ed9023c4aa3915e5eb1362",
    ),
    "fr_FR": (
        "fr_FR/fr",
        "Francês",
        "4730775ff4488c4a9aa4833393c8b2187126336eed766866300a58a75fe874f0",
        "b99447ab2e655c1e4b64509cfd2e6c24821242bff1f971b49eac723e388a2d19",
    ),
    "it_IT": (
        "it_IT/it_IT",
        "Italiano",
        "951afaa19272f13555b8823e8bcf9ccf78f8fe1a07835bdfb912ab3e4d537c2b",
        "bae1e3501dcd2a923669592493b3fde6c02aae7c7aab83bf5e5b49077e73dd64",
    ),
    "de_DE": (
        "de/de_DE_frami",
        "Alemão",
        "646bf3333ac69c23e9d794533ee5241d6f755c359e8fe10a648f87613743d594",
        "52d2484a70681386d979e958f2f828a976f0dcdaa680038f371bc70abcf7463a",
    ),
}


class SpellError(Exception):
    """Idioma inexistente ou dicionário que não pôde ser baixado."""


_dicts = {}
_locks = {lang: threading.Lock() for lang in LANGUAGES}


def download(lang: str):
    """Baixa o dicionário do idioma, se ainda não estiver em tools/dictionaries."""
    if lang not in LANGUAGES:
        raise SpellError(f"Idioma não disponível: {lang}")
    path, _, *hashes = LANGUAGES[lang]
    DICT_DIR.mkdir(parents=True, exist_ok=True)
    for ext, sha in zip((".aff", ".dic"), hashes, strict=True):
        dest = DICT_DIR / f"{lang}{ext}"
        if dest.exists():
            continue
        try:
            data = urllib.request.urlopen(SOURCE + path + ext, timeout=60).read()
        except OSError as e:
            raise SpellError(
                f"Não foi possível baixar o dicionário ({LANGUAGES[lang][1]}). Verifique a internet."
            ) from e
        if hashlib.sha256(data).hexdigest() != sha:
            raise SpellError(f"O dicionário baixado ({lang}{ext}) não confere com o esperado.")
        tmp = dest.with_suffix(ext + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        logger.info("Dicionário %s%s baixado (%d KB)", lang, ext, len(data) // 1024)


def _dictionary(lang: str):
    if lang not in LANGUAGES:
        raise SpellError(f"Idioma não disponível: {lang}")
    if lang in _dicts:
        return _dicts[lang]
    with _locks[lang]:  # o primeiro uso carrega (~2 s); os pedidos ao mesmo tempo esperam
        if lang not in _dicts:
            from spylls.hunspell import Dictionary

            download(lang)
            _dicts[lang] = Dictionary.from_files(str(DICT_DIR / lang))
        return _dicts[lang]


def unknown(lang: str, words: list[str]):
    """Palavras que não estão no dicionário."""
    d = _dictionary(lang)
    words = {w for w in words if isinstance(w, str) and 0 < len(w) <= 60}
    return sorted(w for w in list(words)[:5000] if not d.lookup(w))


def suggestions(lang: str, word: str, limit: int = 6):
    d = _dictionary(lang)
    out = []
    for s in d.suggest(word[:60]):
        out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- dicionário pessoal
# Palavras que o usuário adicionou, valendo para todos os projetos e idiomas. Fica com os
# dados do TexDesk (e não no navegador), para não se perder ao limpar os dados do navegador.
PERSONAL = DATA / "dictionary.json"
MAX_PERSONAL = 20000
_personal_lock = threading.Lock()


def personal_words():
    try:
        words = json.loads(PERSONAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [w for w in words if isinstance(w, str)] if isinstance(words, list) else []


def update_personal(add=(), remove=()):
    """Adiciona e remove palavras (sem diferenciar maiúsculas). Devolve a lista nova."""
    with _personal_lock:
        words = {w.lower(): w for w in personal_words()}
        for w in add:
            if isinstance(w, str) and 0 < len(w.strip()) <= 60:
                words.setdefault(w.strip().lower(), w.strip().lower())
        for w in remove:
            if isinstance(w, str):
                words.pop(w.strip().lower(), None)
        out = sorted(words.values(), key=str.lower)[:MAX_PERSONAL]
        PERSONAL.parent.mkdir(parents=True, exist_ok=True)
        tmp = PERSONAL.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(PERSONAL)
        return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for code in sys.argv[1:]:
        try:
            download(code)
        except SpellError as e:
            print(e)
            sys.exit(1)
