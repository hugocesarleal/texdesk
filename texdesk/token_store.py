# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Onde fica o token de acesso ao Google Drive.

Preferência: o cofre de senhas do sistema (Gerenciador de Credenciais no Windows, Chaves no
macOS, Secret Service/GNOME Keyring/KWallet no Linux), pela biblioteca keyring. Assim o
token não fica num arquivo que qualquer programa ou cópia da pasta poderia levar.

Sem cofre disponível (ex.: Linux sem interface gráfica), fica em .drive/token.json com
permissão só para o dono. Um token.json antigo é migrado para o cofre automaticamente.
TEXDESK_KEYRING=0 desliga o cofre (os testes usam isso para nunca tocar no cofre real).
"""

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "TexDesk"


def _system_keyring():
    """O cofre do sistema, ou None se não houver um utilizável."""
    if os.environ.get("TEXDESK_KEYRING", "1") == "0":
        return None
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    kr = keyring.get_keyring()
    # sem cofre de verdade, o keyring devolve um backend que só gera erros
    if isinstance(kr, fail.Keyring) or getattr(kr, "priority", 0) <= 0:
        return None
    return kr


class TokenStore:
    def __init__(self, state_dir: Path, backend="auto"):
        self.file = state_dir / "token.json"
        # uma entrada por pasta de dados: duas instalações do TexDesk não se misturam
        self.account = f"google-drive:{state_dir.resolve()}"
        self.keyring = _system_keyring() if backend == "auto" else backend
        self._lock = threading.Lock()
        self._cache = None
        self._loaded = False
        self._migrate_file()

    @property
    def location(self):
        """'keyring' ou 'file': onde o token está guardado (mostrado no painel do Drive)."""
        return "keyring" if self.keyring is not None else "file"

    def load(self):
        with self._lock:
            if not self._loaded:
                self._cache = self._read()
                self._loaded = True
            return dict(self._cache) if self._cache else None

    def save(self, tok):
        with self._lock:
            data = json.dumps(tok)
            if self.keyring is not None:
                try:
                    self.keyring.set_password(SERVICE, self.account, data)
                except Exception as e:  # cofre travado, cheio, sem permissão…
                    log.warning("Não foi possível usar o cofre de senhas (%s); o token vai para %s", e, self.file)
                    self.keyring = None
            if self.keyring is None:
                self._write_file(data)
            self._cache, self._loaded = dict(tok), True

    def delete(self):
        with self._lock:
            if self.keyring is not None:
                try:
                    self.keyring.delete_password(SERVICE, self.account)
                except Exception:  # já não existia
                    pass
            self.file.unlink(missing_ok=True)
            self._cache, self._loaded = None, True

    # ---------------------------------------------------------------- interno
    def _read(self):
        if self.keyring is not None:
            try:
                data = self.keyring.get_password(SERVICE, self.account)
                if data:
                    return json.loads(data)
            except Exception as e:
                log.warning("Não foi possível ler o cofre de senhas: %s", e)
        if self.file.exists():
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except ValueError:
                return None
        return None

    def _write_file(self, data):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(data, encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.file, 0o600)  # só o dono lê

    def _migrate_file(self):
        """Move um token.json antigo para o cofre, apagando o arquivo só se o cofre confirmar."""
        if self.keyring is None or not self.file.exists():
            return
        try:
            data = self.file.read_text(encoding="utf-8")
            json.loads(data)
            self.keyring.set_password(SERVICE, self.account, data)
            if self.keyring.get_password(SERVICE, self.account) != data:
                raise RuntimeError("o cofre não devolveu o mesmo token")
        except Exception as e:
            log.warning("Token do Drive mantido em %s (cofre de senhas indisponível: %s)", self.file, e)
            return
        self.file.unlink()
        log.info("Token do Google Drive movido para o cofre de senhas do sistema")
