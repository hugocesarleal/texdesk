# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização de projetos com o Google Drive.

- OAuth 2.0 (app instalado, loopback + PKCE) com escopo drive.file: o app só
  enxerga os arquivos que ele mesmo criou.
- Cada projeto vira uma pasta dentro de "TexDesk" no Drive.
- Um processo em segundo plano envia as alterações de projetos "sujos",
  no máximo a cada SYNC_INTERVAL segundos por projeto, só com o que mudou.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .token_store import TokenStore

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "TexDesk"
MANIFEST = ".drive.json"
SYNC_INTERVAL = 5.0
RETRY_INTERVAL = 15.0
UPLOAD_WORKERS = 4  # envios simultâneos por projeto
# arquivos locais que não vão para o Drive
EXCLUDE = {MANIFEST, ".thumbnail.png"}

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


def sync_project(client: DriveClient, d: Path, name: str):
    """Envia o estado local do projeto para o Drive. Retorna nº de operações."""
    m = load_manifest(d)
    ops = 0
    root = client.root_folder()  # sem custo depois da 1ª vez em cada execução

    folder = m.get("folderId")
    if folder and folder not in client.verified:
        if client.exists(folder):
            client.verified.add(folder)
        else:  # apagada no Drive: recria do zero
            folder, m = None, {}
    if not folder:
        m = {"folderName": name, "files": {}, "folders": {}}
        folder = client.find_child(root, name, folder=True)
        if folder:
            # já existe uma pasta com esse nome no Drive (ex.: outro computador): em vez de
            # reenviar tudo como cópia, registra os arquivos que já estão lá pelo caminho.
            # Os de mesmo conteúdo não são reenviados; os diferentes são atualizados no lugar
            # (a versão anterior fica no histórico do Drive); os que só existem no Drive
            # ficam intactos, porque não entram no manifesto.
            remote, _ = remote_tree(client, folder)
            local = local_files(d)
            m["files"] = {rel: info for rel, info in remote.items() if rel in local}
        else:
            folder = client.create_folder(name, root)
        client.verified.add(folder)
        m["folderId"] = folder
        ops += 1
    elif m.get("folderName") != name:  # projeto renomeado localmente
        client.rename(folder, name)
        m["folderName"] = name
        ops += 1
    m.setdefault("files", {})
    m.setdefault("folders", {})

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

    files = local_files(d)
    try:
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
            with lock:
                m["files"][rel] = {"id": fid, "md5": remote_md5 or digest, "mtime": st.st_mtime, "size": st.st_size}
                save_manifest(d, m)

        if todo:
            with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(todo))) as pool:
                for fut in [pool.submit(send, it) for it in todo]:
                    fut.result()  # propaga o primeiro erro, depois de os outros terminarem
            ops += len(todo)

        # removidos localmente -> lixeira do Drive (recuperável por 30 dias)
        for rel in [r for r in m["files"] if r not in files]:
            client.trash(m["files"].pop(rel)["id"])
            ops += 1
        local_dirs = {str(Path(r).parent.as_posix()) for r in files}
        local_dirs = {x for r in local_dirs for x in _parents(r)}
        for rel in sorted([r for r in m["folders"] if r not in local_dirs], key=len, reverse=True):
            client.trash(m["folders"].pop(rel))
            ops += 1
        m["lastSync"] = time.time()
    except DriveError as e:
        if "404" in str(e):
            # alguma pasta sumiu do Drive: na próxima tentativa, confere tudo de novo
            client.verified.discard(folder)
            m["folders"] = {}
        raise
    finally:
        save_manifest(d, m)
    return ops


def _parents(rel_dir):
    if rel_dir in ("", "."):
        return []
    parts = rel_dir.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _safe_name(name):
    """Nome de arquivo/pasta do Drive que pode ser gravado com segurança dentro do projeto."""
    return (
        bool(name) and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|\0') and name == name.strip()
    )


def remote_tree(client: DriveClient, folder_id: str):
    """Arquivos e subpastas de uma pasta do Drive: ({caminho: {id, md5}}, {caminho: id})."""
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
                files[child] = {"id": f["id"], "md5": f.get("md5Checksum")}

    walk(folder_id, "")
    return files, folders


def restore_project(client: DriveClient, folder_id: str, dest: Path, remote_name: str):
    """Baixa uma pasta de projeto do Drive para dest e grava o manifesto.

    Se o nome local for diferente, a próxima sincronização renomeia a pasta no Drive.
    """
    files, folders = remote_tree(client, folder_id)
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
        with lock:
            m["files"][rel] = {"id": info["id"], "md5": info["md5"], "mtime": st.st_mtime, "size": st.st_size}

    try:
        if files:
            with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(files))) as pool:
                for fut in [pool.submit(fetch, it) for it in files.items()]:
                    fut.result()
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)  # importação pela metade não vira projeto
        raise
    save_manifest(dest, m)
    return len(m["files"])


class SyncManager:
    """Fila de projetos alterados + worker que sincroniza a cada SYNC_INTERVAL."""

    def __init__(self, client: DriveClient, projects_dir: Path, is_enabled):
        self.client = client
        self.projects = projects_dir
        self.is_enabled = is_enabled  # função(nome) -> bool
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

    def mark_dirty(self, name, check_only=False):
        """check_only: só conferir (ex.: ao iniciar o servidor). Não aparece como
        pendente no painel e fica atrás das alterações reais na fila."""
        if not self.client.connected or not self.is_enabled(name):
            return
        with self.cv:
            if check_only:
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
            try:
                if not d.is_dir() or not self.is_enabled(name):
                    raise _Skip()
                ops = sync_project(self.client, d, name)
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
            with self.cv:
                self.status.setdefault(name, {}).update(upd)
                self.status[name]["pending"] = name in self.dirty
                self.next_allowed[name] = time.time() + delay


class _Skip(Exception):
    pass
