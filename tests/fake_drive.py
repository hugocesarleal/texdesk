# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Google Drive falso, em memória, com a mesma interface usada por drive_sync."""

import copy
import hashlib
import itertools
import threading
import time
from datetime import datetime, timezone

from texdesk import drive_sync as ds


class FakeDrive:
    connected = True

    def __init__(self, state_dir=None):
        self.dir = state_dir  # como DriveClient.dir: onde fica a versão comum dos arquivos (base/)
        self.files = {}  # id -> {name, parent, folder, data, trashed, modified}
        self.calls = []  # registro das operações, para os testes conferirem
        self.verified = set()
        self._ids = itertools.count(1)  # compartilhado com outro_computador()
        self._lock = threading.Lock()

    def _new(self, **kw):
        with self._lock:
            fid = f"id{next(self._ids)}"
            self.files[fid] = dict(trashed=False, modified=time.time(), **kw)
        return fid

    # ---- mesma interface de DriveClient
    def root_folder(self):
        return self.find_child("root", ds.ROOT_FOLDER_NAME, True) or self.create_folder(ds.ROOT_FOLDER_NAME, "root")

    def exists(self, fid):
        self.calls.append(("exists",))
        return fid in self.files and not self.files[fid]["trashed"]

    def find_child(self, parent, name, folder=None):
        for fid, f in self.files.items():
            if (
                f["parent"] == parent
                and f["name"] == name
                and not f["trashed"]
                and (folder is None or f["folder"] == folder)
            ):
                return fid
        return None

    def create_folder(self, name, parent=None):
        self.calls.append(("mkdir", name))
        return self._new(name=name, parent=parent or "root", folder=True, data=None)

    def rename(self, fid, name):
        self.calls.append(("rename", name))
        self.files[fid]["name"] = name

    def upload(self, data, name, parent, file_id=None):
        self.calls.append(("upload", name, bool(file_id)))
        # como o cliente real: arquivo (ou pasta de destino) na lixeira conta como inexistente
        if file_id and self.files[file_id]["trashed"]:
            raise ds.DriveError("Drive 404: File not found")
        if not file_id and self.files.get(parent, {}).get("trashed"):
            raise ds.DriveError("Drive 404: File not found (parent)")
        if file_id:
            self.files[file_id].update(data=data, modified=time.time())
        else:
            file_id = self._new(name=name, parent=parent, folder=False, data=data)
        return file_id, hashlib.md5(data).hexdigest()

    def trash(self, fid):
        self.calls.append(("trash", self.files[fid]["name"]))
        self.files[fid]["trashed"] = True

    def list_children(self, parent):
        return [
            {
                "id": fid,
                "name": f["name"],
                "mimeType": ds.FOLDER_MIME if f["folder"] else "text/plain",
                "md5Checksum": hashlib.md5(f["data"]).hexdigest() if f["data"] is not None else None,
                "modifiedTime": datetime.fromtimestamp(f["modified"], timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            for fid, f in list(self.files.items())
            if f["parent"] == parent and not f["trashed"]
        ]

    def download(self, fid):
        f = self.files.get(fid)
        self.calls.append(("download", f["name"] if f else None))
        if not f:
            raise ds.DriveError("Drive 404: File not found")
        return f["data"]

    # ---- ajudas para os testes
    def outro_computador(self, state_dir):
        """O mesmo Drive visto de outro computador: mesmos arquivos, estado local próprio."""
        other = copy.copy(self)  # files, calls e ids continuam compartilhados
        other.dir = state_dir
        other.verified = set()
        return other

    def trash_tree(self, fid):
        """Lixeira em cascata, como no Drive: a pasta leva o conteúdo junto."""
        self.files[fid]["trashed"] = True
        for cid, f in self.files.items():
            if f["parent"] == fid:
                self.trash_tree(cid)

    def tree(self, fid, prefix=""):
        """{caminho: conteúdo} de tudo que não está na lixeira dentro da pasta."""
        out = {}
        for c in self.list_children(fid):
            if c["mimeType"] == ds.FOLDER_MIME:
                out.update(self.tree(c["id"], prefix + c["name"] + "/"))
            else:
                out[prefix + c["name"]] = self.files[c["id"]]["data"]
        return out

    def uploads(self):
        return [c for c in self.calls if c[0] == "upload"]

    def put(self, folder_id, path, data):
        """Grava um arquivo no Drive como outro computador faria (cria as subpastas)."""
        parent = folder_id
        *dirs, name = path.split("/")
        for x in dirs:
            parent = self.find_child(parent, x, True) or self.create_folder(x, parent)
        fid = self.find_child(parent, name, False)
        self.upload(data, name, parent, fid)
