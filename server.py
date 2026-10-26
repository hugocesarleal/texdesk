# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""TexDesk — editor e compilador LaTeX local.

Servidor Flask que gerencia projetos e arquivos, compila com o Tectonic
(motor XeTeX que baixa pacotes sob demanda), lê o log do TeX e, se ligado,
sincroniza os projetos com o Google Drive.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory

import drive_sync
from latexlog import parse_log
from synctex import SyncTex

ROOT = Path(__file__).resolve().parent
# dados do usuário (projetos, PDFs, conexão com o Drive); TEXDESK_DATA permite outra pasta,
# usada pelos testes para não tocar nos projetos reais
DATA = Path(os.environ.get("TEXDESK_DATA", ROOT)).resolve()
PROJECTS = DATA / "projects"
OUTPUT = DATA / "output"
TEMPLATES = ROOT / "templates"
TECTONIC = ROOT / "tools" / ("tectonic.exe" if os.name == "nt" else "tectonic")
SETTINGS_FILE = ".project.json"
THUMB_FILE = ".thumbnail.png"
TEXT_EXT = {".tex", ".bib", ".cls", ".sty", ".bst", ".txt", ".md", ".csv", ".dat",
            ".tikz", ".cfg", ".def", ".ltx", ".dtx", ".ins", ".bbx", ".cbx", ".lbx",
            ".json", ".xml", ".py", ".m", ".r", ".gp", ".asy", ".lua", ".bbl", ".log"}
COMPILE_TIMEOUT = 600
MAX_UPLOAD_MB = 500  # limite por requisição (upload de arquivos ou de projeto .zip)

PORT = int(os.environ.get("PORT", 5050))
URL = f"http://127.0.0.1:{PORT}"


def already_running():
    """No Windows, dois servidores conseguem abrir a mesma porta, e isso duplicaria
    a sincronização com o Drive. Então, antes de qualquer coisa, pergunta se já há um."""
    try:
        with urllib.request.urlopen(f"{URL}/api/drive/status", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


# antes de criar o processo de sincronização (mais abaixo)
if __name__ == "__main__" and already_running():
    print(f"\n  O TexDesk já está rodando em {URL} (em segundo plano).")
    print("  Abrindo o navegador. Esta janela pode ser fechada.\n")
    if "--abrir" in sys.argv:
        webbrowser.open(URL)
    sys.exit(3)

PROJECTS.mkdir(parents=True, exist_ok=True)
OUTPUT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ---------------------------------------------------------------- segurança
# O servidor só escuta em 127.0.0.1, mas qualquer site aberto no navegador consegue
# mandar requisições para ele. Sem as barreiras abaixo, um site poderia ligar o
# shell-escape, enviar um .tex com \write18 e compilar, executando comandos no computador.

ALLOWED_HOSTS = {f"{h}:{PORT}" for h in ("127.0.0.1", "localhost", "[::1]")}
CSRF_HEADER = "X-TexDesk"  # enviado pelo front-end em toda requisição que altera algo


@app.before_request
def security_checks():
    # DNS rebinding: um domínio do atacante que resolve para 127.0.0.1 chega com outro Host
    if request.host.lower() not in ALLOWED_HOSTS:
        abort(403, "Host não permitido")
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None  # leituras: a política de mesma origem do navegador já impede outro site de ler
    # CSRF: requisições vindas de outro site (o navegador informa nesses cabeçalhos)
    if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
        abort(403, "Requisição de outro site recusada")
    origin = request.headers.get("Origin")
    if origin and origin.lower().split("://", 1)[-1] not in ALLOWED_HOSTS:
        abort(403, "Origem não permitida")
    # um cabeçalho próprio não pode ser enviado por outro site sem permissão (preflight de
    # CORS), e este servidor nunca concede essa permissão
    if request.headers.get(CSRF_HEADER) != "1":
        abort(403, "Requisição sem o cabeçalho do TexDesk")
    return None


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # não pode ser embutido em sites de terceiros
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def json_body():
    """Corpo JSON da requisição; recusa outros tipos de conteúdo (ex.: text/plain)."""
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        abort(415, "Envie um JSON (Content-Type: application/json)")
    return data


def project_lock(name):
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


# ---------------------------------------------------------------- helpers

NAME_RE = re.compile(r"^[\w\-. ]{1,80}$", re.UNICODE)


def project_dir(name):
    if not NAME_RE.match(name) or name.startswith("."):
        abort(400, "Nome de projeto inválido")
    d = PROJECTS / name
    if not d.is_dir():
        abort(404, "Projeto não encontrado")
    return d


def safe_path(base: Path, rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel or any(part in ("..", "") for part in rel.split("/")):
        abort(400, "Caminho inválido")
    p = (base / rel).resolve()
    if base.resolve() not in p.parents:
        abort(400, "Caminho inválido")
    return p


def is_text(path: Path):
    return path.suffix.lower() in TEXT_EXT or path.suffix == ""


def load_settings(d: Path):
    f = d / SETTINGS_FILE
    s = {}
    if f.exists():
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            s = {}
    if not s.get("main") or not (d / s["main"]).exists():
        s["main"] = guess_main(d)
    s.setdefault("autoCompile", False)
    s.setdefault("shellEscape", False)
    s.setdefault("driveSync", False)
    return s


def save_settings(d: Path, s):
    (d / SETTINGS_FILE).write_text(json.dumps(s, indent=2), encoding="utf-8")


def guess_main(d: Path):
    texs = sorted(p for p in d.rglob("*.tex") if not any(x.startswith(".") for x in p.relative_to(d).parts))
    candidates = []
    for p in texs:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^[^%\n]*\\documentclass", t, re.M) and "\\begin{document}" in t:
            rel = p.relative_to(d)
            # prefere main.tex, depois arquivos mais rasos, evitando exemplos/modelos
            score = (p.name.lower() != "main.tex", bool(re.search(r"exemplo|example|sample|template|modelo", p.name, re.I)),
                     len(rel.parts), rel.as_posix())
            candidates.append((score, rel.as_posix()))
    if candidates:
        return min(candidates)[1]
    return texs[0].relative_to(d).as_posix() if texs else "main.tex"


def tree(d: Path):
    out = []
    for p in sorted(d.rglob("*"), key=lambda x: x.relative_to(d).as_posix().lower()):
        rel = p.relative_to(d)
        if any(part.startswith(".") for part in rel.parts):
            continue
        out.append({"path": rel.as_posix(), "type": "folder" if p.is_dir() else "file",
                    "text": p.is_file() and is_text(p), "size": p.stat().st_size if p.is_file() else 0})
    return out


# ---------------------------------------------------------------- Google Drive

def drive_enabled(name):
    f = PROJECTS / name / SETTINGS_FILE
    try:
        return bool(json.loads(f.read_text(encoding="utf-8")).get("driveSync"))
    except (OSError, ValueError):
        return False


drive = drive_sync.DriveClient(DATA / ".drive")
syncer = drive_sync.SyncManager(drive, PROJECTS, drive_enabled)
syncer.mark_all()  # envia o que mudou enquanto o servidor estava desligado


def changed(name):
    """Chamado após qualquer alteração nos arquivos do projeto."""
    syncer.mark_dirty(name)


def apply_sync_default(d: Path):
    """Projetos novos entram na sincronização se 'sincronizar todos' estiver ligado."""
    if drive.connected and drive.state().get("syncAll"):
        s = load_settings(d)
        s["driveSync"] = True
        save_settings(d, s)
        changed(d.name)


# ---------------------------------------------------------------- pages

@app.get("/")
def index():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/project/<name>")
def editor_page(name):
    project_dir(name)
    return send_from_directory(ROOT / "static", "editor.html")


# ---------------------------------------------------------------- projects

@app.get("/api/projects")
def list_projects():
    items = []
    for d in PROJECTS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            mtime = max((p.stat().st_mtime for p in d.rglob("*")
                         if p.is_file() and p.name not in (THUMB_FILE, SETTINGS_FILE, drive_sync.MANIFEST)),
                        default=d.stat().st_mtime)
            thumb = d / THUMB_FILE
            settings = load_settings(d)
            pdf = OUTPUT / d.name / (Path(settings["main"]).stem + ".pdf")
            tw, th = png_size(thumb)
            items.append({
                "name": d.name, "modified": mtime,
                "thumb": thumb.stat().st_mtime if thumb.exists() else None,
                "thumbW": tw, "thumbH": th,
                "pdf": pdf.stat().st_mtime if pdf.exists() else None,
                "pdfUrl": f"/api/projects/{quote(d.name)}/output/{quote(pdf.name)}" if pdf.exists() else None,
                "drive": syncer.get_status(d.name) if settings["driveSync"] else None,
            })
    items.sort(key=lambda x: -x["modified"])
    return jsonify(items)


def png_size(p: Path):
    """Largura e altura lidas do cabeçalho IHDR do PNG (sem abrir a imagem inteira)."""
    try:
        with open(p, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return None, None


@app.get("/api/projects/<name>/thumbnail")
def get_thumbnail(name):
    f = project_dir(name) / THUMB_FILE
    if not f.exists():
        abort(404)
    resp = send_file(f, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=31536000"  # a URL leva ?v=mtime
    return resp


@app.post("/api/projects/<name>/thumbnail")
def put_thumbnail(name):
    """Miniatura da 1ª página, renderizada pelo navegador (PDF.js) após compilar."""
    d = project_dir(name)
    data = request.get_data()
    if not data.startswith(b"\x89PNG") or len(data) > 2_000_000:
        abort(400, "PNG inválido")
    (d / THUMB_FILE).write_bytes(data)
    return jsonify({"ok": True})


TEMPLATE_META = ".template.json"


@app.get("/api/templates")
def list_templates():
    out = []
    for p in TEMPLATES.iterdir():
        if not p.is_dir():
            continue
        meta = {}
        try:
            meta = json.loads((p / TEMPLATE_META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        out.append({"id": p.name, "name": meta.get("name", p.name), "description": meta.get("description", ""),
                    "order": meta.get("order", 99), "source": meta.get("source")})
    out.sort(key=lambda t: (t["order"], t["name"]))
    return jsonify(out)


@app.post("/api/projects")
def create_project():
    data = json_body()
    name = (data.get("name") or "").strip()
    if not NAME_RE.match(name) or name.startswith("."):
        abort(400, "Nome inválido (use letras, números, espaço, - _ .)")
    d = PROJECTS / name
    if d.exists():
        abort(409, "Já existe um projeto com esse nome")
    tpl = TEMPLATES / (data.get("template") or "blank")
    if tpl.is_dir() and TEMPLATES in tpl.resolve().parents:
        shutil.copytree(tpl, d, ignore=shutil.ignore_patterns(TEMPLATE_META))
    else:
        d.mkdir()
        (d / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nOlá, mundo!\n\\end{document}\n",
                                    encoding="utf-8")
    apply_sync_default(d)
    return jsonify({"name": name})


@app.post("/api/projects/upload")
def upload_project():
    f = request.files.get("file")
    if not f:
        abort(400, "Nenhum arquivo")
    name = (request.form.get("name") or Path(f.filename).stem).strip()
    if not NAME_RE.match(name):
        abort(400, "Nome inválido")
    d = PROJECTS / name
    if d.exists():
        abort(409, "Já existe um projeto com esse nome")
    with zipfile.ZipFile(io.BytesIO(f.read())) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        # se tudo estiver dentro de uma única pasta, remove esse prefixo
        prefix = ""
        tops = {n.split("/")[0] for n in z.namelist()}
        if len(tops) == 1 and all("/" in n for n in names):
            prefix = tops.pop() + "/"
        d.mkdir()
        for n in names:
            rel = n[len(prefix):]
            if not rel or rel.startswith("__MACOSX"):
                continue
            target = safe_path(d, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
    (d / drive_sync.MANIFEST).unlink(missing_ok=True)
    apply_sync_default(d)
    return jsonify({"name": name})


@app.delete("/api/projects/<name>")
def delete_project(name):
    d = project_dir(name)
    shutil.rmtree(d)
    shutil.rmtree(OUTPUT / name, ignore_errors=True)
    syncer.forget(name)  # a cópia no Drive é mantida; pode ser restaurada pelo painel
    return jsonify({"ok": True})


@app.post("/api/projects/<name>/rename")
def rename_project(name):
    d = project_dir(name)
    new = (json_body().get("name") or "").strip()
    if not NAME_RE.match(new) or new.startswith("."):
        abort(400, "Nome inválido")
    if (PROJECTS / new).exists():
        abort(409, "Já existe um projeto com esse nome")
    d.rename(PROJECTS / new)
    if (OUTPUT / name).exists():
        (OUTPUT / name).rename(OUTPUT / new)
    syncer.forget(name)
    changed(new)  # renomeia a pasta no Drive
    return jsonify({"name": new})


@app.post("/api/projects/<name>/clone")
def clone_project(name):
    d = project_dir(name)
    new = (json_body().get("name") or "").strip()
    if not NAME_RE.match(new) or (PROJECTS / new).exists():
        abort(400, "Nome inválido ou já existente")
    shutil.copytree(d, PROJECTS / new)
    # a cópia é um projeto novo: não pode apontar para a mesma pasta do Drive
    (PROJECTS / new / drive_sync.MANIFEST).unlink(missing_ok=True)
    changed(new)
    return jsonify({"name": new})


@app.get("/api/projects/<name>/zip")
def download_zip(name):
    d = project_dir(name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in d.rglob("*"):
            rel = p.relative_to(d)
            if p.is_file() and not any(x.startswith(".") for x in rel.parts):
                z.write(p, rel.as_posix())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"{name}.zip")


@app.get("/api/projects/<name>/settings")
def get_settings(name):
    return jsonify(load_settings(project_dir(name)))


@app.post("/api/projects/<name>/settings")
def set_settings(name):
    d = project_dir(name)
    s = load_settings(d)
    data = json_body()
    for k in ("main", "autoCompile", "shellEscape", "driveSync"):
        if k in data:
            s[k] = data[k]
    if s["main"]:
        safe_path(d, s["main"])
    save_settings(d, s)
    changed(name)
    return jsonify(s)


# ---------------------------------------------------------------- files

@app.get("/api/projects/<name>/files")
def list_files(name):
    return jsonify(tree(project_dir(name)))


@app.get("/api/projects/<name>/file")
def read_file(name):
    d = project_dir(name)
    p = safe_path(d, request.args.get("path"))
    if not p.is_file():
        abort(404, "Arquivo não encontrado")
    if request.args.get("raw"):
        return send_file(p)
    if not is_text(p):
        abort(415, "Arquivo binário")
    return jsonify({"path": request.args["path"], "content": p.read_text(encoding="utf-8", errors="replace"),
                    "mtime": p.stat().st_mtime})


@app.put("/api/projects/<name>/file")
def write_file(name):
    d = project_dir(name)
    data = json_body()
    p = safe_path(d, data.get("path"))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(data.get("content", ""))
    changed(name)
    return jsonify({"ok": True, "mtime": p.stat().st_mtime})


@app.post("/api/projects/<name>/folder")
def make_folder(name):
    d = project_dir(name)
    safe_path(d, json_body().get("path")).mkdir(parents=True, exist_ok=True)
    changed(name)
    return jsonify({"ok": True})


@app.post("/api/projects/<name>/upload")
def upload_files(name):
    d = project_dir(name)
    folder = (request.form.get("folder") or "").strip("/")
    saved = []
    for f in request.files.getlist("files"):
        rel = (folder + "/" if folder else "") + Path(f.filename).name
        p = safe_path(d, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        f.save(p)
        saved.append(rel)
    changed(name)
    return jsonify({"saved": saved})


@app.post("/api/projects/<name>/move")
def move_file(name):
    d = project_dir(name)
    data = json_body()
    src, dst = safe_path(d, data.get("from")), safe_path(d, data.get("to"))
    if not src.exists():
        abort(404, "Origem não existe")
    if dst.exists():
        abort(409, "Destino já existe")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    s = load_settings(d)
    if s.get("main") == data.get("from"):
        s["main"] = data.get("to")
        save_settings(d, s)
    changed(name)
    return jsonify({"ok": True})


@app.delete("/api/projects/<name>/file")
def delete_file(name):
    d = project_dir(name)
    p = safe_path(d, request.args.get("path"))
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    changed(name)
    return jsonify({"ok": True})


@app.get("/api/projects/<name>/meta")
def project_meta(name):
    """Rótulos (\\label) e chaves de citação (.bib) para o autocompletar."""
    d = project_dir(name)
    labels, keys, packages = set(), set(), set()
    for p in d.rglob("*"):
        if any(x.startswith(".") for x in p.relative_to(d).parts) or not p.is_file():
            continue
        if p.suffix == ".tex":
            t = p.read_text(encoding="utf-8", errors="ignore")
            labels.update(re.findall(r"\\label\{([^}]+)\}", t))
            for group in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", t):
                packages.update(x.strip() for x in group.split(","))
        elif p.suffix == ".bib":
            t = p.read_text(encoding="utf-8", errors="ignore")
            keys.update(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", t))
    return jsonify({"labels": sorted(labels), "citeKeys": sorted(keys), "packages": sorted(packages)})


# ---------------------------------------------------------------- compilação

@app.post("/api/projects/<name>/compile")
def compile_project(name):
    d = project_dir(name)
    s = load_settings(d)
    main = (request.get_json(silent=True) or {}).get("main") or s["main"]
    main_path = safe_path(d, main)
    if not main_path.is_file():
        return jsonify({"status": "failure", "message": f"Documento principal '{main}' não encontrado",
                        "entries": [], "log": ""})
    if not TECTONIC.exists():
        return jsonify({"status": "failure", "message": "Tectonic não instalado. Rode setup.ps1.",
                        "entries": [], "log": ""})

    out = OUTPUT / name
    lock = project_lock(name)
    if not lock.acquire(timeout=5):
        return jsonify({"status": "busy", "message": "Já existe uma compilação em andamento", "entries": []})
    try:
        out.mkdir(parents=True, exist_ok=True)
        # \include{pasta/arq} grava pasta/arq.aux na saída: espelha as subpastas
        for sub in d.rglob("*"):
            rel = sub.relative_to(main_path.parent) if main_path.parent in sub.parents else None
            if sub.is_dir() and rel and not any(x.startswith(".") for x in rel.parts):
                (out / rel).mkdir(parents=True, exist_ok=True)
        stem = Path(main).stem
        for ext in (".pdf", ".log", ".synctex.gz"):
            (out / (stem + ext)).unlink(missing_ok=True)
        cmd = [str(TECTONIC), "--keep-logs", "--keep-intermediates", "--synctex",
               "--outdir", str(out), "--chatter", "minimal",
               # gera o PDF mesmo com erros (como -interaction=batchmode)
               "-Zcontinue-on-errors", f"-Zsearch-path={d}"]
        if s.get("shellEscape"):
            # roda os comandos na pasta do documento, como os outros motores
            # (necessário p/ caminhos relativos em \inputminted etc.)
            cmd.append(f"-Zshell-escape-cwd={main_path.parent}")
        cmd.append(main_path.name)
        # com shell-escape o Tectonic grava os intermediários (.aux, .xdv, .pyg…) na pasta
        # do documento; eles são apagados depois para não sujar o projeto (nem o Drive)
        before = snapshot(d) if s.get("shellEscape") else None
        t0 = time.time()
        try:
            # tools/ no PATH para o Tectonic achar o biber (biblatex)
            env = {**os.environ, "PATH": str(TECTONIC.parent) + os.pathsep + os.environ.get("PATH", "")}
            proc = subprocess.run(cmd, cwd=main_path.parent, capture_output=True, timeout=COMPILE_TIMEOUT, env=env,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            stdout = proc.stdout.decode("utf-8", "replace")
            stderr = proc.stderr.decode("utf-8", "replace")
            code = proc.returncode
        except subprocess.TimeoutExpired:
            return jsonify({"status": "timedout", "message": f"Tempo limite de {COMPILE_TIMEOUT}s excedido",
                            "entries": [], "log": ""})
        finally:
            if before is not None:
                remove_created(d, before)
        elapsed = time.time() - t0

        log_file = out / (stem + ".log")
        log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        main_dir_rel = main_path.parent.relative_to(d).as_posix()
        entries = parse_log(log, main_dir_rel if main_dir_rel != "." else "", Path(main).as_posix())
        entries += parse_tectonic_stderr(stderr, entries, main_dir_rel)
        pdf = out / (stem + ".pdf")
        has_pdf = pdf.exists()  # o PDF anterior foi apagado antes de compilar
        has_errors = code != 0 or any(e["level"] == "error" for e in entries)
        status = "failure" if not has_pdf else ("error" if has_errors else "success")
        return jsonify({
            "status": status,
            "pdf": f"/api/projects/{name}/output/{stem}.pdf?t={int(time.time()*1000)}" if has_pdf else None,
            "entries": entries,
            "log": log,
            "stdout": stdout + stderr,
            "time": round(elapsed, 2),
        })
    finally:
        lock.release()


def snapshot(d: Path):
    return {p for p in d.rglob("*")}


INTERMEDIATE_EXT = {".aux", ".bbl", ".bcf", ".blg", ".idx", ".ilg", ".ind", ".log", ".out", ".toc", ".lof",
                    ".lot", ".xdv", ".fls", ".nav", ".snm", ".vrb", ".glo", ".gls", ".ist", ".pyg", ".aex",
                    ".pygtex", ".pygstyle", ".synctex", ".gz", ".xml"}


def remove_created(d: Path, before):
    """Apaga os intermediários do TeX que a compilação criou na pasta do projeto.

    Só mexe no que não existia antes E é intermediário (pela extensão ou por estar numa
    pasta _minted*): um arquivo que o usuário criar durante a compilação fica intacto.
    """
    def is_intermediate(p):
        rel = p.relative_to(d).parts
        return any(x.startswith("_minted") for x in rel) or p.suffix.lower() in INTERMEDIATE_EXT

    created = [p for p in d.rglob("*") if p not in before and is_intermediate(p)]
    for p in sorted(created, key=lambda x: len(x.parts), reverse=True):  # conteúdo antes das pastas
        try:
            if p.is_dir():
                p.rmdir()  # só remove se ficou vazia
            else:
                p.unlink()
        except OSError:
            pass


def parse_tectonic_stderr(stderr, existing, main_dir):
    """Mensagens do próprio Tectonic (rede, arquivos ausentes) que não estão no .log."""
    def norm(msg):
        return msg.strip().rstrip(".")[:30]

    extra = []
    # o stderr repete as mensagens de cada passada; o .log só tem a última
    seen = {(e["line"], norm(e["message"])) for e in existing}
    for line in stderr.splitlines():
        m = re.match(r"^(error|warning): (?:(.+?):(\d+): )?(.*)$", line.strip())
        if not m:
            continue
        level, f, ln, msg = m.groups()
        if f or level == "warning":
            continue  # mensagens do TeX: já vêm do .log
        if re.match(r"(halted on potentially-recoverable error|the TeX engine had an error)", msg) \
                and any(e["level"] == "error" for e in existing):
            continue
        key = (None, norm(msg))
        if key in seen:
            continue
        seen.add(key)
        if re.search(r'shell-escape command "for \^%i in \(pygmentize', msg):
            level = "warning"  # sondagem do minted no Windows; o realce funciona mesmo assim
        extra.append({"level": level, "file": None, "line": None, "message": msg, "content": ""})
    return extra


@app.get("/api/projects/<name>/output/<path:fname>")
def output_file(name, fname):
    project_dir(name)
    out = OUTPUT / name
    p = safe_path(out, fname)
    if not p.is_file():
        abort(404)
    resp = send_file(p)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- synctex

def _synctex(name):
    d = project_dir(name)
    s = load_settings(d)
    stem = Path(s["main"]).stem
    f = OUTPUT / name / (stem + ".synctex.gz")
    if not f.exists():
        abort(404, "SyncTeX indisponível — compile primeiro")
    main_dir = (d / s["main"]).parent
    return SyncTex(f, d, main_dir)


@app.get("/api/projects/<name>/synctex/code")
def synctex_code(name):
    """PDF -> código (clique duplo no PDF)."""
    st = _synctex(name)
    r = st.edit(int(request.args["page"]), float(request.args["x"]), float(request.args["y"]))
    return jsonify(r or {})


@app.get("/api/projects/<name>/synctex/pdf")
def synctex_pdf(name):
    """código -> PDF (ir para a posição no PDF)."""
    st = _synctex(name)
    return jsonify(st.view(request.args["file"], int(request.args["line"])))


# ---------------------------------------------------------------- rotas do Google Drive

def _redirect_uri():
    # o Google aceita loopback (127.0.0.1) em qualquer porta para apps instalados
    return f"http://127.0.0.1:{request.host.split(':')[-1]}/api/drive/callback"


@app.errorhandler(drive_sync.DriveError)
def drive_error(e):
    return jsonify({"error": str(e)}), 502


@app.get("/api/drive/status")
def drive_status():
    s = drive.state()
    try:
        configured = drive.client_config() is not None
    except drive_sync.DriveError:
        configured = False
    return jsonify({"configured": configured, "connected": drive.connected, "user": s.get("user"),
                    "syncAll": bool(s.get("syncAll")), "redirectUri": _redirect_uri()})


@app.get("/api/drive/overview")
def drive_overview():
    names = sorted((d.name for d in PROJECTS.iterdir()
                    if d.is_dir() and not d.name.startswith(".") and drive_enabled(d.name)), key=str.lower)
    ov = syncer.overview(names)
    ov["rootId"] = drive.state().get("rootId")
    return jsonify(ov)


@app.post("/api/drive/sync-now")
def drive_sync_now():
    syncer.mark_all()
    return jsonify({"ok": True})


@app.post("/api/drive/credentials")
def drive_credentials():
    f = request.files.get("file")
    if not f:
        abort(400, "Nenhum arquivo")
    try:
        drive.save_credentials(f.read())
    except (ValueError, drive_sync.DriveError) as e:
        abort(400, str(e))
    return jsonify({"ok": True})


@app.get("/api/drive/connect")
def drive_connect():
    return redirect(drive.auth_url(_redirect_uri()))


@app.get("/api/drive/callback")
def drive_callback():
    if request.args.get("error"):
        return redirect("/?drive=" + quote("Login cancelado: " + request.args["error"]))
    try:
        drive.finish_auth(request.args.get("state", ""), request.args.get("code", ""))
    except drive_sync.DriveError as e:
        return redirect("/?drive=" + quote(str(e)))
    syncer.mark_all()
    return redirect("/?drive=ok")


@app.post("/api/drive/disconnect")
def drive_disconnect():
    drive.disconnect()
    return jsonify({"ok": True})


@app.post("/api/drive/sync-all")
def drive_sync_all():
    """Liga/desliga a sincronização de todos os projetos (e dos novos)."""
    enabled = bool(json_body().get("enabled"))
    s = drive.state()
    s["syncAll"] = enabled
    drive.save_state(s)
    for d in PROJECTS.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            st = load_settings(d)
            st["driveSync"] = enabled
            save_settings(d, st)
            syncer.mark_dirty(d.name, check_only=True)
    return jsonify({"ok": True})


@app.get("/api/drive/remote")
def drive_remote():
    """Pastas de projeto existentes no Drive, marcando as que já existem localmente."""
    root = drive.root_folder()
    local = local_folder_ids()
    items = [{"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime"), "local": local.get(f["id"])}
             for f in drive.list_children(root) if f["mimeType"] == drive_sync.FOLDER_MIME]
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


@app.post("/api/drive/restore")
def drive_restore():
    data = json_body()
    name = (data.get("name") or "").strip()
    if not NAME_RE.match(name) or name.startswith("."):
        abort(400, "Nome inválido")
    if (PROJECTS / name).exists():
        abort(409, "Já existe um projeto local com esse nome; escolha outro")
    n = drive_sync.restore_project(drive, data["id"], PROJECTS / name, data.get("remoteName") or name)
    s = load_settings(PROJECTS / name)
    s["driveSync"] = True
    save_settings(PROJECTS / name, s)
    changed(name)  # se o nome local difere, a pasta no Drive é renomeada
    return jsonify({"name": name, "files": n})


def local_folder_ids():
    """{id da pasta no Drive: nome do projeto local} dos projetos já ligados ao Drive."""
    out = {}
    for d in PROJECTS.iterdir():
        if d.is_dir():
            fid = drive_sync.load_manifest(d).get("folderId")
            if fid:
                out[fid] = d.name
    return out


def free_project_name(remote_name):
    """Nome de projeto local válido e livre para uma pasta vinda do Drive."""
    base = re.sub(r"\s+", " ", re.sub(r"[^\w\-. ]", " ", remote_name)).strip(" .")[:76] or "Projeto"
    name, i = base, 2
    while (PROJECTS / name).exists():
        name, i = f"{base}-{i}", i + 1
    return name


@app.get("/api/drive/import-candidates")
def drive_import_candidates():
    """Projetos no Drive que não existem neste computador e ainda não foram oferecidos."""
    if not drive.connected:
        return jsonify([])
    offered = set(drive.state().get("offered", []))
    local = local_folder_ids()
    items = [{"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime")}
             for f in drive.list_children(drive.root_folder())
             if f["mimeType"] == drive_sync.FOLDER_MIME and f["id"] not in local and f["id"] not in offered]
    return jsonify(sorted(items, key=lambda x: x["name"].lower()))


@app.post("/api/drive/offered")
def drive_offered():
    """Marca projetos do Drive como já oferecidos (importados ou recusados): não pergunta de novo."""
    ids = json_body().get("ids") or []
    s = drive.state()
    s["offered"] = sorted(set(s.get("offered", [])) | set(ids))
    drive.save_state(s)
    return jsonify({"ok": True})


@app.post("/api/drive/import")
def drive_import():
    """Importa um projeto do Drive com um nome local livre e liga a sincronização."""
    data = json_body()
    fid, remote_name = data.get("id"), data.get("name") or "Projeto"
    if fid in local_folder_ids():
        abort(409, "Esse projeto já está neste computador")
    name = free_project_name(remote_name)
    n = drive_sync.restore_project(drive, fid, PROJECTS / name, remote_name)
    s = load_settings(PROJECTS / name)
    s["driveSync"] = True
    save_settings(PROJECTS / name, s)
    changed(name)  # se o nome local precisou mudar, a pasta no Drive acompanha
    st = drive.state()
    st["offered"] = sorted(set(st.get("offered", [])) | {fid})
    drive.save_state(st)
    return jsonify({"name": name, "files": n})


@app.get("/api/projects/<name>/drive")
def project_drive_status(name):
    project_dir(name)
    return jsonify(syncer.get_status(name))


@app.post("/api/projects/<name>/drive/sync")
def project_drive_sync(name):
    project_dir(name)
    changed(name)
    return jsonify(syncer.get_status(name))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(409)
@app.errorhandler(415)
def json_error(e):
    return jsonify({"error": e.description}), e.code


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"Arquivo grande demais (limite de {MAX_UPLOAD_MB} MB por envio)"}), 413


if __name__ == "__main__":
    print(f"\n  TexDesk rodando em {URL}")
    print("  NÃO feche esta janela enquanto estiver usando (pode minimizar).")
    print("  Fechar esta janela desliga o editor e a sincronização com o Google Drive.\n")
    if "--abrir" in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(URL,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
