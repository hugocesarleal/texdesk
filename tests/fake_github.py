# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""GitHub falso em memória, no lugar do urllib.request.urlopen do GitHubClient.

Imita o que o TexDesk usa da API: login pelo fluxo de dispositivo, /user, criação do
repositório e a Git Data API (refs, commits, árvores, blobs), com os mesmos sha dos blobs
que o git calcula (o cliente compara arquivos pelo sha, sem baixar).
"""

import base64
import hashlib
import io
import json
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
        self.head = None
        self.repo_exists = False
        self.authorized = False  # a pessoa já digitou o código?
        self.calls = []  # (método, caminho)
        self.offline = False
        self.rate_limited = 0  # quantas respostas de limite ainda dar
        self.before_ref_update = None  # gancho: simula outro computador enviando no meio

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

    def files(self):
        """{caminho: bytes} do branch, como estaria num clone."""
        tree = self.commits[self.head]["tree"]
        return {p: self.blobs[s] for p, s in self.flatten(tree).items()}

    def push_from_elsewhere(self, changes):
        """Outro computador faz um commit: changes = {caminho: bytes ou None (apagar)}."""
        files = self.flatten(self.commits[self.head]["tree"])
        for path, data in changes.items():
            if data is None:
                files.pop(path, None)
            else:
                sha = blob_sha(data)
                self.blobs[sha] = data
                files[path] = sha
        self.head = self.commit(files, "outro computador", self.head)

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
            return _Resp({"access_token": "gho_falso", "scope": "repo"})
        path = urllib.parse.urlparse(url).path
        query = urllib.parse.urlparse(url).query
        self.calls.append((method, path))
        if self.rate_limited:
            self.rate_limited -= 1
            raise _error(
                url, 403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Remaining": "0", "Retry-After": "1"}
            )
        data = json.loads(body) if body else None
        if path == "/user":
            return _Resp({"login": LOGIN})
        if path == f"/repos/{REPO}" and method == "GET":
            if not self.repo_exists:
                raise _error(url, 404, {"message": "Not Found"})
            return _Resp({"full_name": REPO, "default_branch": "main"})
        if path == "/user/repos" and method == "POST":
            assert data["private"] is True
            self.repo_exists = True
            readme = b"# texdesk-projetos\n"
            self.blobs[blob_sha(readme)] = readme
            self.head = self.commit({"README.md": blob_sha(readme)}, "Initial commit")
            return _Resp({"full_name": REPO, "default_branch": "main"})
        if path == f"/repos/{REPO}/commits":  # último commit que mexeu numa pasta
            folder = urllib.parse.parse_qs(query)["path"][0]
            has = any(p.startswith(folder + "/") for p in self.flatten(self.commits[self.head]["tree"]))
            return _Resp([{"commit": {"committer": {"date": "2026-01-02T03:04:05Z"}}}] if has else [])
        base = f"/repos/{REPO}/git/"
        assert path.startswith(base), path
        rest = path[len(base) :]
        if rest == "ref/heads/main":
            return _Resp({"object": {"sha": self.head}})
        if rest.startswith("commits/") and method == "GET":
            return _Resp({"tree": {"sha": self.commits[rest.split("/")[1]]["tree"]}})
        if rest.startswith("trees/") and method == "GET":
            sha = rest.split("/")[1]
            if "recursive=1" in query:
                return _Resp(
                    {
                        "tree": [{"path": p, "type": "blob", "sha": s} for p, s in self.flatten(sha).items()],
                        "truncated": False,
                    }
                )
            return _Resp({"tree": self.trees[sha]})
        if rest.startswith("blobs/") and method == "GET":
            return _Resp({"content": base64.b64encode(self.blobs[rest.split("/")[1]]).decode(), "encoding": "base64"})
        if rest == "blobs" and method == "POST":
            raw = base64.b64decode(data["content"])
            self.blobs[blob_sha(raw)] = raw
            return _Resp({"sha": blob_sha(raw)})
        if rest == "trees" and method == "POST":
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
        if rest == "commits" and method == "POST":
            sha = hashlib.sha1(f"{data['tree']}{data['parents']}{len(self.commits)}".encode()).hexdigest()
            self.commits[sha] = {"tree": data["tree"], "parents": data["parents"], "message": data["message"]}
            return _Resp({"sha": sha})
        if rest == "refs/heads/main" and method == "PATCH":
            if self.before_ref_update:
                hook, self.before_ref_update = self.before_ref_update, None
                hook()
            if self.commits[data["sha"]]["parents"] != [self.head]:
                raise _error(url, 422, {"message": "Update is not a fast forward"})
            self.head = data["sha"]
            return _Resp({"object": {"sha": self.head}})
        raise AssertionError(f"chamada não esperada: {method} {path}")

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]
