# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""GitHub falso em memória, no lugar do urllib.request.urlopen do GitHubClient.

Imita o que o TexDesk usa da API: login pelo fluxo de dispositivo, /user, criação de
repositórios, a Git Data API (refs, commits, árvores, blobs, com os mesmos sha de blob que o
git calcula) e o compartilhamento (colaboradores, convites, permissões). Vários usuários: cada
um entra com o próprio login (gh.login_as), e o token diz quem está chamando.
"""

import base64
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse

from texdesk.github_sync import blob_sha

LOGIN = "fulano"
REPO = f"{LOGIN}/texdesk-projetos"


class _Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode() if body is not None else b""

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _error(url, code, body, headers=None):
    return urllib.error.HTTPError(url, code, "erro", headers or {}, io.BytesIO(json.dumps(body).encode()))


class FakeGitHub:
    def __init__(self):
        self.blobs, self.trees, self.commits = {}, {}, {}
        self.heads = {}  # dono/nome -> commit do branch main
        self.repos = {}  # dono/nome -> {description, collaborators: {login: write}}
        self.invites = {}  # id -> {repo, login, write, inviter}
        self.users = {LOGIN, "beltrana", "ciclano"}  # contas que existem no GitHub falso
        self.login_as = LOGIN  # quem está digitando o código do login
        self.authorized = False  # a pessoa já digitou o código?
        self.calls = []  # (método, caminho)
        self.offline = False
        self.rate_limited = 0  # quantas respostas de limite ainda dar
        self.before_ref_update = None  # gancho: simula outro computador enviando no meio
        self.scope = "repo,delete_repo"  # o que o GitHub devolve no login (antes: só "repo")

    # ---- repositório principal (os testes antigos usam head/files direto)
    @property
    def head(self):
        return self.heads.get(REPO)

    @head.setter
    def head(self, sha):
        self.heads[REPO] = sha

    @property
    def repo_exists(self):
        return REPO in self.repos

    # ---- objetos do git
    def _tree_sha(self, entries):
        canon = json.dumps(sorted((e["path"], e["mode"], e["type"], e["sha"]) for e in entries)).encode()
        return hashlib.sha1(b"tree" + canon).hexdigest()

    def put_tree(self, entries):
        sha = self._tree_sha(entries)
        self.trees[sha] = entries
        return sha

    def flatten(self, tree_sha, prefix=""):
        out = {}
        for e in self.trees.get(tree_sha, []):
            path = prefix + e["path"]
            if e["type"] == "tree":
                out.update(self.flatten(e["sha"], path + "/"))
            else:
                out[path] = e["sha"]
        return out

    def build(self, files):
        """Árvore aninhada a partir de {caminho: sha do blob}."""
        here, subs = [], {}
        for path, sha in files.items():
            if "/" in path:
                top, rest = path.split("/", 1)
                subs.setdefault(top, {})[rest] = sha
            else:
                here.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
        for top, inner in subs.items():
            here.append({"path": top, "mode": "040000", "type": "tree", "sha": self.build(inner)})
        return self.put_tree(here)

    def commit(self, files, message="commit", parent=None):
        tree = self.build(files)
        sha = hashlib.sha1(f"{tree}{parent}{message}{len(self.commits)}".encode()).hexdigest()
        self.commits[sha] = {"tree": tree, "parents": [parent] if parent else [], "message": message}
        return sha

    def files(self, repo=REPO):
        """{caminho: bytes} do branch, como estaria num clone."""
        tree = self.commits[self.heads[repo]]["tree"]
        return {p: self.blobs[s] for p, s in self.flatten(tree).items()}

    def push_from_elsewhere(self, changes, repo=REPO):
        """Outro computador faz um commit: changes = {caminho: bytes ou None (apagar)}."""
        head = self.heads[repo]
        files = self.flatten(self.commits[head]["tree"]) if head else {}  # (repositório vazio)
        for path, data in changes.items():
            if data is None:
                files.pop(path, None)
            else:
                sha = blob_sha(data)
                self.blobs[sha] = data
                files[path] = sha
        self.heads[repo] = self.commit(files, "outro computador", head)

    def create_repo(self, owner, name, description="", init=True):
        full = f"{owner}/{name}"
        self.repos[full] = {"description": description, "collaborators": {}}
        self.heads[full] = None  # vazio, como o GitHub sem auto_init
        if init:
            readme = f"# {name}\n".encode()
            self.blobs[blob_sha(readme)] = readme
            self.heads[full] = self.commit({"README.md": blob_sha(readme)}, "Initial commit")
        return full

    # ---- acesso
    def _access(self, user, full):
        """None (não vê), "read" ou "write"."""
        if full not in self.repos:
            return None
        if full.split("/")[0] == user:
            return "write"
        w = self.repos[full]["collaborators"].get(user)
        return None if w is None else ("write" if w else "read")

    # ---- urlopen
    def __call__(self, req, timeout=None):
        url = req.full_url
        method = req.get_method()
        body = req.data
        if self.offline:
            raise urllib.error.URLError("sem rede")
        if url.startswith("https://github.com/login/"):
            form = dict(urllib.parse.parse_qsl(body.decode()))
            if url.endswith("/device/code"):
                return _Resp(
                    {
                        "device_code": "dev123",
                        "user_code": "ABCD-1234",
                        "verification_uri": "https://github.com/login/device",
                        "expires_in": 900,
                        "interval": 0,
                    }
                )
            assert form["device_code"] == "dev123"
            if not self.authorized:
                return _Resp({"error": "authorization_pending"})
            return _Resp({"access_token": f"gho_{self.login_as}", "scope": self.scope})
        user = (req.get_header("Authorization") or "").removeprefix("Bearer gho_")
        parsed = urllib.parse.urlparse(url)
        path, query = parsed.path, parsed.query
        self.calls.append((method, path))
        if self.rate_limited:
            self.rate_limited -= 1
            raise _error(
                url, 403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Remaining": "0", "Retry-After": "1"}
            )
        data = json.loads(body) if body else None

        if path == "/user":
            return _Resp({"login": user})
        if path == "/user/repos" and method == "GET":
            return _Resp(
                [
                    {"full_name": f, "name": f.split("/")[1], "description": r["description"]}
                    for f, r in self.repos.items()
                    if self._access(user, f)
                ]
            )
        if path == "/user/repos" and method == "POST":
            assert data["private"] is True
            full = f"{user}/{data['name']}"
            if full in self.repos:
                raise _error(url, 422, {"message": "name already exists on this account"})
            self.create_repo(user, data["name"], data.get("description", ""), data.get("auto_init", False))
            return _Resp({"full_name": full, "default_branch": "main"})
        if path == "/user/repository_invitations" and method == "GET":
            mine = [(i, v) for i, v in self.invites.items() if v["login"] == user]
            return _Resp(
                [
                    {
                        "id": i,
                        "repository": {
                            "full_name": v["repo"],
                            "name": v["repo"].split("/")[1],
                            "description": self.repos[v["repo"]]["description"],
                        },
                        "inviter": {"login": v["inviter"]},
                        "permissions": "write" if v["write"] else "read",
                    }
                    for i, v in mine
                ]
            )
        m = re.fullmatch(r"/user/repository_invitations/(\d+)", path)
        if m:
            inv = self.invites.get(int(m.group(1)))
            if not inv or inv["login"] != user:
                raise _error(url, 404, {"message": "Not Found"})
            del self.invites[int(m.group(1))]
            if method == "PATCH":  # aceitar
                self.repos[inv["repo"]]["collaborators"][user] = inv["write"]
            return _Resp(None)

        m = re.fullmatch(r"/repos/([^/]+/[^/]+)(/.*)?", path)
        assert m, path
        full, rest = m.group(1), m.group(2) or ""
        access = self._access(user, full)
        if access is None:
            raise _error(url, 404, {"message": "Not Found"})
        repo = self.repos[full]
        if not rest and method == "DELETE":  # apagar o repositório: só o dono, com delete_repo
            if full.split("/")[0] != user or "delete_repo" not in self.scope:
                raise _error(url, 403, {"message": "Must have admin rights to Repository."})
            del self.repos[full], self.heads[full]
            self.invites = {i: v for i, v in self.invites.items() if v["repo"] != full}
            return _Resp(None)
        if not rest:
            return _Resp({"full_name": full, "default_branch": "main", "permissions": {"push": access == "write"}})
        if rest == "/commits":  # último commit que mexeu numa pasta
            folder = urllib.parse.parse_qs(query)["path"][0]
            has = any(p.startswith(folder + "/") for p in self.flatten(self.commits[self.heads[full]]["tree"]))
            return _Resp([{"commit": {"committer": {"date": "2026-01-02T03:04:05Z"}}}] if has else [])
        if rest == "/collaborators" and method == "GET":
            return _Resp([{"login": u, "permissions": {"push": w}} for u, w in repo["collaborators"].items()])
        m = re.fullmatch(r"/collaborators/([^/]+)", rest)
        if m:
            who = m.group(1)
            if method == "DELETE":  # o dono remove alguém, ou a pessoa sai do projeto
                if access != "write" and who != user:
                    raise _error(url, 403, {"message": "Forbidden"})
                repo["collaborators"].pop(who, None)
                return _Resp(None)
            assert method == "PUT" and full.split("/")[0] == user
            if who not in self.users:
                raise _error(url, 404, {"message": "Not Found"})
            write = data["permission"] == "push"
            if who in repo["collaborators"]:
                repo["collaborators"][who] = write
                return _Resp(None)  # 204: já tinha acesso, só a permissão mudou
            iid = len(self.invites) + 1000
            self.invites[iid] = {"repo": full, "login": who, "write": write, "inviter": user}
            return _Resp({"id": iid})
        if rest == "/invitations":
            return _Resp(
                [
                    {"id": i, "invitee": {"login": v["login"]}, "permissions": "write" if v["write"] else "read"}
                    for i, v in self.invites.items()
                    if v["repo"] == full
                ]
            )
        m = re.fullmatch(r"/invitations/(\d+)", rest)
        if m:
            inv = self.invites[int(m.group(1))]
            if method == "DELETE":
                del self.invites[int(m.group(1))]
            else:
                inv["write"] = data["permissions"] == "write"
            return _Resp(None)
        m = re.fullmatch(r"/contents/(.+)", rest)
        if m and method == "GET":
            path_in = urllib.parse.unquote(m.group(1))
            files = self.flatten(self.commits[self.heads[full]]["tree"]) if self.heads[full] else {}
            if path_in not in files:
                raise _error(url, 404, {"message": "Not Found"})
            return _Resp({"sha": files[path_in], "path": path_in})
        if m and method == "PUT":
            if access != "write":
                raise _error(url, 403, {"message": "Forbidden"})
            self.push_from_elsewhere({urllib.parse.unquote(m.group(1)): base64.b64decode(data["content"])}, full)
            return _Resp({"commit": {"sha": self.heads[full]}})

        assert rest.startswith("/git/"), path
        git = rest[len("/git/") :]
        if git == "ref/heads/main":
            return _Resp({"object": {"sha": self.heads[full]}})
        if git.startswith("commits/") and method == "GET":
            return _Resp({"tree": {"sha": self.commits[git.split("/")[1]]["tree"]}})
        if git.startswith("trees/") and method == "GET":
            sha = git.split("/")[1]
            if "recursive=1" in query:
                tree = [{"path": p, "type": "blob", "sha": s} for p, s in self.flatten(sha).items()]
                return _Resp({"tree": tree, "truncated": False})
            return _Resp({"tree": self.trees[sha]})
        if git.startswith("blobs/") and method == "GET":
            return _Resp({"content": base64.b64encode(self.blobs[git.split("/")[1]]).decode(), "encoding": "base64"})
        if access != "write":  # só leitura: o GitHub não deixa escrever
            raise _error(url, 404, {"message": "Not Found"})
        if git == "blobs" and method == "POST":
            raw = base64.b64decode(data["content"])
            self.blobs[blob_sha(raw)] = raw
            return _Resp({"sha": blob_sha(raw)})
        if git == "trees" and method == "POST":
            files = self.flatten(data["base_tree"])
            for e in data["tree"]:
                if e.get("type") == "tree" and e.get("sha") is None:  # apaga a pasta inteira
                    files = {p: s for p, s in files.items() if not p.startswith(e["path"] + "/")}
                elif "content" in e:
                    raw = e["content"].encode("utf-8")
                    self.blobs[blob_sha(raw)] = raw
                    files[e["path"]] = blob_sha(raw)
                elif e.get("sha") is None:
                    if e["path"] not in files:
                        raise _error(url, 422, {"message": "tree.path does not exist"})
                    files.pop(e["path"])
                else:
                    assert e["sha"] in self.blobs, "blob inexistente"
                    files[e["path"]] = e["sha"]
            sha = self.build(files)
            return _Resp({"sha": sha, "tree": self.trees[sha]})  # como o GitHub: a raiz da árvore nova
        if git == "commits" and method == "POST":
            sha = hashlib.sha1(f"{data['tree']}{data['parents']}{len(self.commits)}".encode()).hexdigest()
            self.commits[sha] = {"tree": data["tree"], "parents": data["parents"], "message": data["message"]}
            return _Resp({"sha": sha})
        if git == "refs/heads/main" and method == "PATCH":
            if self.before_ref_update:
                hook, self.before_ref_update = self.before_ref_update, None
                hook()
            if self.commits[data["sha"]]["parents"] != [self.heads[full]]:
                raise _error(url, 422, {"message": "Update is not a fast forward"})
            self.heads[full] = data["sha"]
            return _Resp({"object": {"sha": self.heads[full]}})
        raise AssertionError(f"chamada não esperada: {method} {path}")

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]
