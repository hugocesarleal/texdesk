# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""O que o TexDesk busca na internet: aviso de versão nova e referências por DOI.

Nada disso é necessário para editar e compilar: sem internet, as duas coisas só falham
em silêncio (o aviso) ou com uma mensagem (o DOI).
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

REPO = "hugocesarleal/texdesk"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"TexDesk/{__version__} (+https://github.com/{REPO})"
UPDATE_TTL = 24 * 3600  # consulta o GitHub no máximo uma vez por dia

_update = {"checked": 0.0, "result": None}
_update_lock = threading.Lock()


class OnlineError(Exception):
    """Falha que vira mensagem para o usuário."""


def _get(url, accept, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URLs fixas, https)
        return r.read().decode("utf-8", "replace")


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def update_check_enabled():
    return os.environ.get("TEXDESK_UPDATE_CHECK", "1") != "0"


def latest_release():
    """{current, latest, url, newer} da última versão publicada, ou None se não der para saber."""
    if not update_check_enabled():
        return None
    with _update_lock:
        if time.time() - _update["checked"] < UPDATE_TTL:
            return _update["result"]
        _update["checked"] = time.time()
        try:
            data = json.loads(_get(RELEASES_API, "application/vnd.github+json", 5))
            tag = data.get("tag_name") or ""
            result = {
                "current": __version__,
                "latest": tag.lstrip("v"),
                "url": data.get("html_url") or f"https://github.com/{REPO}/releases",
                "newer": bool(tag) and _version_tuple(tag) > _version_tuple(__version__),
            }
        except (OSError, ValueError, urllib.error.URLError):
            result = None  # sem internet ou GitHub fora: tenta de novo amanhã
        _update["result"] = result
        return result


# ---------------------------------------------------------------- referências por DOI
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def normalize_doi(text: str):
    """Aceita o DOI puro, "doi:10…" ou o link https://doi.org/10…"""
    doi = (text or "").strip()
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    doi = urllib.parse.unquote(doi).strip()
    if not DOI_RE.match(doi):
        raise OnlineError("Isso não parece um DOI. Ele começa com 10. (por exemplo, 10.1000/xyz123)")
    return doi


def _split_fields(body: str):
    """Campos "nome = {valor}" de uma entrada BibTeX, respeitando chaves e aspas."""
    fields, i, n = [], 0, len(body)
    while i < n:
        m = re.compile(r"\s*,?\s*([\w\-:.]+)\s*=\s*").match(body, i)
        if not m:
            break
        name, i = m.group(1), m.end()
        if i < n and body[i] in '{"':
            close = "}" if body[i] == "{" else '"'
            depth, j = 0, i
            while j < n:
                c = body[j]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                if (close == "}" and depth == 0 and c == "}") or (close == '"' and j > i and c == '"' and depth == 0):
                    break
                j += 1
            value, i = body[i : j + 1], j + 1
        else:
            m2 = re.compile(r"[^,}\s]+").match(body, i)
            value = m2.group(0) if m2 else ""
            i = m2.end() if m2 else i + 1
        fields.append((name.lower(), value))
    return fields


def format_bibtex(raw: str):
    """Reescreve a entrada com um campo por linha, alinhado como nos .bib dos modelos."""
    m = re.search(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*)\}\s*$", raw.strip(), re.S)
    if not m:
        raise OnlineError("O serviço de DOI devolveu uma referência em formato inesperado")
    kind, key, body = m.group(1).lower(), m.group(2), m.group(3)
    fields = [(k, v) for k, v in _split_fields(body) if k not in ("abstract",)]
    width = max((len(k) for k, _ in fields), default=0)
    lines = [f"@{kind}{{{key},"] + [f"  {k.ljust(width)} = {v}," for k, v in fields]
    lines[-1] = lines[-1].rstrip(",")
    return key, "\n".join(lines) + "\n}\n"


def doi_bibtex(text: str):
    """{doi, key, bibtex} da referência, consultando doi.org (Crossref, DataCite…)."""
    doi = normalize_doi(text)
    url = "https://doi.org/" + urllib.parse.quote(doi, safe="/:;()._-<>")
    try:
        raw = _get(url, "application/x-bibtex; charset=utf-8", 15)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise OnlineError(f"DOI não encontrado: {doi}") from e
        raise OnlineError(f"O serviço de DOI respondeu com erro ({e.code}). Tente de novo mais tarde.") from e
    except (OSError, urllib.error.URLError) as e:
        raise OnlineError("Não foi possível consultar o DOI. Confira a conexão com a internet.") from e
    if not raw.lstrip().startswith("@"):
        raise OnlineError("Este DOI não tem referência em BibTeX disponível")
    key, bib = format_bibtex(raw)
    return {"doi": doi, "key": key, "bibtex": bib}
