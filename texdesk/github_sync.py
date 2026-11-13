# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Sincronização com o GitHub: um repositório privado, com uma pasta por projeto.

Conexão: "Entrar com GitHub" pelo fluxo de dispositivo do OAuth (device flow). O TexDesk
mostra um código, a pessoa o digita em github.com/login/device, e o token fica no cofre de
senhas do sistema. Não precisa de git instalado: tudo passa pela API do GitHub (Git Data API).

Envio: cada alteração deixa o projeto pendente, e o commit sai COMMIT_DELAY (2 min) depois
da última, juntando as edições de uma sessão num commit só. Ao fechar o projeto no editor, o
commit sai na hora. Se o TexDesk for fechado antes (janela do terminal fechada, computador
desligado), nada se perde: os arquivos já estão salvos no disco, e o manifesto de cada
projeto (MANIFEST) guarda o que foi enviado por último. Ao fechar a janela, o TexDesk ainda
tenta enviar o que falta em poucos segundos (flush); se não der tempo, ao abrir de novo cada
projeto é comparado com o manifesto e o que ficou para trás vai no primeiro commit.

Recebimento: ao abrir o projeto e a cada 30 s enquanto ele está aberto, o TexDesk compara a
pasta do projeto no GitHub com a última sincronizada (uma leitura pequena). Se outro
computador mudou algo, traz as mudanças, juntando palavra por palavra quando os dois lados
mexeram no mesmo arquivo (merge.py), como a sincronização do Google Drive.
"""

import base64
import calendar
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .drive_sync import MANIFEST as DRIVE_MANIFEST
from .drive_sync import VERSION_FILE as DRIVE_VERSION_FILE
from .drive_sync import _is_text_name, _remove_empty_dirs, _safe_name, _write_atomic
from .merge import merge3
from .token_store import TokenStore

log = logging.getLogger(__name__)

API = "https://api.github.com"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
SCOPE = "repo"  # repositórios privados (o GitHub não tem escopo só para um repositório)
REPO_NAME = "texdesk-projetos"
MANIFEST = ".github.json"
COMMIT_DELAY = 120.0  # segundos sem editar até o commit
SHARED_DELAY = 30.0  # num projeto compartilhado: a outra pessoa vê a mudança em menos de 1 minuto
SHARED_REPO_PREFIX = "texdesk-"  # repositório de um projeto compartilhado: texdesk-<projeto>
SHARE_META = ".texdesk-projeto.json"  # na raiz dele: o nome do projeto (fica fora da pasta local)
RETRY_INTERVAL = 30.0
DOWNLOAD_WORKERS = 4
MAX_FILE = 90 * 1024 * 1024  # o GitHub recusa arquivos de mais de 100 MB
BASE_MAX = 2 * 1024 * 1024
# não vão para o GitHub: manifestos das sincronizações, miniatura do painel e a versão do Drive
EXCLUDE = {MANIFEST, DRIVE_MANIFEST, DRIVE_VERSION_FILE, ".thumbnail.png", SHARE_META}
FILE_MODE = "100644"


class GitHubError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class AuthRequired(GitHubError):
    pass


class RateLimited(GitHubError):
    """O GitHub pediu para esperar (limite de envios). retry_after em segundos."""

    def __init__(self, message, retry_after):
        super().__init__(message, 403)
        self.retry_after = retry_after


class NotFastForward(GitHubError):
    """Outro computador enviou um commit enquanto este montava o dele."""


def blob_sha(data: bytes):
    """O mesmo identificador que o git dá ao conteúdo (dá para comparar sem baixar)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_sha(p: Path):
    h = hashlib.sha1(b"blob %d\0" % p.stat().st_size)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- cliente da API do GitHub


class GitHubClient:
    def __init__(self, state_dir: Path, client_id: str, token_backend="auto", api=API, open_url=None):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client_id = client_id
        self.api = api
        self.state_file = self.dir / "state.json"
        self.tokens = TokenStore(self.dir, token_backend, kind="github")
        self._open = open_url or urllib.request.urlopen  # os testes trocam por um GitHub falso
        self._device = None  # login em andamento: {device_code, interval, expires, next}
        self._lock = threading.Lock()
        self.hurry = False  # enviando às pressas (TexDesk fechando): nenhuma chamada dispensável
        self._repos = {}  # dono/nome -> Repo (com o que já se sabe dele nesta execução)

    # ---- estado
    def state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, s):
        self.state_file.write_text(json.dumps(s, indent=2), encoding="utf-8")

    @property
    def configured(self):
        return bool(self.client_id)

    @property
    def connected(self):
        t = self.tokens.load()
        return bool(t and t.get("access_token") and self.state().get("repo"))

    @property
    def repo(self):
        return self.state().get("repo")  # "dono/nome"

    @property
    def branch(self):
        return self.state().get("branch") or "main"

    def disconnect(self):
        self.tokens.delete()
        s = self.state()
        self.save_state({k: v for k, v in s.items() if k in ("syncAll", "offered")})
        log.info("GitHub desconectado")

    # ---- login pelo fluxo de dispositivo
    def _post_form(self, url, data):
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode(),
            headers={"Accept": "application/json", "User-Agent": f"TexDesk/{__version__}"},
        )
        try:
            with self._open(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise GitHubError(f"GitHub respondeu {e.code}: {e.read()[:300].decode('utf-8', 'replace')}", e.code) from e
        except (urllib.error.URLError, OSError) as e:
            raise GitHubError(f"Sem conexão com o GitHub: {e}") from e

    def start_login(self):
        """Pede um código ao GitHub. Devolve o que mostrar: código, endereço e validade."""
        if not self.client_id:
            raise GitHubError("Esta instalação do TexDesk não tem o app do GitHub configurado")
        r = self._post_form(DEVICE_CODE_URL, {"client_id": self.client_id, "scope": SCOPE})
        if "device_code" not in r:
            raise GitHubError(r.get("error_description") or r.get("error") or "O GitHub não devolveu o código")
        now = time.time()
        with self._lock:
            self._device = {
                "device_code": r["device_code"],
                "interval": int(r.get("interval", 5)),
                "expires": now + int(r.get("expires_in", 900)),
                "next": now + int(r.get("interval", 5)),
            }
        return {
            "userCode": r["user_code"],
            "verificationUri": r.get("verification_uri", "https://github.com/login/device"),
            "expiresIn": int(r.get("expires_in", 900)),
            "interval": int(r.get("interval", 5)),
        }

    def poll_login(self):
        """Confere se a pessoa já autorizou. {"state": pending|done|expired|denied}."""
        with self._lock:
            dev = self._device
            if not dev:
                return {"state": "expired"}
            now = time.time()
            if now > dev["expires"]:
                self._device = None
                return {"state": "expired"}
            if now < dev["next"]:  # o GitHub pede para não perguntar antes do intervalo
                return {"state": "pending"}
            dev["next"] = now + dev["interval"]
        r = self._post_form(
            TOKEN_URL,
            {
                "client_id": self.client_id,
                "device_code": dev["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        err = r.get("error")
        if err == "authorization_pending":
            return {"state": "pending"}
        if err == "slow_down":
            with self._lock:
                dev["interval"] = int(r.get("interval", dev["interval"] + 5))
                dev["next"] = time.time() + dev["interval"]
            return {"state": "pending"}
        if err in ("expired_token", "token_expired"):
            self._device = None
            return {"state": "expired"}
        if err == "access_denied":
            self._device = None
            return {"state": "denied"}
        if err or not r.get("access_token"):
            raise GitHubError(r.get("error_description") or err or "O GitHub não devolveu o acesso")
        self._device = None
        self.tokens.save({"access_token": r["access_token"], "scope": r.get("scope", "")})
        try:
            user = self.request("GET", "/user")
            repo, branch = self.ensure_repo(user["login"])
        except GitHubError:
            self.tokens.delete()
            raise
        s = self.state()
        s.update(user=user["login"], repo=repo, branch=branch)
        s.setdefault("syncAll", True)  # "uma pasta com todos os projetos": todos entram
        self.save_state(s)
        log.info("GitHub conectado: %s (%s)", user["login"], repo)
        return {"state": "done", "user": user["login"], "repo": repo}

    # ---- chamadas à API
    def request(self, method, path, body=None, ok404=False):
        tok = self.tokens.load()
        if not tok or not tok.get("access_token"):
            raise AuthRequired("Conecte o GitHub de novo (painel → GitHub)", 401)
        url = path if path.startswith("http") else self.api + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {tok['access_token']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"TexDesk/{__version__}",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with self._open(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as e:
            text = e.read()[:500].decode("utf-8", "replace")
            if e.code == 404 and ok404:
                return None
            if e.code == 401:
                raise AuthRequired("O acesso ao GitHub foi revogado ou expirou. Conecte de novo", 401) from e
            remaining = e.headers.get("X-RateLimit-Remaining") if e.headers else None
            if e.code == 429 or (e.code == 403 and (remaining == "0" or "rate limit" in text.lower())):
                wait = e.headers.get("Retry-After") if e.headers else None
                reset = e.headers.get("X-RateLimit-Reset") if e.headers else None
                after = int(wait) if wait else max(60, int(reset) - int(time.time())) if reset else 60
                raise RateLimited(f"Limite do GitHub atingido; nova tentativa em {after // 60 or 1} min", after) from e
            if e.code == 422 and "fast forward" in text.lower():
                raise NotFastForward("Outro computador enviou alterações", 422) from e
            raise GitHubError(f"GitHub respondeu {e.code} em {method} {path}: {text[:200]}", e.code) from e
        except (urllib.error.URLError, OSError) as e:
            raise GitHubError(f"Sem conexão com o GitHub: {e}") from e

    def ensure_repo(self, login):
        """O repositório privado dos projetos: usa o existente ou cria. Devolve (dono/nome, branch)."""
        r = self.request("GET", f"/repos/{login}/{REPO_NAME}", ok404=True)
        if r is None:
            r = self.request(
                "POST",
                "/user/repos",
                {
                    "name": REPO_NAME,
                    "private": True,
                    "auto_init": True,  # já nasce com um commit (README): os envios têm onde se apoiar
                    "description": "Projetos LaTeX sincronizados pelo TexDesk",
                },
            )
        return r["full_name"], r.get("default_branch") or "main"

    def view(self, full_name=None, branch=None):
        """O repositório full_name ("dono/nome"); sem nome, o principal (texdesk-projetos)."""
        full_name = full_name or self.repo
        with self._lock:
            r = self._repos.get(full_name)
            if r is None:
                r = self._repos[full_name] = Repo(self, full_name, branch)
            return r

    # atalhos para o repositório principal
    def head(self):
        return self.view().head()

    def commit_tree(self, commit_sha):
        return self.view().commit_tree(commit_sha)

    def top_folders(self, tree_sha):
        return self.view().top_folders(tree_sha)

    def commit_url(self, sha):
        return self.view().commit_url(sha)

    # ---- compartilhamento
    def create_shared_repo(self, name):
        """Repositório privado de um projeto compartilhado (texdesk-<projeto>). Devolve dono/nome."""
        slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:80] or "projeto"
        user = self.state()["user"]
        for i in range(1, 50):
            repo_name = SHARED_REPO_PREFIX + slug + (f"-{i}" if i > 1 else "")
            if self.request("GET", f"/repos/{user}/{repo_name}", ok404=True) is not None:
                continue  # nome já usado na conta
            r = self.request(
                "POST",
                "/user/repos",
                {
                    "name": repo_name,
                    "private": True,
                    # vazio: o GitHub criaria um README.md, que viraria um arquivo do projeto (aqui
                    # o projeto é a raiz). O primeiro commit é o SHARE_META, pela API de conteúdo
                    "auto_init": False,
                    "description": f"{name} · projeto LaTeX compartilhado pelo TexDesk",
                },
            )
            return r["full_name"]
        raise GitHubError("Não foi possível escolher um nome para o repositório")

    def invitations(self):
        """Convites recebidos para projetos do TexDesk (outros convites do GitHub ficam de fora)."""
        out = []
        for inv in self.request("GET", "/user/repository_invitations?per_page=100") or []:
            repo = inv.get("repository") or {}
            if not repo.get("name", "").startswith(SHARED_REPO_PREFIX) or repo.get("name") == REPO_NAME:
                continue
            desc = repo.get("description") or ""
            out.append(
                {
                    "id": inv["id"],
                    "repo": repo["full_name"],
                    "name": desc.split(" · ")[0] if " · " in desc else repo["name"][len(SHARED_REPO_PREFIX) :],
                    "from": (inv.get("inviter") or {}).get("login"),
                    "write": inv.get("permissions") in ("write", "admin", "maintain"),
                }
            )
        return out

    def accept(self, invitation_id):
        self.request("PATCH", f"/user/repository_invitations/{int(invitation_id)}")

    def decline(self, invitation_id):
        self.request("DELETE", f"/user/repository_invitations/{int(invitation_id)}")

    def shared_repos(self):
        """Projetos compartilhados a que esta conta tem acesso (dela ou de outras pessoas)."""
        out = []
        for r in self.request("GET", "/user/repos?affiliation=owner,collaborator&per_page=100") or []:
            if not r["name"].startswith(SHARED_REPO_PREFIX) or r["name"] == REPO_NAME:
                continue
            desc = r.get("description") or ""
            name = desc.split(" · ")[0] if " · " in desc else r["name"][len(SHARED_REPO_PREFIX) :]
            out.append({"repo": r["full_name"], "name": name, "owner": r["full_name"].split("/")[0]})
        return out

    def leave(self, full_name):
        """Sai de um projeto compartilhado por outra pessoa (o repositório continua com ela)."""
        self.request("DELETE", f"/repos/{full_name}/collaborators/{self.state()['user']}")


class Repo:
    """Um repositório: o principal (uma pasta por projeto) ou o de um projeto compartilhado.

    Guarda o que este computador já sabe dele nesta execução: a raiz das últimas árvores, o
    último commit conhecido (known) e o README do principal.
    """

    def __init__(self, client: GitHubClient, full_name: str, branch=None):
        self.client = client
        self.full_name = full_name
        self._branch = branch
        self.dir = client.dir  # (cópias de base da junção, compartilhadas por todos os repositórios)
        self._tops = {}  # árvore -> {nome na raiz: (tipo, sha)}, da última consulta desta execução
        self.readme = None  # (sha, lista de projetos) do README.md do último commit conhecido
        # último commit do branch conhecido por este computador e a árvore dele: o próximo commit
        # se apoia nele sem perguntar ao GitHub (se outro computador enviou no meio, o GitHub
        # recusa a atualização do branch, e o commit é refeito pelo caminho completo)
        self.known = None

    @property
    def branch(self):
        if self._branch is None:
            if self.full_name == self.client.repo:
                self._branch = self.client.branch
            else:
                self._branch = self.client.request("GET", f"/repos/{self.full_name}").get("default_branch") or "main"
        return self._branch

    def request(self, method, path, body=None, ok404=False):
        return self.client.request(method, path, body, ok404)

    def _repo_path(self, rest):
        return f"/repos/{self.full_name}{rest}"

    def head(self):
        r = self.request("GET", self._repo_path(f"/git/ref/heads/{self.branch}"))
        return r["object"]["sha"]

    def commit_tree(self, commit_sha):
        return self.request("GET", self._repo_path(f"/git/commits/{commit_sha}"))["tree"]["sha"]

    def _top(self, tree_sha):
        if tree_sha not in self._tops:
            r = self.request("GET", self._repo_path(f"/git/trees/{tree_sha}"))
            self._tops = {tree_sha: {e["path"]: (e["type"], e["sha"]) for e in r["tree"]}}
        return self._tops[tree_sha]

    def top_folders(self, tree_sha):
        """{pasta de projeto: sha da árvore dela}, na raiz do repositório."""
        return {p: sha for p, (kind, sha) in self._top(tree_sha).items() if kind == "tree"}

    def top_file(self, tree_sha, name):
        """sha de um arquivo da raiz do repositório (ex.: README.md), ou None."""
        kind, sha = self._top(tree_sha).get(name, (None, None))
        return sha if kind == "blob" else None

    def tree_files(self, tree_sha):
        """{caminho: sha} de todos os arquivos de uma pasta (com subpastas)."""
        r = self.request("GET", self._repo_path(f"/git/trees/{tree_sha}?recursive=1"))
        if r.get("truncated"):
            raise GitHubError("Projeto grande demais para a API do GitHub (mais de 100 mil arquivos)")
        return {e["path"]: e["sha"] for e in r["tree"] if e["type"] == "blob"}

    def blob(self, sha):
        r = self.request("GET", self._repo_path(f"/git/blobs/{sha}"))
        return base64.b64decode(r["content"]) if r.get("encoding") == "base64" else r["content"].encode("utf-8")

    def create_blob(self, data: bytes):
        r = self.request(
            "POST", self._repo_path("/git/blobs"), {"content": base64.b64encode(data).decode(), "encoding": "base64"}
        )
        return r["sha"]

    def create_tree(self, base_tree, entries):
        r = self.request("POST", self._repo_path("/git/trees"), {"base_tree": base_tree, "tree": entries})
        if "tree" in r:  # a resposta já traz a raiz da árvore nova: top_folders() não pergunta de novo
            self._tops = {r["sha"]: {e["path"]: (e["type"], e["sha"]) for e in r["tree"]}}
        return r["sha"]

    def create_commit(self, message, tree, parent):
        body = {"message": message, "tree": tree, "parents": [parent]}
        r = self.request("POST", self._repo_path("/git/commits"), body)
        return r["sha"]

    def update_head(self, sha):
        self.request("PATCH", self._repo_path(f"/git/refs/heads/{self.branch}"), {"sha": sha, "force": False})

    def last_change(self, path):
        """Instante do último commit que mexeu na pasta (para o README), ou None."""
        query = f"path={urllib.parse.quote(path)}&sha={self.branch}&per_page=1"
        r = self.request("GET", self._repo_path(f"/commits?{query}"))
        if not r:
            return None
        when = r[0]["commit"]["committer"]["date"]  # ex.: 2026-11-12T23:40:05Z
        return calendar.timegm(time.strptime(when, "%Y-%m-%dT%H:%M:%SZ"))

    # ---- pessoas com acesso (projeto compartilhado)
    @property
    def owner(self):
        return self.full_name.split("/")[0]

    def can_push(self):
        perms = (self.request("GET", f"/repos/{self.full_name}") or {}).get("permissions") or {}
        return bool(perms.get("push"))

    def people(self):
        """Quem tem acesso (sem o dono) e os convites pendentes: [{login, write, pending, invitation}]."""
        out = []
        for c in self.request("GET", self._repo_path("/collaborators?affiliation=direct&per_page=100")) or []:
            if c["login"].lower() != self.owner.lower():
                perms = c.get("permissions") or {}
                out.append(
                    {
                        "login": c["login"],
                        "avatar": c.get("avatar_url"),
                        "write": bool(perms.get("push")),
                        "pending": False,
                    }
                )
        for i in self.request("GET", self._repo_path("/invitations?per_page=100")) or []:
            who = i.get("invitee") or {}
            out.append(
                {
                    "login": who.get("login"),
                    "avatar": who.get("avatar_url"),
                    "write": i.get("permissions") in ("write", "admin", "maintain"),
                    "pending": True,
                    "invitation": i["id"],
                }
            )
        return sorted(out, key=lambda x: (x["login"] or "").lower())

    def invite(self, login, write):
        """Convida (ou muda a permissão de quem já aceitou)."""
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", login or ""):
            raise GitHubError("Usuário do GitHub inválido")
        if login.lower() == self.owner.lower():
            raise GitHubError("Esse é o dono do projeto")
        r = self.request(
            "PUT", self._repo_path(f"/collaborators/{login}"), {"permission": "push" if write else "pull"}, ok404=True
        )
        if r is None:
            raise GitHubError(f"Usuário do GitHub não encontrado: {login}", 404)

    def set_permission(self, login, write, invitation=None):
        if invitation:
            self.request(
                "PATCH",
                self._repo_path(f"/invitations/{int(invitation)}"),
                {"permissions": "write" if write else "read"},
            )
        else:
            self.invite(login, write)

    def remove(self, login, invitation=None):
        if invitation:
            self.request("DELETE", self._repo_path(f"/invitations/{int(invitation)}"))
        else:
            self.request("DELETE", self._repo_path(f"/collaborators/{login}"))

    def put_file(self, path, data: bytes, message):
        """Grava um arquivo direto no branch (uma chamada; usado só para SHARE_META)."""
        body = {"message": message, "content": base64.b64encode(data).decode(), "branch": self.branch}
        self.request("PUT", self._repo_path(f"/contents/{urllib.parse.quote(path)}"), body)
        self.known = None  # o branch andou

    def commit_url(self, sha):
        return f"https://github.com/{self.full_name}/commit/{sha}"

    def folder_url(self, path):
        if not path:
            return f"https://github.com/{self.full_name}"
        return f"https://github.com/{self.full_name}/tree/{self.branch}/{urllib.parse.quote(path)}"


# ---------------------------------------------------------------- manifesto e arquivos locais


def load_manifest(d: Path):
    try:
        return json.loads((d / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(d: Path, m):
    tmp = d / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / MANIFEST)


def local_files(d: Path):
    """Arquivos do projeto que vão para o GitHub (inclui o .project.json)."""
    out = {}
    for p in d.rglob("*"):
        if p.is_file() and p.name not in EXCLUDE and not p.name.endswith(".tmp"):
            out[p.relative_to(d).as_posix()] = p
    return out


def pending_changes(d: Path):
    """Arquivos alterados, novos ou apagados desde o último commit (sem chamar o GitHub)."""
    m = load_manifest(d)
    files, known = local_files(d), m.get("files", {})
    out = []
    for rel, p in files.items():
        st = p.stat()
        e = known.get(rel)
        if not e or e.get("mtime") != st.st_mtime or e.get("size") != st.st_size:
            if not e or e.get("sha") != file_sha(p):
                out.append(rel)
    out += [rel for rel in known if rel not in files]
    return sorted(out)


# versão comum (base da junção): cópia de cada arquivo de texto como estava no último commit
def _base_dir(client):
    return Path(client.dir) / "base"


def _save_base(client, sha, data: bytes, rel):
    if not sha or len(data) > BASE_MAX or not _is_text_name(rel):
        return
    p = _base_dir(client) / sha
    if not p.exists():
        _write_atomic(p, data)


def _load_base(client, sha):
    try:
        return (_base_dir(client) / sha).read_bytes()
    except OSError:
        return None


# ---------------------------------------------------------------- sincronização de um projeto


def sync_project(client: GitHubClient, d: Path, name: str, push=True, report=None, before_change=None):
    """Traz do GitHub o que outro computador mudou e, se push, envia um commit com o daqui.

    O projeto vive numa pasta do repositório principal (texdesk-projetos/<nome>) ou, se for
    compartilhado, na raiz do repositório próprio dele (manifesto "repo"). Num projeto só de
    leitura (manifesto "readOnly"), nada é enviado.

    report recebe "received" (arquivos alterados aqui), "conflicts" (trechos alterados dos dois
    lados) e "commit" ({sha, url, files}) quando houve envio. Devolve o nº de arquivos enviados.
    """
    report = {} if report is None else report
    report.setdefault("received", [])
    report.setdefault("conflicts", [])
    m = load_manifest(d)
    m.setdefault("files", {})
    shared = m.get("repo")
    repo = client.view(shared)
    prefix = "" if shared else name
    old_path = m.get("path")
    renamed_from = old_path if not shared and old_path and old_path != name else None
    push = push and not m.get("readOnly")
    for attempt in range(4):
        # Commit rápido (3 chamadas em vez de 7, o que importa ao fechar a janela, quando o Windows
        # dá uns 5 s): apoiado no último commit conhecido, sem conferir antes o GitHub. Se outro
        # computador enviou algo no meio, update_head falha e a volta seguinte faz o completo.
        fast = attempt == 0 and push and repo.known and not renamed_from and m.get("head")
        if fast:
            head, root = repo.known
            remote_tree = m.get("tree")
        else:
            head = repo.head()
            root = repo.commit_tree(head)
            repo.known = (head, root)
            if shared:
                remote_tree = root
            else:
                remote_tree = repo.top_folders(root).get(name)
                if renamed_from and remote_tree is None:  # projeto renomeado aqui: a pasta antiga vale
                    remote_tree = repo.top_folders(root).get(renamed_from)
        if not fast and remote_tree != m.get("tree"):
            skip = _pull(repo, d, m, remote_tree, report, before_change)
            m["tree"] = remote_tree if not skip else None
            m["head"] = head
            save_manifest(d, m)
        else:
            skip = set()
        if not push:
            return 0
        entries, sent = _changes(repo, d, m, skip, prefix, renamed_from)
        if not entries:
            if fast:  # nada a enviar: confere o GitHub pelo caminho completo (traz o que mudou lá)
                continue
            m["path"], m["head"], m["lastSync"] = prefix, head, time.time()
            save_manifest(d, m)
            return 0
        readme = None
        if not shared:  # a lista de projetos fica no README do repositório principal
            readme = _readme(repo, root, name, renamed_from, fill=not client.hurry)
            entries = entries + [readme[2]]
        tree = repo.create_tree(root, entries)
        commit = repo.create_commit(_message(name, sent, renamed_from), tree, head)
        try:
            repo.update_head(commit)
        except NotFastForward:
            continue  # outro computador enviou no meio: traz o dele e monta de novo
        repo.known = (commit, tree)
        if readme:
            repo.readme = readme[:2]
        new_tree = tree if shared else repo.top_folders(tree).get(name)
        for rel, info in sent.items():
            if info is None:
                m["files"].pop(rel, None)
            else:
                m["files"][rel] = info
        m.update(path=prefix, head=commit, tree=new_tree, lastSync=time.time())
        m["lastCommit"] = {"sha": commit, "at": time.time(), "files": sorted(sent)}
        save_manifest(d, m)
        report["commit"] = {"sha": commit, "url": repo.commit_url(commit), "files": sorted(sent)}
        _prune_base(repo, d)
        return len(sent)
    raise GitHubError("O repositório mudou várias vezes seguidas; nova tentativa em seguida")


def _join(prefix, rel):
    return f"{prefix}/{rel}" if prefix else rel


# ---------------------------------------------------------------- README do repositório
# A lista dos projetos salvos, com a última atualização de cada um, vai no mesmo commit do
# projeto (sem chamada a mais ao GitHub). Os dados ficam num comentário no fim do README, para
# outro computador continuar a lista; o resto do arquivo é refeito a cada commit.
README = "README.md"
README_DATA = "<!-- texdesk-projetos: "


def _readme(client, root, name, renamed_from, fill=True):
    """(sha, dados, entrada da árvore) do README com o projeto name atualizado agora.

    fill: busca a data das pastas que ainda não estão na lista (enviadas antes de o README
    existir). Fica de fora no envio ao fechar o TexDesk, que precisa caber em poucos segundos.
    """
    sha = client.top_file(root, README)
    if client.readme and client.readme[0] == sha:
        data = dict(client.readme[1])  # o do último commit deste computador: sem baixar
    else:
        data = _parse_readme(client.blob(sha)) if sha else {}
    folders = set(client.top_folders(root)) | ({name} if name else set())
    folders.discard(renamed_from)
    data = {p: v for p, v in data.items() if p in folders}
    for p in sorted(folders - set(data) - {name}) if fill else ():
        try:
            at = client.last_change(p)
        except GitHubError:
            at = None
        if at:
            data[p] = {"at": at, "computer": ""}
    if name:
        data[name] = {"at": time.time(), "computer": platform.node() or ""}
    text = _render_readme(data, folders)
    raw = text.encode("utf-8")
    return blob_sha(raw), data, {"path": README, "mode": FILE_MODE, "type": "blob", "content": text}


def _parse_readme(raw: bytes):
    text = raw.decode("utf-8", "replace")
    i = text.rfind(README_DATA)
    if i < 0:
        return {}
    try:
        data = json.loads(text[i + len(README_DATA) : text.index("-->", i)].strip())
    except ValueError:
        return {}
    return {p: v for p, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _render_readme(data, folders):
    def when(p):
        at = data.get(p, {}).get("at")
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(at)) if at else "—"

    def cell(s):
        return str(s).replace("|", "\\|")

    order = sorted(folders, key=lambda p: (-(data.get(p, {}).get("at") or 0), p.lower()))
    rows = [
        f"| [{cell(p)}]({urllib.parse.quote(p)}/) | {when(p)} | {cell(data.get(p, {}).get('computer') or '—')} |"
        for p in order
    ]
    lines = [
        "# Projetos do TexDesk",
        "",
        "Projetos LaTeX sincronizados pelo [TexDesk](https://github.com/hugocesarleal/texdesk). Cada pasta é um "
        "projeto. O TexDesk faz os commits sozinho e atualiza esta lista a cada envio.",
        "",
        f"**{len(order)} projeto{'s' if len(order) != 1 else ''}**",
        "",
        "| Projeto | Última atualização | Computador |",
        "| --- | --- | --- |",
        *rows,
        "",
        "<sub>Arquivo gerado pelo TexDesk: alterações feitas nele à mão são substituídas no próximo envio.</sub>",
        "",
        README_DATA + json.dumps(data, ensure_ascii=False, sort_keys=True) + " -->",
        "",
    ]
    return "\n".join(lines)


def _message(name, sent, renamed_from=None):
    names = sorted(sent)
    shown = ", ".join(names[:3]) + (f" e mais {len(names) - 3}" if len(names) > 3 else "")
    title = f"{name}: renomeado (antes: {renamed_from})" if renamed_from else f"{name}: {shown}"
    return f"{title}\n\nEnviado pelo TexDesk de {platform.node() or 'um computador'}."


def _changes(client, d: Path, m: dict, skip, prefix, renamed_from):
    """Entradas da árvore do commit e, para o manifesto, {caminho: info ou None (apagado)}."""
    files = {rel: p for rel, p in local_files(d).items() if rel not in skip}
    entries, sent = [], {}
    if renamed_from:
        # renomeado aqui: no repositório a pasta muda de nome. Os arquivos que não mudaram vão
        # para o caminho novo pelo sha (o conteúdo já está no GitHub: nada é reenviado)
        for rel, e in m["files"].items():
            entries.append({"path": f"{renamed_from}/{rel}", "mode": FILE_MODE, "type": "blob", "sha": None})
            if rel in files and e.get("sha"):
                entries.append({"path": _join(prefix, rel), "mode": FILE_MODE, "type": "blob", "sha": e["sha"]})
                sent[rel] = dict(e)
    for rel, p in sorted(files.items()):
        st = p.stat()
        e = m["files"].get(rel)
        if e and e.get("mtime") == st.st_mtime and e.get("size") == st.st_size:
            continue
        if st.st_size > MAX_FILE:
            log.warning("GitHub: %s tem mais de 90 MB e não foi enviado", _join(prefix or d.name, rel))
            continue
        data = p.read_bytes()
        sha = blob_sha(data)
        info = {"sha": sha, "mtime": st.st_mtime, "size": st.st_size}
        if e and e.get("sha") == sha:
            m["files"][rel] = info  # só a data mudou
            if rel in sent:
                sent[rel] = info
            continue
        path = _join(prefix, rel)
        if rel in sent:  # renomeado e também alterado: vale o conteúdo novo
            entries = [x for x in entries if x["path"] != path]
        try:
            text = data.decode("utf-8")
            entries.append({"path": path, "mode": FILE_MODE, "type": "blob", "content": text})
        except UnicodeDecodeError:  # imagem, PDF…: vai como blob, em base64
            entries.append({"path": path, "mode": FILE_MODE, "type": "blob", "sha": client.create_blob(data)})
        sent[rel] = info
        _save_base(client, sha, data, rel)
    for rel in [r for r in m["files"] if r not in files and r not in skip]:
        if not renamed_from:  # (renomeado: o caminho antigo já foi apagado acima)
            entries.append({"path": _join(prefix, rel), "mode": FILE_MODE, "type": "blob", "sha": None})
        sent[rel] = None
    return entries, sent


def _pull(client, d: Path, m: dict, remote_tree, report, before_change):
    """Traz o que mudou na pasta do projeto no GitHub desde a última sincronização.

    Mesmas regras do Google Drive: só lá mudou -> baixa; só aqui -> fica para o commit; os dois
    -> junta palavra por palavra (texto) ou fica o daqui (outros arquivos, que vão no commit).
    Um arquivo editado aqui e apagado lá não é apagado. Uma pasta apagada no GitHub não apaga
    nada aqui: o próximo commit a recria. Devolve os arquivos que mudaram aqui no meio.
    """
    if remote_tree is None:  # sem pasta no GitHub (projeto novo, ou apagada lá): envia tudo
        m["files"] = {}
        return set()
    remote = _remote_files(client, remote_tree)
    files = local_files(d)
    plan, important = [], False
    for rel in sorted(set(remote) | set(m["files"])):
        rsha, e, lp = remote.get(rel), m["files"].get(rel), files.get(rel)
        base = e.get("sha") if e else None
        if rsha == base:
            continue  # não mudou no GitHub
        st = lp.stat() if lp else None
        seen = (st.st_mtime, st.st_size) if st else None
        if st is None:
            lsha = None
        elif e and e.get("mtime") == st.st_mtime and e.get("size") == st.st_size:
            lsha = base
        else:
            lsha = file_sha(lp)
        if rsha is None:  # apagado no GitHub
            plan.append(("delete" if lsha == base else "forget", rel, None, seen))
        elif lsha == rsha:
            plan.append(("adopt", rel, rsha, seen))
        elif lsha is None or lsha == base:
            plan.append(("download", rel, rsha, seen))
        else:
            important = True
            base_data = _load_base(client, base) if base else None
            plan.append(("merge" if base_data is not None and _is_text_name(rel) else "keep", rel, rsha, seen))

    need = sorted({sha for act, _, sha, _ in plan if act in ("download", "merge")})
    data = {}
    if need:
        with ThreadPoolExecutor(max_workers=min(DOWNLOAD_WORKERS, len(need))) as pool:
            data = dict(zip(need, pool.map(client.blob, need), strict=True))
    if before_change and any(act in ("download", "merge", "delete") for act, *_ in plan):
        before_change(d, important)

    skip = set()
    for act, rel, rsha, seen in plan:
        p = d / rel
        try:
            st = p.stat()
            now = (st.st_mtime, st.st_size)
        except OSError:
            now = None
        if now != seen:  # mudou aqui durante a conferência: fica para a próxima
            skip.add(rel)
            continue
        if act == "forget":
            m["files"].pop(rel, None)
        elif act == "delete":
            p.unlink(missing_ok=True)
            _remove_empty_dirs(d, p.parent)
            m["files"].pop(rel, None)
            report["received"].append(rel)
        elif act == "adopt":
            m["files"][rel] = {"sha": rsha, "mtime": now[0], "size": now[1]}
        elif act == "keep":  # fica o daqui; o commit o envia por cima
            m["files"][rel] = {"sha": rsha}
        elif act == "download":
            _write_atomic(p, data[rsha])
            st = p.stat()
            m["files"][rel] = {"sha": rsha, "mtime": st.st_mtime, "size": st.st_size}
            _save_base(client, rsha, data[rsha], rel)
            report["received"].append(rel)
        elif act == "merge":
            theirs_b = data[rsha]
            _save_base(client, rsha, theirs_b, rel)
            try:
                base_t, mine, theirs = (
                    x.decode("utf-8") for x in (_load_base(client, m["files"][rel]["sha"]), p.read_bytes(), theirs_b)
                )
            except UnicodeDecodeError:
                m["files"][rel] = {"sha": rsha}
                continue
            merged, conflicts = merge3(base_t, mine, theirs)
            if merged != mine:
                _write_atomic(p, merged.encode("utf-8"))
                report["received"].append(rel)
            if merged == theirs:
                st = p.stat()
                m["files"][rel] = {"sha": rsha, "mtime": st.st_mtime, "size": st.st_size}
            else:  # o resultado da junção vai no próximo commit
                m["files"][rel] = {"sha": rsha}
            report["conflicts"] += [dict(c, path=rel) for c in conflicts]
    return skip


def _remote_files(client, tree):
    """Arquivos de uma pasta do repositório que podem virar arquivos aqui ({caminho: sha})."""
    out = {}
    for rel, sha in client.tree_files(tree).items():
        if all(_safe_name(x) for x in rel.split("/")) and rel not in EXCLUDE:
            out[rel] = sha  # (nomes como "..", "a\b" ou "C:x" ficam de fora)
    return out


def _prune_base(client, d: Path):
    """Apaga as cópias de base que nenhum projeto usa mais (barato: só quando há commit)."""
    bd = _base_dir(client)
    if not bd.is_dir():
        return
    keep = set()
    for proj in d.parent.iterdir():
        keep |= {e.get("sha") for e in load_manifest(proj).get("files", {}).values()} if proj.is_dir() else set()
    for p in bd.iterdir():
        if p.name not in keep:
            p.unlink(missing_ok=True)


def share_project(client: GitHubClient, d: Path, name: str):
    """Leva o projeto para um repositório privado só dele, onde dá para convidar pessoas.

    No repositório principal, o acesso de um convidado valeria para todos os projetos. A ordem
    protege os arquivos: o projeto inteiro vai para o repositório novo e só depois sai do
    principal (moveFrom no manifesto: se algo falhar no meio, a próxima sincronização termina).
    """
    m = load_manifest(d)
    if m.get("repo"):
        return m["repo"]
    full = client.create_shared_repo(name)
    repo = client.view(full)
    meta = {"name": name, "owner": client.state().get("user")}
    repo.put_file(
        SHARE_META, json.dumps(meta, ensure_ascii=False).encode(), f"{name}: projeto compartilhado pelo TexDesk"
    )
    new = {"repo": full, "path": "", "files": {}, "moveFrom": m.get("path") or (name if m.get("files") else None)}
    save_manifest(d, new)
    sync_project(client, d, name)  # todos os arquivos, num commit
    finish_move(client, d)
    return full


def finish_move(client: GitHubClient, d: Path):
    """Tira do repositório principal a pasta de um projeto que já está no repositório próprio."""
    m = load_manifest(d)
    path = m.get("moveFrom")
    if not path or not m.get("lastCommit"):
        return
    main = client.view()
    for _ in range(3):
        head = main.head()
        root = main.commit_tree(head)
        tree = main.top_folders(root).get(path)
        if tree is None:
            break
        entries = [
            {"path": f"{path}/{rel}", "mode": FILE_MODE, "type": "blob", "sha": None} for rel in main.tree_files(tree)
        ]
        readme = _readme(main, root, None, path, fill=not client.hurry)
        new_tree = main.create_tree(root, entries + [readme[2]])
        commit = main.create_commit(f"{path}: movido para o repositório compartilhado {m['repo']}", new_tree, head)
        try:
            main.update_head(commit)
        except NotFastForward:
            continue
        main.known = (commit, new_tree)
        main.readme = readme[:2]
        break
    m.pop("moveFrom", None)
    save_manifest(d, m)


SHARED_PREFIX = "repo:"  # id de importação de um projeto compartilhado: "repo:dono/nome"


def restore_project(client: GitHubClient, path: str, dest: Path, remote_name: str, progress=None):
    """Baixa um projeto para dest (importação em outro computador ou de quem recebeu o convite).

    path é a pasta no repositório principal ou, para um projeto compartilhado, "repo:dono/nome"
    (o projeto é a raiz desse repositório).
    """
    shared = path[len(SHARED_PREFIX) :] if path.startswith(SHARED_PREFIX) else None
    repo = client.view(shared)
    head = repo.head()
    root = repo.commit_tree(head)
    tree = root if shared else repo.top_folders(root).get(path)
    if tree is None:
        raise GitHubError(f"A pasta {path} não está mais no repositório")
    remote = _remote_files(repo, tree)
    if progress:
        progress(0, len(remote))
    dest.mkdir(parents=True)
    m = {"path": "" if shared else path, "head": head, "tree": tree, "files": {}}
    if shared:
        m["repo"] = shared
        m["readOnly"] = not repo.can_push()
    lock = threading.Lock()

    def fetch(item):
        rel, sha = item
        data = repo.blob(sha)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        st = target.stat()
        _save_base(client, sha, data, rel)
        with lock:
            m["files"][rel] = {"sha": sha, "mtime": st.st_mtime, "size": st.st_size}
            if progress:
                progress(len(m["files"]), len(remote))

    try:
        if remote:
            with ThreadPoolExecutor(max_workers=min(DOWNLOAD_WORKERS, len(remote))) as pool:
                for fut in [pool.submit(fetch, it) for it in remote.items()]:
                    fut.result()
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    m["lastSync"] = time.time()
    save_manifest(dest, m)
    return len(m["files"])


# ---------------------------------------------------------------- fila de envio


class GitSyncManager:
    """Commits com atraso (COMMIT_DELAY depois da última alteração) e conferências do GitHub.

    Um worker só: os commits de projetos diferentes vão para o mesmo branch, um de cada vez.
    """

    def __init__(self, client: GitHubClient, projects_dir: Path, is_enabled, before_change=None, after_change=None):
        self.client = client
        self.projects = projects_dir
        self.is_enabled = is_enabled
        self.before_change = before_change  # (pasta, nome, important)
        self.after_change = after_change  # (nome)
        self.due = {}  # nome -> instante do commit
        self.checks = {}  # nome -> instante da conferência (só trazer)
        self.status = {}
        self.blocked_until = 0.0  # limite do GitHub
        self.busy = None
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.stopped = False
        self.paused = 0  # exclusive() em andamento: a fila espera
        self.thread = threading.Thread(target=self._run, daemon=True, name="github-sync")
        self.thread.start()

    # ---- pedidos
    def mark_dirty(self, name):
        """Algo mudou no projeto: o commit sai COMMIT_DELAY depois da última alteração."""
        if not self.client.connected or not self.is_enabled(name):
            return
        with self.cv:
            at = time.time() + (SHARED_DELAY if load_manifest(self.projects / name).get("repo") else COMMIT_DELAY)
            self.due[name] = at
            self.status.setdefault(name, {}).update(pending=True, commitAt=at)
            self.cv.notify()

    def commit_now(self, name):
        if not self.client.connected or not self.is_enabled(name):
            return
        with self.cv:
            self.due[name] = time.time()
            self.status.setdefault(name, {}).update(pending=True, commitAt=self.due[name])
            self.cv.notify()

    def check(self, name):
        """Conferir já se outro computador mexeu no projeto (o editor pede a cada 30 s)."""
        if not self.client.connected or not self.is_enabled(name):
            return
        with self.cv:
            self.checks[name] = time.time()
            self.cv.notify()

    def mark_all(self):
        """Ao abrir o TexDesk (ou conectar): confere todos e envia o que ficou para trás
        (alterações feitas com o TexDesk fechado ou interrompido antes do commit)."""
        for d in self.projects.iterdir():
            if d.is_dir() and not d.name.startswith(".") and self.is_enabled(d.name):
                with self.cv:  # (antecipa também um commit que já estava esperando o prazo)
                    self.due[d.name] = min(self.due.get(d.name, float("inf")), time.time())
        with self.cv:
            self.cv.notify()

    def flush(self, timeout):
        """Envia já tudo o que está esperando o commit e espera até timeout segundos.

        Chamado ao fechar o TexDesk (inclusive pela janela do terminal) e pelo "Enviar agora".
        Devolve True se não sobrou nada pendente."""
        if not self.client.connected:
            return True
        end = time.time() + timeout
        self.client.hurry = True
        try:
            with self.cv:
                now = time.time()
                for n in list(self.due):
                    self.due[n] = min(self.due[n], now)
                self.cv.notify_all()
                while (self.due or self.busy) and not self.stopped:
                    left = end - time.time()
                    if left <= 0:
                        return False
                    self.cv.wait(timeout=min(left, 0.2))
            return True
        finally:
            self.client.hurry = False

    def stop(self, timeout=60):
        self.flush(min(timeout, 20))
        with self.cv:
            self.stopped = True
            self.cv.notify_all()
        self.thread.join(timeout)

    def forget(self, name):
        with self.lock:
            self.due.pop(name, None)
            self.checks.pop(name, None)
            self.status.pop(name, None)

    def pop_conflict(self, name, cid):
        with self.lock:
            items = self.status.get(name, {}).get("conflicts", [])
            for c in items:
                if c["id"] == cid:
                    items.remove(c)
                    return c
        return None

    # ---- estado para a interface
    def get_status(self, name):
        with self.lock:
            st = dict(self.status.get(name, {}))
            st["conflicts"] = list(st.get("conflicts", []))
            st["pending"] = name in self.due or bool(st.get("pending") and self.busy == name)
            if name in self.due:
                st["commitAt"] = self.due[name]
            blocked = self.blocked_until
        st["enabled"] = self.is_enabled(name)
        st["connected"] = self.client.connected
        st.setdefault("state", "idle")
        if blocked > time.time() and st["pending"]:
            st["waitUntil"] = blocked
        m = load_manifest(self.projects / name)
        shared = m.get("repo")
        if "lastSync" not in st:
            st["lastSync"] = m.get("lastSync")
            if m.get("lastCommit") and st["connected"]:
                st["lastCommit"] = dict(
                    m["lastCommit"], url=self.client.view(shared).commit_url(m["lastCommit"]["sha"])
                )
            with self.lock:
                self.status.setdefault(name, {}).setdefault("lastSync", st["lastSync"])
                if "lastCommit" in st:
                    self.status[name].setdefault("lastCommit", st["lastCommit"])
        if shared:  # compartilhado: repositório próprio, de quem compartilhou
            me = (self.client.state().get("user") or "").lower()
            st["shared"] = {"repo": shared, "owner": shared.split("/")[0], "mine": shared.split("/")[0].lower() == me}
            st["readOnly"] = bool(m.get("readOnly"))
        if st["enabled"] and st["connected"]:
            st["url"] = self.client.view(shared).folder_url("" if shared else name)
        return st

    def overview(self, names):
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

    # ---- worker
    PERMISSION_EVERY = 300.0  # segundos entre conferências da permissão num projeto de outra pessoa

    def _refresh_permission(self, d: Path, force=False):
        """Num projeto compartilhado por outra pessoa: confere se ainda pode editar (o dono pode ter
        mudado para "só ler", ou o contrário). Devolve True se ainda tem acesso ao repositório."""
        m = load_manifest(d)
        shared = m.get("repo")
        if not shared or shared.split("/")[0].lower() == (self.client.state().get("user") or "").lower():
            return bool(shared)
        if not force and time.time() - m.get("permissionAt", 0) < self.PERMISSION_EVERY:
            return True
        info = self.client.request("GET", f"/repos/{shared}", ok404=True)
        if info is None:
            return False
        read_only = not (info.get("permissions") or {}).get("push")
        if read_only != bool(m.get("readOnly")):
            log.info("GitHub: %s agora é %s", d.name, "só para leitura" if read_only else "editável")
        m.update(readOnly=read_only, permissionAt=time.time())
        save_manifest(d, m)
        return True

    def exclusive(self, fn):
        """Roda fn() com a fila parada (depois do envio em andamento): ex., ao levar um projeto
        para o repositório próprio, nenhum commit dele pode sair pelo caminho antigo no meio."""
        with self.cv:
            self.paused += 1
            while self.busy:
                self.cv.wait(timeout=0.2)
        try:
            return fn()
        finally:
            with self.cv:
                self.paused -= 1
                self.cv.notify_all()

    def _next(self):
        """(nome, push) do próximo trabalho, ou o tempo a esperar."""
        now = time.time()
        if self.paused:
            return None, None, 0.2
        if now < self.blocked_until:
            return None, None, self.blocked_until - now
        if self.checks:  # conferências pedidas pelo editor vêm primeiro
            name = min(self.checks, key=self.checks.get)
            self.checks.pop(name)
            return name, name in self.due and self.due[name] <= now, 0
        ready = [n for n, at in self.due.items() if at <= now]
        if ready:
            return min(ready, key=self.due.get), True, 0
        waits = [at - now for at in self.due.values()]
        return None, None, min(waits) if waits else None

    def _run(self):
        while True:
            with self.cv:
                if self.stopped:
                    return
                name, push, wait = self._next()
                if not name:
                    self.cv.wait(timeout=wait)
                    continue
                if push:
                    self.due.pop(name, None)
                self.busy = name
                self.status.setdefault(name, {}).update(state="syncing")
            report = {}
            d = self.projects / name
            delay_on_error = None
            try:
                if not d.is_dir() or not self.is_enabled(name) or not self.client.connected:
                    upd = {"state": "idle"}
                else:

                    def before(pasta, important, name=name):
                        if self.before_change:
                            self.before_change(pasta, name, important)

                    self._refresh_permission(d)
                    try:
                        sent = sync_project(self.client, d, name, push=push, report=report, before_change=before)
                    except GitHubError as e:
                        # o dono passou esta pessoa para "só ler": o GitHub recusa o envio. Confere e,
                        # se ela ainda lê o projeto, segue recebendo, sem enviar
                        if e.status != 404 or not self._refresh_permission(d, force=True):
                            raise
                        sent = sync_project(self.client, d, name, push=False, report=report, before_change=before)
                    if load_manifest(d).get("moveFrom"):  # compartilhamento interrompido no meio
                        finish_move(self.client, d)
                    if sent:
                        log.info("GitHub: %s enviado (%d arquivo(s))", name, sent)
                    upd = {"state": "synced", "lastSync": time.time(), "error": None}
                    if report.get("commit"):
                        upd["lastCommit"] = dict(report["commit"], at=time.time())
            except RateLimited as e:
                log.warning("GitHub: %s", e)
                upd, delay_on_error = {"state": "waiting", "error": str(e)}, e.retry_after
                with self.cv:
                    self.blocked_until = time.time() + e.retry_after
            except AuthRequired as e:
                log.warning("GitHub: %s não sincronizado: %s", name, e)
                upd = {"state": "error", "error": str(e)}
            except Exception as e:  # rede, repositório apagado etc.: tenta de novo depois
                if isinstance(e, GitHubError) and e.status == 404 and load_manifest(d).get("repo"):
                    e = GitHubError(
                        "Você não tem mais acesso a este projeto no GitHub: quem compartilhou tirou o "
                        "acesso ou apagou o repositório. A cópia neste computador continua aqui.",
                        404,
                    )
                if isinstance(e, GitHubError):
                    log.warning("GitHub: falha ao sincronizar %s: %s", name, e)
                else:
                    log.exception("GitHub: erro inesperado ao sincronizar %s", name)
                upd, delay_on_error = {"state": "error", "error": str(e)}, RETRY_INTERVAL
            received, conflicts = report.get("received"), report.get("conflicts")
            if received:
                log.info("GitHub: %s recebeu: %s", name, ", ".join(received))
                upd["received"] = {"at": time.time(), "files": received}
            if (received or conflicts) and self.after_change:
                self.after_change(name)
            upd["checkedAt"] = time.time()
            with self.cv:
                if push and delay_on_error is not None:  # o commit não saiu: tenta de novo
                    self.due[name] = min(self.due.get(name, 1e18), time.time() + delay_on_error)
                st = self.status.setdefault(name, {})
                st.update(upd)
                if conflicts:
                    now = time.time()
                    st.setdefault("conflicts", []).extend(dict(c, id=uuid.uuid4().hex[:12], at=now) for c in conflicts)
                st["pending"] = name in self.due
                if name in self.due:
                    st["commitAt"] = self.due[name]
                self.busy = None
                self.cv.notify_all()
