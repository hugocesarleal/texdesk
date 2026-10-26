"""Leitor do log do TeX.

Extrai erros, avisos e "badboxes" (overfull/underfull) com arquivo e linha,
rastreando a pilha de arquivos abertos pelos parênteses do log.
"""
import re

LOG_WRAP = 79  # o TeX quebra linhas do log nessa largura

FILE_RE = re.compile(r'^\(\s*"?((?:\.{0,2}/|[A-Za-z]:[/\\]|/)?[^\s()"]*?\.[A-Za-z0-9]{1,8})"?')
LINE_RE = re.compile(r"^l\.(\d+)\s?(.*)$")
INPUT_LINE_RE = re.compile(r"on input line (\d+)")
BADBOX_RE = re.compile(r"^(Over|Under)full \\[hv]box .*? (?:at lines? (\d+)(?:--(\d+))?|has occurred while \\output is active|detected at line (\d+))")
WARN_RE = re.compile(r"^(?:LaTeX|Package (\S+)|Class (\S+)|LaTeX Font|pdfTeX|Font|Missing character)(?: (\S+))? [Ww]arning\s*:?\s*(.*)$")
PKG_ERR_RE = re.compile(r"^! (?:LaTeX|Package \S+|Class \S+) Error: ")


def unwrap(log: str):
    lines = log.replace("\r\n", "\n").split("\n")
    out = []
    buf = ""
    for ln in lines:
        buf += ln
        if len(ln) == LOG_WRAP:
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


def _norm(path: str, main_dir: str):
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if main_dir and not re.match(r"^([A-Za-z]:)?/", p):
        p = f"{main_dir}/{p}"
    return p


def _is_project_file(path):
    return path is not None and not re.match(r"^([A-Za-z]:)?/", path) and "texmf" not in path.lower()


def parse_log(log: str, main_dir: str = "", main_file: str = "main.tex"):
    lines = unwrap(log)
    stack = []  # pilha de arquivos abertos
    entries = []

    def current_file():
        for f in reversed(stack):
            if f is not None:
                return f
        return main_file

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # ---- erros: "! Mensagem"
        if line.startswith("! "):
            msg = line[2:]
            if PKG_ERR_RE.match(line):
                msg = PKG_ERR_RE.sub("", line)
            ctx = []
            lineno = None
            j = i + 1
            while j < n and j < i + 25:
                m = LINE_RE.match(lines[j])
                if m:
                    lineno = int(m.group(1))
                    ctx.append(lines[j])
                    if j + 1 < n:
                        ctx.append(lines[j + 1])
                    break
                ctx.append(lines[j])
                j += 1
            kind = ""
            mm = re.match(r"^! (LaTeX|Package (\S+)|Class (\S+)) Error", line)
            if mm:
                kind = mm.group(1)
            entries.append({"level": "error", "file": current_file(), "line": lineno,
                            "message": msg.strip(), "content": "\n".join(ctx).strip(), "kind": kind})
            i = j + 1 if lineno is not None else i + 1
            continue

        # ---- erro no estilo file:line:error (-file-line-error)
        m = re.match(r"^(\.{0,2}/[^:]+\.\w+):(\d+): (.*)$", line)
        if m:
            entries.append({"level": "error", "file": _norm(m.group(1), main_dir), "line": int(m.group(2)),
                            "message": m.group(3), "content": ""})
            i += 1
            continue

        # ---- avisos
        m = WARN_RE.match(line)
        if m:
            msg = m.group(4)
            pkg = m.group(1) or m.group(2)
            # avisos de pacote continuam nas linhas seguintes com "(pkg)  "
            j = i + 1
            while j < n and pkg and lines[j].startswith(f"({pkg})"):
                msg += " " + lines[j][len(pkg) + 2:].strip()
                j += 1
            while j < n and not pkg and lines[j].strip() and not lines[j].startswith(("(", ")", "[", "!", "<")) \
                    and not msg.rstrip().endswith("."):
                msg += " " + lines[j].strip()
                j += 1
            lm = INPUT_LINE_RE.search(msg)
            entries.append({"level": "warning", "file": current_file(), "line": int(lm.group(1)) if lm else None,
                            "message": (f"{pkg}: " if pkg else "") + msg.strip(), "content": ""})
            i = j
            continue

        # ---- badboxes
        m = BADBOX_RE.match(line)
        if m:
            ln = m.group(2) or m.group(4)
            ctx = lines[i + 1] if i + 1 < n else ""
            entries.append({"level": "typesetting", "file": current_file(), "line": int(ln) if ln else None,
                            "message": line.strip(), "content": ctx})
            i += 1
            continue

        # ---- rastreamento de arquivos por parênteses
        k = 0
        L = len(line)
        while k < L:
            c = line[k]
            if c == "(":
                fm = FILE_RE.match(line[k:])
                if fm:
                    stack.append(_norm(fm.group(1), main_dir))
                    k += len(fm.group(0))
                    continue
                stack.append(None)
            elif c == ")":
                if stack:
                    stack.pop()
            k += 1
        i += 1

    for e in entries:
        if not _is_project_file(e["file"]):
            e["external"] = True  # arquivo de pacote/sistema, não do projeto
    # remove duplicatas consecutivas
    uniq, seen = [], set()
    for e in entries:
        key = (e["level"], e["file"], e["line"], e["message"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    order = {"error": 0, "warning": 1, "typesetting": 2}
    uniq.sort(key=lambda e: order.get(e["level"], 3))
    return uniq
