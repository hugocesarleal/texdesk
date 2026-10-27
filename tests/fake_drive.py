# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Google Drive falso, em memória, com a mesma interface usada por drive_sync."""

import hashlib
import threading

from texdesk import drive_sync as ds


class FakeDrive:
    connected = True

    def __init__(self):
        self.files = {}  # id -> {name, parent, folder, data, trashed}
        self.calls = []  # registro das operações, para os testes conferirem
        self.verified = set()
        self._n = 0
        self._lock = threading.Lock()

    def _new(self, **kw):
        with self._lock:
            self._n += 1
            fid = f"id{self._n}"
            self.files[fid] = dict(trashed=False, **kw)
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
            self.files[file_id]["data"] = data
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
            }
            for fid, f in list(self.files.items())
            if f["parent"] == parent and not f["trashed"]
        ]

    def download(self, fid):
        return self.files[fid]["data"]

    # ---- ajudas para os testes
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
