# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Busca e substituição em todos os arquivos do projeto e contagem de palavras do documento."""

import re
from pathlib import Path

from .storage import is_hidden, is_text

MAX_RESULTS = 500


# ---------------------------------------------------------------- busca no projeto


def _pattern(q: str, case: bool, regex: bool, word: bool):
    pat = q if regex else re.escape(q)
    if word:
        pat = rf"(?<!\w){pat}(?!\w)"
    return re.compile(pat, 0 if case else re.IGNORECASE)


def _text_files(d: Path):
    files = sorted((p for p in d.rglob("*") if p.is_file()), key=lambda p: p.relative_to(d).as_posix().lower())
    return [p for p in files if not is_hidden(p.relative_to(d)) and is_text(p)]


def search(d: Path, q: str, case: bool = False, regex: bool = False, word: bool = False):
    """Ocorrências de q nos arquivos de texto. Levanta re.error se a expressão for inválida."""
    rx = _pattern(q, case, regex, word)
    results = []
    for p in _text_files(d):
        rel = p.relative_to(d)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in rx.finditer(line):
                if m.end() == m.start():
                    continue  # expressão que casa com vazio (ex.: "a*")
                if len(results) >= MAX_RESULTS:
                    return {"results": results, "truncated": True}
                # recorta linhas longas em volta da ocorrência
                start = max(0, m.start() - 60)
                results.append(
                    {
                        "path": rel.as_posix(),
                        "line": n,
                        "col": m.start(),
                        "len": m.end() - m.start(),
                        "text": line[start : m.end() + 100],
                        "offset": m.start() - start,
                    }
                )
    return {"results": results, "truncated": False}


def replace(d: Path, q: str, repl: str, case=False, regex=False, word=False, paths=None):
    """Substitui as ocorrências (linha a linha, como a busca) e devolve {caminho: quantas}.

    O texto novo é literal (barras invertidas do LaTeX ficam como estão); com expressão
    regular, $1…$9 viram os grupos capturados.
    """
    rx = _pattern(q, case, regex, word)
    group = re.compile(r"\$(\d)")

    def sub(m):
        if not regex:
            return repl
        return group.sub(lambda g: m.group(int(g.group(1))) or "" if int(g.group(1)) <= rx.groups else g.group(0), repl)

    changed = {}
    for p in _text_files(d):
        rel = p.relative_to(d).as_posix()
        if paths is not None and rel not in paths:
            continue
        try:
            text = p.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # não mexe em arquivos que não são UTF-8 válido
        total = 0
        lines = text.split("\n")
        for i, line in enumerate(lines):
            body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
            hits = sum(1 for m in rx.finditer(body) if m.end() > m.start())
            if hits:
                lines[i] = rx.sub(lambda m: sub(m) if m.end() > m.start() else m.group(0), body) + cr
                total += hits
        if total:
            p.write_bytes("\n".join(lines).encode("utf-8"))
            changed[rel] = total
    return changed


# ---------------------------------------------------------------- contagem de palavras
# Parecida com o texcount: conta o texto do corpo, os títulos e as legendas separadamente,
# e as fórmulas à parte. Segue \input, \include e \subfile a partir do documento principal.

WORD_RE = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
HEADING = r"part|chapter|section|subsection|subsubsection|paragraph|subparagraph|title"
INCLUDE_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
# ambientes cujo conteúdo não é texto
SKIP_ENVS = r"verbatim|lstlisting|minted|comment|tikzpicture|thebibliography|filecontents\*?"
DISPLAY_ENVS = r"equation|align|gather|multline|eqnarray|displaymath|math|flalign|alignat"
# comandos cujo argumento some (não é texto do documento)
DROP_ARGS = (
    r"label|ref|eqref|pageref|autoref|cref|Cref|nameref|cite\w*|citep|citet|parencite|textcite|autocite|"
    r"usepackage|documentclass|includegraphics|input|include|subfile|bibliography|bibliographystyle|"
    r"addbibresource|url|vspace|hspace|setlength|addtolength|setcounter|newcommand|renewcommand|"
    r"providecommand|newenvironment|renewenvironment|DeclareMathOperator|hypersetup|graphicspath|"
    r"begin|end|pagestyle|thispagestyle|pagenumbering|color|textcolor|definecolor|geometry|"
    r"tableofcontents|listoffigures|listoftables|printbibliography|maketitle|newpage|clearpage|"
    r"linewidth|textwidth|fontsize|selectfont|usetheme|usecolortheme|setbeamertemplate|setbeamercolor"
)


def _group_end(s: str, i: int):
    """s[i] é '{': devolve o índice logo depois do '}' correspondente."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(s)


def _take(s: str, names: str):
    """Tira \\nome[...]{arg} do texto e devolve (texto sem eles, lista dos args)."""
    rx = re.compile(rf"\\(?:{names})\*?\s*(?:\[[^\]]*\]\s*)*(?=\{{)")
    out, args, pos = [], [], 0
    for m in rx.finditer(s):
        if m.start() < pos:
            continue
        end = _group_end(s, m.end())
        out.append(s[pos : m.start()])
        args.append(s[m.end() + 1 : end - 1])
        pos = end
    out.append(s[pos:])
    return "".join(out), args


def _strip_comments(s: str):
    return re.sub(r"(?<!\\)%.*", "", s)


def _words(s: str):
    s = re.sub(r"\\[a-zA-Z@]+\*?", " ", s)  # comandos que sobraram (o argumento fica)
    s = re.sub(r"\\.", " ", s)
    s = re.sub(r"[{}\[\]~]", " ", s)
    return len(WORD_RE.findall(s))


def _count_text(s: str):
    r = {"text": 0, "headers": 0, "captions": 0, "inlineMath": 0, "displayMath": 0}
    s = re.sub(rf"\\begin\{{({SKIP_ENVS})\}}.*?\\end\{{\1\}}", " ", s, flags=re.S)
    # fórmulas em destaque e no meio do texto
    display = rf"\\begin\{{(?:{DISPLAY_ENVS})\*?\}}.*?\\end\{{(?:{DISPLAY_ENVS})\*?\}}|\$\$.*?\$\$|\\\[.*?\\\]"
    r["displayMath"] = len(re.findall(display, s, flags=re.S))
    s = re.sub(display, " ", s, flags=re.S)
    inline = r"(?<!\\)\$.+?(?<!\\)\$|\\\(.*?\\\)"
    r["inlineMath"] = len(re.findall(inline, s, flags=re.S))
    s = re.sub(inline, " ", s, flags=re.S)
    s, heads = _take(s, HEADING)
    r["headers"] = sum(_words(h) for h in heads)
    s, caps = _take(s, "caption")
    r["captions"] = sum(_words(c) for c in caps)
    s, _ = _take(s, DROP_ARGS)
    r["text"] = _words(s)
    return r


def word_count(d: Path, main: str):
    """Contagem do documento principal e dos arquivos que ele inclui."""
    total = {"text": 0, "headers": 0, "captions": 0, "inlineMath": 0, "displayMath": 0}
    files, seen = [], set()
    main_dir = (d / main).parent

    def resolve(ref: str, base: Path):
        ref = ref.strip()
        for root in (base, main_dir, d):
            for cand in (ref, ref + ".tex"):
                p = (root / cand).resolve()
                if p.is_file() and d.resolve() in p.parents:
                    return p
        return None

    def visit(p: Path, is_main: bool):
        if p in seen:
            return
        seen.add(p)
        s = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        if is_main:
            m = re.search(r"\\begin\{document\}(.*?)(?:\\end\{document\}|$)", s, flags=re.S)
            if m:
                s = m.group(1)
        includes = INCLUDE_RE.findall(s)
        r = _count_text(s)
        for k in total:
            total[k] += r[k]
        files.append({"path": p.relative_to(d.resolve()).as_posix(), **r})
        for ref in includes:
            child = resolve(ref, p.parent)
            if child:
                visit(child, False)

    start = (d / main).resolve()
    if start.is_file():
        visit(start, True)
    return {**total, "words": total["text"] + total["headers"] + total["captions"], "files": files}
