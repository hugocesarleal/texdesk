# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Junção de duas versões de um arquivo de texto a partir da versão comum (como o git faz).

Quando o mesmo arquivo foi alterado neste computador e em outro desde a última sincronização,
cada versão é comparada com a última que os dois tinham em comum (a base). O que só um lado
mudou entra direto. Se os dois mexeram no mesmo trecho, a junção tenta de novo palavra por
palavra, porque no LaTeX um parágrafo costuma ser uma linha só: duas correções em frases
diferentes do mesmo parágrafo se juntam sozinhas. Só sobra conflito quando os dois mudaram
as mesmas palavras; nesse trecho fica a versão deste computador, e o conflito é devolvido
para o usuário escolher.
"""

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"\w+|\s+|[^\w\s]", re.UNICODE)


def _sync_regions(base, a, b):
    """Trechos iguais nas três versões: (base_ini, base_fim, a_ini, a_fim, b_ini, b_fim)."""
    ma = SequenceMatcher(None, base, a, autojunk=False).get_matching_blocks()
    mb = SequenceMatcher(None, base, b, autojunk=False).get_matching_blocks()
    out = []
    ia = ib = 0
    while ia < len(ma) and ib < len(mb):
        abase, amatch, alen = ma[ia]
        bbase, bmatch, blen = mb[ib]
        ini, fim = max(abase, bbase), min(abase + alen, bbase + blen)
        if ini < fim:
            asub, bsub = amatch + (ini - abase), bmatch + (ini - bbase)
            out.append((ini, fim, asub, asub + fim - ini, bsub, bsub + fim - ini))
        if abase + alen < bbase + blen:
            ia += 1
        else:
            ib += 1
    out.append((len(base), len(base), len(a), len(a), len(b), len(b)))
    return out


def _merge_seq(base, a, b):
    """Junta duas sequências. Devolve uma lista de ("ok", itens) e ("conflito", base, a, b)."""
    out = []
    iz = ia = ib = 0
    for zini, zfim, aini, afim, bini, bfim in _sync_regions(base, a, b):
        pa, pb, pz = a[ia:aini], b[ib:bini], base[iz:zini]
        if pa or pb or pz:
            if pa == pb:
                out.append(("ok", pa))
            elif pa == pz:  # só o outro lado mudou
                out.append(("ok", pb))
            elif pb == pz:  # só este lado mudou
                out.append(("ok", pa))
            else:
                out.append(("conflito", pz, pa, pb))
        if zfim > zini:
            out.append(("ok", base[zini:zfim]))
        iz, ia, ib = zfim, afim, bfim
    return out


def _merge_words(base, mine, theirs):
    """Junta um trecho palavra por palavra; None se as mesmas palavras mudaram dos dois lados."""
    parts = _merge_seq(_WORD.findall(base), _WORD.findall(mine), _WORD.findall(theirs))
    if any(p[0] == "conflito" for p in parts):
        return None
    return "".join(t for _, items in parts for t in items)


def merge3(base: str, mine: str, theirs: str):
    """Junta mine (deste computador) e theirs (do Drive), que partiram de base.

    Devolve (texto, conflitos). Cada conflito é {"line", "mine", "theirs"}: o trecho que ficou
    no texto (a versão deste computador, a partir da linha line, contada do 0) e o que o outro
    computador tinha no lugar.
    """
    if mine == theirs:
        return mine, []
    if base == mine:
        return theirs, []
    if base == theirs:
        return mine, []
    lines = [s.splitlines(keepends=True) for s in (base, mine, theirs)]
    text, conflicts, line = [], [], 0
    for part in _merge_seq(*lines):
        if part[0] == "ok":
            chunk = "".join(part[1])
        else:
            pz, pa, pb = ("".join(x) for x in part[1:])
            chunk = _merge_words(pz, pa, pb)
            if chunk is None:
                chunk = pa
                conflicts.append({"line": line, "mine": pa, "theirs": pb})
        text.append(chunk)
        line += chunk.count("\n")
    return "".join(text), conflicts


def apply_choice(text: str, conflict: dict):
    """Troca, no texto atual, o trecho de um conflito pela versão do outro computador.

    Procura o trecho na linha registrada; se o texto mudou desde então, procura o trecho no
    arquivo inteiro (precisa aparecer uma vez só). Devolve o texto novo, ou None se não achar.
    """
    mine, theirs = conflict["mine"], conflict["theirs"]
    lines = text.splitlines(keepends=True)
    line = conflict.get("line", 0)
    if 0 <= line <= len(lines):
        start = len("".join(lines[:line]))
        if text.startswith(mine, start):
            return text[:start] + theirs + text[start + len(mine) :]
    if mine and text.count(mine) == 1:
        return text.replace(mine, theirs, 1)
    return None
