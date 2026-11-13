# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização de projetos com o Google Drive.

- OAuth 2.0 (app instalado, loopback + PKCE) com escopo drive.file: o app só
  enxerga os arquivos que ele mesmo criou.
- Cada projeto vira uma pasta dentro de "TexDesk" no Drive.
- Um processo em segundo plano sincroniza os projetos "sujos", no máximo a cada
  SYNC_INTERVAL segundos por projeto, nos dois sentidos: antes de enviar o que mudou aqui,
  confere o arquivo de versão no Drive e, se outro computador mexeu no projeto, traz as
  mudanças dele (juntando as dos dois quando o mesmo arquivo mudou dos dois lados).
"""

import base64
import hashlib
import json
import logging
import os
import platform
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .config import TEXT_EXT
from .merge import merge3
from .token_store import TokenStore

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "TexDesk"
MANIFEST = ".drive.json"
# versão do projeto no Drive: muda a cada envio. Comparar só ela (um arquivo pequeno) basta para
# saber se outro computador mexeu no projeto desde a última sincronização
VERSION_FILE = ".version.json"
SYNC_INTERVAL = 5.0
RETRY_INTERVAL = 15.0
UPLOAD_WORKERS = 4  # envios simultâneos por projeto
# arquivos locais que não vão para o Drive
# (o arquivo de versão vai, mas separado: sempre depois dos outros)
EXCLUDE = {MANIFEST, ".thumbnail.png", VERSION_FILE, ".github.json"}  # (.github.json: sincronização do GitHub)
BASE_MAX = 2 * 1024 * 1024  # arquivos de texto maiores que isso não guardam a versão comum

log = logging.getLogger(__name__)


class DriveError(Exception):
    pass


class AuthRequired(DriveError):
    pass


# ---------------------------------------------------------------- cliente HTTP do Drive


class DriveClient:
    def __init__(self, state_dir: Path, token_backend="auto"):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cred_file = self.dir / "credentials.json"
        self.state_file = self.dir / "state.json"
        # o token de acesso fica no cofre de senhas do sistema (ou num arquivo protegido)
        self.tokens = TokenStore(self.dir, token_backend)
        self._lock = threading.Lock()
        self._pending = {}  # state -> (verifier, redirect_uri)
        # pastas cuja existência no Drive já foi confirmada nesta execução do servidor:
        # assim, conferir um projeto sem mudanças não faz nenhuma chamada à API
        self.verified = set()

    # ---- configuração
    def client_config(self):
        if not self.cred_file.exists():
            return None
        data = json.loads(self.cred_file.read_text(encoding="utf-8"))
        cfg = data.get("installed") or data.get("web") or data
        if not cfg.get("client_id") or not cfg.get("client_secret"):
            raise DriveError("credentials.json sem client_id/client_secret")
        return cfg

    def save_credentials(self, raw: bytes):
        data = json.loads(raw.decode("utf-8"))
        cfg = data.get("installed") or data.get("web") or data
        if not cfg.get("client_id") or not cfg.get("client_secret"):
            raise DriveError("Arquivo inválido: esperado o JSON de cliente OAuth baixado do Google Cloud")
        self.cred_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.cred_file, 0o600)  # só o dono lê

    def _token(self):
        return self.tokens.load()

    def _save_token(self, tok):
        self.tokens.save(tok)

    def state(self):
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {}

    def save_state(self, s):
        self.state_file.write_text(json.dumps(s, indent=2), encoding="utf-8")

    @property
    def connected(self):
        t = self._token()
        return bool(t and t.get("refresh_token"))

    def disconnect(self):
        t = self._token()
        if t and t.get("refresh_token"):
            try:  # revoga no Google; ignora falhas de rede
                urllib.request.urlopen(
                    urllib.request.Request(
                        "https://oauth2.googleapis.com/revoke",
                        data=urllib.parse.urlencode({"token": t["refresh_token"]}).encode(),
                    ),
                    timeout=10,
                )
            except (urllib.error.URLError, OSError):
                pass
        self.tokens.delete()
        self.state_file.unlink(missing_ok=True)
        log.info("Google Drive desconectado")

    # ---- OAuth
    def auth_url(self, redirect_uri):
        cfg = self.client_config()
        if not cfg:
            raise DriveError("Configure as credenciais OAuth primeiro")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        self._pending[state] = (verifier, redirect_uri)
        q = {
            "client_id": cfg["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return AUTH_URL + "?" + urllib.parse.urlencode(q)

    def finish_auth(self, state, code):
        if state not in self._pending:
            raise DriveError("Sessão de login expirada; tente conectar de novo")
        verifier, redirect_uri = self._pending.pop(state)
        cfg = self.client_config()
        tok = self._post_form(
            TOKEN_URL,
            {
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if "refresh_token" not in tok:
            raise DriveError(
                "O Google não devolveu refresh_token; remova o acesso do app na sua conta e conecte de novo"
            )
        tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
        self._save_token(tok)
        about = self.request("GET", f"{API}/about", params={"fields": "user(emailAddress,displayName)"})
        s = self.state()
        s["user"] = about.get("user", {})
        self.save_state(s)
        log.info("Google Drive conectado (token guardado em: %s)", self.tokens.location)

    def _post_form(self, url, data):
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise DriveError(f"Falha no login do Google: {e.read().decode('utf-8', 'replace')[:300]}") from e

    def _access_token(self):
        with self._lock:
            tok = self._token()
            if not tok or not tok.get("refresh_token"):
                raise AuthRequired("Google Drive não conectado")
            if time.time() < tok.get("expires_at", 0):
                return tok["access_token"]
            cfg = self.client_config()
            try:
                new = self._post_form(
                    TOKEN_URL,
                    {
                        "client_id": cfg["client_id"],
                        "client_secret": cfg["client_secret"],
                        "refresh_token": tok["refresh_token"],
                        "grant_type": "refresh_token",
                    },
                )
            except DriveError as e:
                if "invalid_grant" in str(e):
                    raise AuthRequired("Acesso ao Drive expirou ou foi revogado; conecte de novo") from e
                raise
            tok.update(access_token=new["access_token"], expires_at=time.time() + new.get("expires_in", 3600) - 60)
            self._save_token(tok)
            return tok["access_token"]

    # ---- chamadas à API
    def request(self, method, url, params=None, json_body=None, data=None, headers=None, raw=False, want_headers=False):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = data
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json; charset=UTF-8"
        for attempt in range(5):
            hdrs["Authorization"] = "Bearer " + self._access_token()
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    if want_headers:
                        return r.headers
                    content = r.read()
                    if raw:
                        return content
                    return json.loads(content) if content else {}
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")
                if e.code == 401 and attempt == 0:
                    with self._lock:  # força renovar o token
                        tok = self._token() or {}
                        tok["expires_at"] = 0
                        self._save_token(tok)
                    continue
                if e.code in (429, 500, 502, 503, 504) or (e.code == 403 and "rateLimit" in msg):
                    time.sleep(min(2**attempt, 16))
                    continue
                raise DriveError(f"Drive {e.code}: {msg[:300]}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise DriveError(f"Sem conexão com o Google Drive ({e})") from e
        raise DriveError("Drive indisponível após várias tentativas")

    @staticmethod
    def _q(s):
        return s.replace("\\", "\\\\").replace("'", "\\'")

    def find_child(self, parent, name, folder=None):
        q = f"name = '{self._q(name)}' and '{parent}' in parents and trashed = false"
        if folder is True:
            q += f" and mimeType = '{FOLDER_MIME}'"
        r = self.request("GET", f"{API}/files", params={"q": q, "fields": "files(id,name,mimeType)", "pageSize": 10})
        files = r.get("files", [])
        return files[0]["id"] if files else None

    def list_children(self, parent):
        out, token = [], None
        while True:
            params = {
                "q": f"'{parent}' in parents and trashed = false",
                "pageSize": 1000,
                "fields": "nextPageToken,files(id,name,mimeType,md5Checksum,modifiedTime,size)",
            }
            if token:
                params["pageToken"] = token
            r = self.request("GET", f"{API}/files", params=params)
            out += r.get("files", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def create_folder(self, name, parent=None):
        meta = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        return self.request("POST", f"{API}/files", params={"fields": "id"}, json_body=meta)["id"]

    def rename(self, file_id, name):
        self.request("PATCH", f"{API}/files/{file_id}", params={"fields": "id"}, json_body={"name": name})

    def trash(self, file_id):
        try:
            self.request("PATCH", f"{API}/files/{file_id}", params={"fields": "id"}, json_body={"trashed": True})
        except DriveError as e:
            if "404" not in str(e):
                raise

    def exists(self, file_id):
        try:
            r = self.request("GET", f"{API}/files/{file_id}", params={"fields": "id,trashed"})
            return not r.get("trashed")
        except DriveError as e:
            if "404" in str(e):
                return False
            raise

    def upload(self, data: bytes, name, parent, file_id=None):
        """Cria ou atualiza um arquivo. Retorna (id, md5)."""
        fields = {"fields": "id,md5Checksum,trashed"}
        if len(data) <= 5 * 1024 * 1024:
            if file_id:
                r = self.request(
                    "PATCH",
                    f"{UPLOAD}/files/{file_id}",
                    params={"uploadType": "media", **fields},
                    data=data,
                    headers={"Content-Type": "application/octet-stream"},
                )
            else:
                boundary = uuid.uuid4().hex
                meta = json.dumps({"name": name, "parents": [parent]}).encode()
                body = (
                    f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                    + meta
                    + f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
                    + data
                    + f"\r\n--{boundary}--".encode()
                )
                r = self.request(
                    "POST",
                    f"{UPLOAD}/files",
                    params={"uploadType": "multipart", **fields},
                    data=body,
                    headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                )
        else:  # upload retomável p/ arquivos grandes
            meta = {} if file_id else {"name": name, "parents": [parent]}
            url = f"{UPLOAD}/files/{file_id}" if file_id else f"{UPLOAD}/files"
            h = self.request(
                "PATCH" if file_id else "POST",
                url,
                params={"uploadType": "resumable"},
                json_body=meta,
                want_headers=True,
            )
            r = self.request("PUT", h["Location"], data=data, headers={"Content-Type": "application/octet-stream"})
            if "md5Checksum" not in r:
                r = self.request("GET", f"{API}/files/{r['id']}", params=fields)
        if r.get("trashed"):
            # o Drive aceita atualizar arquivos na lixeira (ex.: a pasta do projeto foi apagada);
            # trata como "não existe" para o arquivo ser recriado no lugar certo
            raise DriveError("Drive 404: arquivo está na lixeira")
        return r["id"], r.get("md5Checksum")

    def download(self, file_id):
        return self.request("GET", f"{API}/files/{file_id}", params={"alt": "media"}, raw=True)

    def root_folder(self):
        """Pasta 'TexDesk' na raiz do Drive (criada na primeira vez)."""
        s = self.state()
        fid = s.get("rootId")
        if fid and fid in self.verified:
            return fid
        if fid:
            try:
                info = self.request("GET", f"{API}/files/{fid}", params={"fields": "id,name,trashed"})
            except DriveError as e:
                if "404" not in str(e):
                    raise
                info = None
            if info and not info.get("trashed"):
                if info.get("name") != ROOT_FOLDER_NAME:
                    # pasta criada com um nome antigo do app (ex.: "LaTeX Local"): só renomeia
                    self.rename(fid, ROOT_FOLDER_NAME)
                self.verified.add(fid)
                return fid
        fid = self.find_child("root", ROOT_FOLDER_NAME, folder=True) or self.create_folder(ROOT_FOLDER_NAME)
        s["rootId"] = fid
        self.save_state(s)
        self.verified.add(fid)
        return fid


# ---------------------------------------------------------------- sincronização


def md5_file(p: Path):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(d: Path):
    f = d / MANIFEST
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def save_manifest(d: Path, m):
    tmp = d / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / MANIFEST)


def local_files(d: Path):
    """Arquivos do projeto que vão para o Drive (inclui ocultos como .project.json)."""
    out = {}
    for p in d.rglob("*"):
        rel = p.relative_to(d).as_posix()
        if p.is_file() and p.name not in EXCLUDE and not p.name.endswith(".tmp"):
            out[rel] = p
    return out


def sync_project(client: DriveClient, d: Path, name: str, report=None, before_change=None):
    """Sincroniza o projeto com o Drive nos dois sentidos. Retorna nº de operações.

    1. Confere o arquivo de versão (VERSION_FILE) no Drive. Se for o mesmo da última
       sincronização, ninguém mexeu no projeto por lá: só uma leitura pequena.
    2. Se mudou (ou se o projeto ainda não tem versão), compara arquivo por arquivo e traz o
       que mudou no Drive (_pull), juntando as alterações quando os dois lados mexeram.
    3. Envia o que mudou aqui (_push) e, por último, uma versão nova: quem a vir já encontra
       todos os arquivos no Drive.

    report recebe "received" (arquivos alterados aqui pelo que veio do Drive), "conflicts"
    (trechos alterados dos dois lados) e "computer" (de onde veio a última versão).
    before_change(d, important) é chamado antes de alterar arquivos locais (para guardar uma
    versão no histórico); important indica que algo daqui vai ser juntado ou substituído.
    """
    report = {} if report is None else report
    report.setdefault("received", [])
    report.setdefault("conflicts", [])
    m = load_manifest(d)
    ops = 0
    root = client.root_folder()  # sem custo depois da 1ª vez em cada execução

    folder = m.get("folderId")
    if folder and folder not in client.verified:
        if client.exists(folder):
            client.verified.add(folder)
        else:  # apagada no Drive: recria do zero
            folder, m = None, {}
    created = False
    if not folder:
        m = {"folderName": name, "files": {}, "folders": {}}
        # já existe uma pasta com esse nome no Drive (ex.: outro computador)? Então ela é
        # comparada arquivo por arquivo com a local (_pull), em vez de tudo ir como cópia
        folder = client.find_child(root, name, folder=True)
        if not folder:
            folder = client.create_folder(name, root)
            created = True
        client.verified.add(folder)
        m["folderId"] = folder
        ops += 1
    elif m.get("folderName") != name:  # projeto renomeado localmente
        client.rename(folder, name)
        m["folderName"] = name
        ops += 1
    m.setdefault("files", {})
    m.setdefault("folders", {})

    try:
        for attempt in range(3):
            ver = None
            skip = set()
            if not created:
                ver, vid = _remote_version(client, folder, m)
                if vid:
                    m["versionId"] = vid
                if ver is None or ver["rev"] != m.get("rev"):
                    skip, n = _pull(client, d, m, folder, report, before_change)
                    ops += n
                    if ver:
                        report["computer"] = ver.get("computer")
                    # um arquivo alterado aqui durante a conferência fica para a próxima, que
                    # então compara tudo de novo
                    m["rev"] = ver["rev"] if ver and not skip else None
                    save_manifest(d, m)
            sent = _push(client, d, m, folder, skip)
            ops += sent
            if not sent and m.get("rev") is not None:
                local = read_version(d)
                if ver and (local is None or local.get("rev") != ver["rev"]):
                    _write_atomic(d / VERSION_FILE, _version_bytes(ver))
                break
            # antes de publicar a versão nova, confere se outro computador não publicou uma
            # enquanto isso; se publicou, traz as mudanças dele primeiro
            if not created and attempt < 2:
                again, _ = _remote_version(client, folder, m)
                if (again or {}).get("rev") != (ver or {}).get("rev"):
                    m["rev"] = (ver or {}).get("rev")
                    continue
            new = {
                "version": max(_num(ver), _num(read_version(d))) + 1,
                "rev": uuid.uuid4().hex,
                "updated": time.time(),
                "computer": platform.node(),
            }
            data = _version_bytes(new)
            _write_atomic(d / VERSION_FILE, data)
            try:
                fid, _ = client.upload(data, VERSION_FILE, folder, m.get("versionId"))
            except DriveError as e:
                if not (m.get("versionId") and "404" in str(e)):
                    raise
                fid, _ = client.upload(data, VERSION_FILE, folder, None)
            m["versionId"] = fid
            m["rev"] = None if skip else new["rev"]
            ops += 1
            break
        m["lastSync"] = time.time()
        _prune_base(client, folder, m)
    except DriveError as e:
        if "404" in str(e):
            # alguma pasta sumiu do Drive: na próxima tentativa, confere tudo de novo
            client.verified.discard(folder)
            m["folders"] = {}
        raise
    finally:
        save_manifest(d, m)
    return ops


def _push(client: DriveClient, d: Path, m: dict, folder: str, skip=()):
    """Envia o estado local para o Drive (só o que mudou). skip: arquivos que ficam para depois."""
    ops = 0

    def ensure_dir(rel_dir):
        if not rel_dir:
            return folder
        if rel_dir in m["folders"]:
            return m["folders"][rel_dir]
        parent = ensure_dir(rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else "")
        base = rel_dir.rsplit("/", 1)[-1]
        fid = client.find_child(parent, base, folder=True) or client.create_folder(base, parent)
        m["folders"][rel_dir] = fid
        return fid

    all_files = local_files(d)
    files = {rel: p for rel, p in all_files.items() if rel not in skip}

    # 1) descobre o que mudou (barato: mtime/tamanho, e md5 só se precisar)
    todo = []
    for rel, p in sorted(files.items()):
        st = p.stat()
        entry = m["files"].get(rel)
        if entry and entry.get("mtime") == st.st_mtime and entry.get("size") == st.st_size:
            continue  # inalterado desde a última sincronização
        digest = md5_file(p)
        if entry and entry.get("md5") == digest:
            entry.update(mtime=st.st_mtime, size=st.st_size)
            continue
        todo.append((rel, p, st, digest, entry))

    # 2) pastas em sequência (criá-las em paralelo geraria duplicatas no Drive)
    parents = {rel: ensure_dir(rel.rsplit("/", 1)[0] if "/" in rel else "") for rel, *_ in todo}

    # 3) envios em paralelo; o manifesto é salvo a cada arquivo concluído,
    #    então uma falha no meio não reenvia o que já foi
    lock = threading.Lock()

    def send(item):
        rel, p, st, digest, entry = item
        data = p.read_bytes()
        try:
            fid, remote_md5 = client.upload(data, p.name, parents[rel], entry["id"] if entry else None)
        except DriveError as e:
            if not (entry and "404" in str(e)):
                raise
            # o arquivo foi apagado direto no Drive: envia de novo como arquivo novo
            fid, remote_md5 = client.upload(data, p.name, parents[rel], None)
        md5 = remote_md5 or digest
        _save_base(client, folder, md5, data, rel)
        with lock:
            m["files"][rel] = {"id": fid, "md5": md5, "mtime": st.st_mtime, "size": st.st_size}
            save_manifest(d, m)

    if todo:
        with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(todo))) as pool:
            for fut in [pool.submit(send, it) for it in todo]:
                fut.result()  # propaga o primeiro erro, depois de os outros terminarem
        ops += len(todo)

    # removidos localmente -> lixeira do Drive (recuperável por 30 dias)
    for rel in [r for r in m["files"] if r not in all_files and r not in skip]:
        client.trash(m["files"].pop(rel)["id"])
        ops += 1
    local_dirs = {str(Path(r).parent.as_posix()) for r in all_files}
    local_dirs = {x for r in local_dirs for x in _parents(r)}
    for rel in sorted([r for r in m["folders"] if r not in local_dirs], key=len, reverse=True):
        client.trash(m["folders"].pop(rel))
        ops += 1
    return ops


def _pull(client: DriveClient, d: Path, m: dict, folder: str, report: dict, before_change=None):
    """Traz para cá o que mudou no Drive desde a última sincronização.

    Compara cada arquivo do Drive com o manifesto (como estava na última sincronização) e com
    o arquivo local:
    - só o Drive mudou: baixa (inclusive arquivos novos e apagados lá);
    - só aqui mudou: nada a fazer agora, o envio cuida;
    - os dois mudaram: arquivos de texto são juntados (merge3); os outros, ou quando não há a
      versão comum guardada (projetos de versões anteriores), fica o modificado por último.
      Um arquivo editado aqui e apagado no Drive (ou o contrário) não é apagado: a edição vence.

    Devolve (arquivos que mudaram aqui durante a conferência e ficam para a próxima, nº de
    arquivos alterados).
    """
    remote, rfolders = remote_tree(client, folder)
    ver = remote.pop(VERSION_FILE, None)
    if ver:
        m["versionId"] = ver["id"]
    files = local_files(d)
    plan = []  # (ação, caminho, arquivo no Drive, (mtime, tamanho) local observado)
    important = False
    for rel in sorted(set(remote) | set(m["files"]) | set(files)):
        r, e, lp = remote.get(rel), m["files"].get(rel), files.get(rel)
        if r is None and e is None:
            continue  # só existe aqui: o envio cuida
        base = e.get("md5") if e else None
        rmd5 = r.get("md5") if r else None
        if r is not None and (rmd5 is None or rmd5 == base):
            continue  # não mudou no Drive
        st = lp.stat() if lp else None
        seen = (st.st_mtime, st.st_size) if st else None
        if st is None:
            lmd5 = None
        elif e and e.get("mtime") == st.st_mtime and e.get("size") == st.st_size:
            lmd5 = base
        else:
            lmd5 = md5_file(lp)
        if r is None:  # apagado no Drive
            if lmd5 is None:
                plan.append(("forget", rel, None, seen))
            elif lmd5 == base:
                plan.append(("delete", rel, None, seen))
            else:  # editado aqui: fica, e vai de novo para o Drive como arquivo novo
                plan.append(("forget", rel, None, seen))
            continue
        if lmd5 == rmd5:
            plan.append(("adopt", rel, r, seen))
        elif lmd5 is None or lmd5 == base:
            plan.append(("download", rel, r, seen))
        else:  # os dois lados mudaram
            important = True
            base_data = _load_base(client, folder, base) if base else None
            if base_data is not None and _is_text_name(rel):
                plan.append(("merge", rel, dict(r, base=base_data), seen))
            elif (r.get("modified") or 0) > st.st_mtime:
                plan.append(("download", rel, r, seen))
            else:
                plan.append(("keep", rel, r, seen))

    # baixa tudo antes de mexer em qualquer arquivo local
    need = [r["id"] for act, _, r, _ in plan if act in ("download", "merge")]
    data = {}
    if need:
        with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(need))) as pool:
            for fid, content in zip(need, pool.map(client.download, need), strict=True):
                data[fid] = content

    if before_change and any(act in ("download", "merge", "delete") for act, *_ in plan):
        before_change(d, important)

    skip, changed = set(), 0
    for act, rel, r, seen in plan:
        p = d / rel
        try:
            st = p.stat()
            now = (st.st_mtime, st.st_size)
        except OSError:
            now = None
        if now != seen:  # o arquivo mudou aqui enquanto o Drive era consultado
            skip.add(rel)
            continue
        if act == "forget":
            m["files"].pop(rel, None)
        elif act == "delete":
            p.unlink(missing_ok=True)
            _remove_empty_dirs(d, p.parent)
            m["files"].pop(rel, None)
            report["received"].append(rel)
            changed += 1
        elif act == "adopt":
            m["files"][rel] = {"id": r["id"], "md5": r["md5"], "mtime": now[0], "size": now[1]}
            _save_base(client, folder, r["md5"], p.read_bytes(), rel)
        elif act == "keep":  # fica o daqui: o envio o grava por cima do que está no Drive
            m["files"][rel] = {"id": r["id"], "md5": r["md5"]}
        elif act == "download":
            _write_atomic(p, data[r["id"]])
            st = p.stat()
            m["files"][rel] = {"id": r["id"], "md5": r["md5"], "mtime": st.st_mtime, "size": st.st_size}
            _save_base(client, folder, r["md5"], data[r["id"]], rel)
            report["received"].append(rel)
            changed += 1
        elif act == "merge":
            theirs_b, mine_b = data[r["id"]], p.read_bytes()
            _save_base(client, folder, r["md5"], theirs_b, rel)
            try:
                base_t, mine, theirs = (x.decode("utf-8") for x in (r["base"], mine_b, theirs_b))
            except UnicodeDecodeError:  # não é texto: fica o modificado por último
                if (r.get("modified") or 0) > seen[0]:
                    _write_atomic(p, theirs_b)
                    report["received"].append(rel)
                    changed += 1
                    st = p.stat()
                    m["files"][rel] = {"id": r["id"], "md5": r["md5"], "mtime": st.st_mtime, "size": st.st_size}
                else:
                    m["files"][rel] = {"id": r["id"], "md5": r["md5"]}
                continue
            merged, conflicts = merge3(base_t, mine, theirs)
            if merged != mine:
                _write_atomic(p, merged.encode("utf-8"))
                report["received"].append(rel)
                changed += 1
            if merged == theirs:
                st = p.stat()
                m["files"][rel] = {"id": r["id"], "md5": r["md5"], "mtime": st.st_mtime, "size": st.st_size}
            else:  # o resultado da junção vai para o Drive no envio
                m["files"][rel] = {"id": r["id"], "md5": r["md5"]}
            report["conflicts"] += [dict(c, path=rel) for c in conflicts]

    # subpastas do Drive que agora têm arquivos aqui (para o envio não criá-las de novo)
    dirs = {x for rel in m["files"] for x in _parents(Path(rel).parent.as_posix())}
    m["folders"].update({k: v for k, v in rfolders.items() if k in dirs})
    return skip, changed


def _parents(rel_dir):
    if rel_dir in ("", "."):
        return []
    parts = rel_dir.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _remove_empty_dirs(d: Path, p: Path):
    while p != d and d in p.parents:
        try:
            p.rmdir()  # só apaga pasta vazia
        except OSError:
            return
        p = p.parent


def _write_atomic(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)


# ---------------------------------------------------------------- arquivo de versão


def _version_bytes(v: dict):
    return json.dumps(v, indent=1, ensure_ascii=False).encode("utf-8")


def _parse_version(data: bytes):
    try:
        v = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return v if isinstance(v, dict) and isinstance(v.get("rev"), str) and v["rev"] else None


def _num(v):
    try:
        return max(0, int((v or {}).get("version", 0)))
    except (TypeError, ValueError):
        return 0


def read_version(d: Path):
    """Arquivo de versão local do projeto ({version, rev, updated, computer}) ou None."""
    try:
        return _parse_version((d / VERSION_FILE).read_bytes())
    except OSError:
        return None


def _remote_version(client: DriveClient, folder: str, m: dict):
    """Arquivo de versão do projeto no Drive: (conteúdo ou None, id ou None). Uma leitura só."""
    vid = m.get("versionId")
    if vid:
        try:
            return _parse_version(client.download(vid)), vid
        except DriveError as e:
            if "404" not in str(e):
                raise
    vid = client.find_child(folder, VERSION_FILE, folder=False)
    if not vid:
        return None, None
    return _parse_version(client.download(vid)), vid


# ---------------------------------------------------------------- versão comum (base da junção)
# Cópia de cada arquivo de texto como estava na última sincronização, guardada fora do
# projeto (no estado do Drive, por pasta do Drive e md5). É a partir dela que merge3 sabe o
# que cada lado mudou.


def _base_dir(client, folder):
    root = getattr(client, "dir", None)
    return Path(root) / "base" / folder if root and folder else None


def _is_text_name(rel):
    suffix = Path(rel).suffix.lower()
    return suffix in TEXT_EXT or suffix == ""


def _save_base(client, folder, md5, data: bytes, rel):
    bd = _base_dir(client, folder)
    if not bd or not md5 or len(data) > BASE_MAX or not _is_text_name(rel):
        return
    p = bd / md5
    if p.exists():
        return
    bd.mkdir(parents=True, exist_ok=True)
    _write_atomic(p, data)


def _load_base(client, folder, md5):
    bd = _base_dir(client, folder)
    try:
        return (bd / md5).read_bytes() if bd else None
    except OSError:
        return None


def _prune_base(client, folder, m):
    """Apaga as cópias que nenhum arquivo do manifesto usa mais."""
    bd = _base_dir(client, folder)
    if not bd or not bd.is_dir():
        return
    keep = {e.get("md5") for e in m["files"].values()}
    for p in bd.iterdir():
        if p.name not in keep:
            p.unlink(missing_ok=True)


def _safe_name(name):
    """Nome de arquivo/pasta do Drive que pode ser gravado com segurança dentro do projeto."""
    return (
        bool(name) and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|\0') and name == name.strip()
    )


def _parse_time(s):
    """Data do Drive (RFC 3339, ex.: 2026-11-04T13:37:00.000Z) em segundos desde 1970."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def remote_tree(client: DriveClient, folder_id: str):
    """Arquivos e subpastas de uma pasta do Drive: ({caminho: {id, md5, modified}}, {caminho: id})."""
    files, folders = {}, {}

    def walk(fid, rel):
        for f in client.list_children(fid):
            if not _safe_name(f["name"]):
                continue  # nome que não pode virar arquivo local (ex.: "..", "a/b", "C:x")
            child = f"{rel}/{f['name']}" if rel else f["name"]
            if child in files or child in folders:
                continue  # nomes repetidos no Drive: fica o primeiro
            if f["mimeType"] == FOLDER_MIME:
                folders[child] = f["id"]
                walk(f["id"], child)
            elif not f["mimeType"].startswith("application/vnd.google-apps"):
                # (documentos nativos do Google não são arquivos binários)
                files[child] = {
                    "id": f["id"],
                    "md5": f.get("md5Checksum"),
                    "modified": _parse_time(f.get("modifiedTime")),
                }

    walk(folder_id, "")
    return files, folders


def restore_project(client: DriveClient, folder_id: str, dest: Path, remote_name: str, progress=None):
    """Baixa uma pasta de projeto do Drive para dest e grava o manifesto.

    Se o nome local for diferente, a próxima sincronização renomeia a pasta no Drive.
    progress(baixados, total) é chamado a cada arquivo, para mostrar o andamento.
    """
    files, folders = remote_tree(client, folder_id)
    ver = files.pop(VERSION_FILE, None)  # baixado à parte, por último: não conta como arquivo
    if progress:
        progress(0, len(files))
    dest.mkdir(parents=True)
    m = {"folderId": folder_id, "folderName": remote_name, "files": {}, "folders": folders}
    lock = threading.Lock()

    def fetch(item):
        # o nome de cada parte do caminho já foi validado em remote_tree (_safe_name), então
        # dest / rel fica dentro de dest. (Não usar resolve() aqui: com outra thread criando
        # a mesma pasta ao mesmo tempo, no Windows ele dá resultados inconsistentes.)
        rel, info = item
        target = dest / rel
        data = client.download(info["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        st = target.stat()
        _save_base(client, folder_id, info["md5"], data, rel)
        with lock:
            m["files"][rel] = {"id": info["id"], "md5": info["md5"], "mtime": st.st_mtime, "size": st.st_size}
            if progress:
                progress(len(m["files"]), len(files))

    try:
        if files:
            with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(files))) as pool:
                for fut in [pool.submit(fetch, it) for it in files.items()]:
                    fut.result()
        if ver:
            data = client.download(ver["id"])
            (dest / VERSION_FILE).write_bytes(data)
            m["versionId"] = ver["id"]
            m["rev"] = (_parse_version(data) or {}).get("rev")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)  # importação pela metade não vira projeto
        raise
    save_manifest(dest, m)
    return len(m["files"])


IMPORT_PREFIX = ".importando-"  # pasta oculta onde um projeto é baixado antes de aparecer


class ImportQueue:
    """Importação de projetos do Drive em segundo plano, um de cada vez.

    Cada projeto é baixado numa pasta oculta e só vira projeto quando chega inteiro. Enquanto
    isso, o nome fica reservado e o painel mostra o andamento (items()). Uma importação que
    falha fica na lista, com o erro, até ser repetida ou descartada.
    """

    def __init__(
        self, client, projects_dir: Path, on_done, restore=None, source="drive", prefix=IMPORT_PREFIX, expected=None
    ):
        self.client = client
        self.projects = projects_dir
        self.on_done = on_done  # função(nome, id da pasta no Drive), depois de importar
        # a mesma fila serve ao GitHub: restore(cliente, id, destino, nome remoto, andamento)
        self.restore = restore or restore_project
        self.source = source  # "drive" ou "github", para o painel
        self.prefix = prefix
        self.expected = expected or (DriveError,)  # erros de rede/serviço (sem rastro no log)
        self.jobs = {}  # nome local -> {id, remote, state (queued|importing|error), done, total, error, added}
        self.lock = threading.Lock()
        self.thread = None  # existe enquanto há importação na fila
        for d in projects_dir.glob(prefix + "*"):  # importação interrompida (servidor fechado)
            shutil.rmtree(d, ignore_errors=True)

    def reserved(self):
        with self.lock:
            return set(self.jobs)

    def importing_ids(self):
        with self.lock:
            return {j["id"] for j in self.jobs.values()}

    def add(self, name, folder_id, remote_name):
        with self.lock:
            self.jobs[name] = {
                "id": folder_id,
                "remote": remote_name,
                "state": "queued",
                "done": 0,
                "total": None,
                "error": None,
                "added": time.time(),
            }
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name="drive-import")
                self.thread.start()

    def retry(self, name):
        with self.lock:
            job = self.jobs.get(name)
            if not job or job["state"] != "error":
                return False
            self.jobs.pop(name)
        self.add(name, job["id"], job["remote"])
        return True

    def dismiss(self, name):
        with self.lock:
            job = self.jobs.get(name)
            if job and job["state"] == "error":
                self.jobs.pop(name)
                return True
        return False

    def items(self):
        with self.lock:
            return [dict(j, name=n, source=self.source) for n, j in self.jobs.items()]

    def _next(self):
        with self.lock:
            for name, job in self.jobs.items():
                if job["state"] == "queued":
                    job["state"] = "importing"
                    return name, dict(job)
            self.thread = None  # sai da fila vazia; o próximo add() abre outra thread
        return None, None

    def _run(self):
        while True:
            name, job = self._next()
            if not name:
                return

            def progress(done, total, name=name):
                with self.lock:
                    self.jobs[name].update(done=done, total=total)

            tmp = self.projects / (self.prefix + name)
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                self.restore(self.client, job["id"], tmp, job["remote"], progress)
                final = name
                if (self.projects / final).exists():  # alguém criou um projeto com esse nome no meio
                    i = 2
                    while (self.projects / f"{name}-{i}").exists():
                        i += 1
                    final = f"{name}-{i}"
                tmp.rename(self.projects / final)
                self.on_done(final, job["id"])
                log.info("%s: %s importado", self.source, final)
                with self.lock:
                    self.jobs.pop(name, None)
            except Exception as e:
                shutil.rmtree(tmp, ignore_errors=True)
                if isinstance(e, self.expected):
                    log.warning("%s: falha ao importar %s: %s", self.source, name, e)
                else:
                    log.exception("%s: erro inesperado ao importar %s", self.source, name)
                with self.lock:
                    self.jobs[name].update(state="error", error=str(e) or e.__class__.__name__)


class SyncManager:
    """Fila de projetos alterados + worker que sincroniza a cada SYNC_INTERVAL."""

    def __init__(self, client: DriveClient, projects_dir: Path, is_enabled, before_change=None, after_change=None):
        self.client = client
        self.projects = projects_dir
        self.is_enabled = is_enabled  # função(nome) -> bool
        # before_change(pasta, nome, important): antes de alterar arquivos com o que veio do Drive
        # after_change(nome): depois de alterar
        self.before_change = before_change
        self.after_change = after_change
        self.dirty = {}  # nome -> instante da última alteração pendente
        self.status = {}  # nome -> dict
        self.next_allowed = {}  # nome -> instante mínimo do próximo envio
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.stopped = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="drive-sync")
        self.thread.start()

    def stop(self, timeout=60):
        """Para o worker depois do envio em andamento (antes de reiniciar o servidor)."""
        with self.cv:
            self.stopped = True
            self.cv.notify()
        self.thread.join(timeout)

    def mark_dirty(self, name, check_only=False, urgent=False):
        """check_only: só conferir (ex.: ao iniciar o servidor). Não aparece como
        pendente no painel e fica atrás das alterações reais na fila.

        urgent: conferir agora, na frente da fila e sem esperar o intervalo mínimo (o projeto
        aberto no editor). Sem isso, ao iniciar o servidor o projeto aberto esperaria todos os
        outros serem conferidos."""
        if not self.client.connected or not self.is_enabled(name):
            return
        with self.cv:
            if urgent:
                self.dirty[name] = time.time()
                self.next_allowed.pop(name, None)
            elif check_only:
                self.dirty.setdefault(name, 0)
            else:
                self.dirty[name] = time.time()
                self.status.setdefault(name, {})["pending"] = True
            self.cv.notify()

    def mark_all(self):
        for d in self.projects.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                self.mark_dirty(d.name, check_only=True)

    def forget(self, name):
        with self.lock:
            self.dirty.pop(name, None)
            self.status.pop(name, None)

    def pop_conflict(self, name, cid):
        """Tira um conflito da lista (o usuário já escolheu) e o devolve, ou None."""
        with self.lock:
            items = self.status.get(name, {}).get("conflicts", [])
            for c in items:
                if c["id"] == cid:
                    items.remove(c)
                    return c
        return None

    def overview(self, names):
        """Resumo para o painel: contagens e estado de cada projeto sincronizado."""
        items = []
        for n in names:
            st = self.get_status(n)
            st["name"] = n
            items.append(st)
        counts = {"total": len(items), "synced": 0, "pending": 0, "error": 0}
        for st in items:
            if st.get("state") == "error":
                counts["error"] += 1
            elif st.get("pending") or st.get("state") == "syncing" or not st.get("lastSync"):
                counts["pending"] += 1
            else:
                counts["synced"] += 1
        return {"counts": counts, "projects": items}

    def get_status(self, name):
        with self.lock:
            st = dict(self.status.get(name, {}))
            st["conflicts"] = list(st.get("conflicts", []))
        st["enabled"] = self.is_enabled(name)
        st["connected"] = self.client.connected
        st.setdefault("state", "idle")
        if "lastSync" not in st:  # após reiniciar o servidor: lê do manifesto uma vez só
            st["lastSync"] = load_manifest(self.projects / name).get("lastSync")
            with self.lock:
                self.status.setdefault(name, {}).setdefault("lastSync", st["lastSync"])
        return st

    def _run(self):
        while True:
            with self.cv:
                if self.stopped:
                    return
                now = time.time()
                ready = [n for n in self.dirty if now >= self.next_allowed.get(n, 0)]
                if not ready:
                    waits = [self.next_allowed.get(n, now) - now for n in self.dirty]
                    self.cv.wait(timeout=max(0.2, min(waits)) if waits else None)
                    continue
                # o projeto alterado por último primeiro: quem está editando não espera a fila
                # (o intervalo mínimo por projeto deixa os outros andarem entre um envio e outro)
                name = max(ready, key=self.dirty.get)
                self.dirty.pop(name)
                self.status.setdefault(name, {}).update(state="syncing", pending=False)
            d = self.projects / name
            report = {}
            try:
                if not d.is_dir() or not self.is_enabled(name):
                    raise _Skip()

                def before(pasta, important, name=name):
                    if self.before_change:
                        self.before_change(pasta, name, important)

                ops = sync_project(self.client, d, name, report=report, before_change=before)
                if ops:
                    log.info("Drive: %s sincronizado (%d operações)", name, ops)
                upd = {"state": "synced", "lastSync": time.time(), "error": None, "lastOps": ops}
                delay = SYNC_INTERVAL
            except _Skip:
                upd, delay = {"state": "idle"}, 0
            except AuthRequired as e:
                log.warning("Drive: %s não sincronizado: %s", name, e)
                upd, delay = {"state": "error", "error": str(e)}, RETRY_INTERVAL
            except Exception as e:  # rede, cota etc.: tenta de novo depois
                if isinstance(e, DriveError):
                    log.warning("Drive: falha ao sincronizar %s (nova tentativa em %ds): %s", name, RETRY_INTERVAL, e)
                else:  # erro inesperado (bug): com o rastro completo
                    log.exception("Drive: erro inesperado ao sincronizar %s", name)
                upd, delay = {"state": "error", "error": str(e)}, RETRY_INTERVAL
                with self.cv:
                    self.dirty.setdefault(name, time.time())
            received, conflicts = report.get("received"), report.get("conflicts")
            if received:
                log.info("Drive: %s recebeu do Drive: %s", name, ", ".join(received))
                upd["received"] = {"at": time.time(), "files": received, "computer": report.get("computer")}
            if (received or conflicts) and self.after_change:
                self.after_change(name)
            upd["checkedAt"] = time.time()  # fim da tentativa, com ou sem erro
            with self.cv:
                st = self.status.setdefault(name, {})
                st.update(upd)
                if conflicts:
                    now = time.time()
                    st.setdefault("conflicts", []).extend(dict(c, id=uuid.uuid4().hex[:12], at=now) for c in conflicts)
                st["pending"] = name in self.dirty
                self.next_allowed[name] = time.time() + delay


class _Skip(Exception):
    pass
