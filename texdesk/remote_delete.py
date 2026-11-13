# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Exclusões no Google Drive e no GitHub de projetos que saíram de vez da lixeira do TexDesk.

Quando um projeto é apagado de vez (lixeira esvaziada, item apagado ou depois de 30 dias), o
que ele tinha no Drive e no GitHub também some. Sem internet nessa hora, ou sem a permissão
necessária, o pedido fica guardado em disco (FILE) e é feito depois: a fila tenta de novo de
tempos em tempos e também logo ao abrir o TexDesk.

Cada item é {"kind": ..., ...}; o que fazer com cada tipo vem de fora (handlers), e cada
handler devolve True (feito, ou nada mais a fazer) ou False (esperar: ex., desconectado).
"""

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

RETRY = 60.0  # segundos entre tentativas, para o que falhou


class RemoteDeletes:
    def __init__(self, file: Path, handlers: dict):
        self.file = file
        self.handlers = handlers  # tipo -> função(item) -> bool
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.errors = {}  # chave do item -> última mensagem de erro
        self.thread = threading.Thread(target=self._run, daemon=True, name="remote-delete")
        self.thread.start()
        if self.items():
            self.wake.set()

    @staticmethod
    def key(item):
        return json.dumps(item, sort_keys=True)

    def items(self):
        with self.lock:
            try:
                return json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return []

    def _save(self, items):
        tmp = self.file.with_name(self.file.name + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.file)

    def add(self, items):
        if not items:
            return
        with self.lock:
            try:
                current = json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = []
            keys = {self.key(i) for i in current}
            current += [i for i in items if self.key(i) not in keys]
            self._save(current)
        self.wake.set()

    def retry_now(self):
        self.wake.set()

    def _done(self, item):
        with self.lock:
            try:
                current = json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = []
            self._save([i for i in current if self.key(i) != self.key(item)])
        self.errors.pop(self.key(item), None)

    def run_once(self):
        """Tenta cada item uma vez. Devolve quantos ficaram para depois."""
        left = 0
        for item in self.items():
            handler = self.handlers.get(item.get("kind"))
            if handler is None:
                self._done(item)
                continue
            try:
                done = handler(item)
            except Exception as e:  # rede, permissão: fica para depois
                log.warning("Exclusão remota (%s) adiada: %s", item.get("kind"), e)
                self.errors[self.key(item)] = str(e)
                done = False
            if done:
                log.info("Exclusão remota feita: %s", item)
                self._done(item)
            else:
                left += 1
        return left

    def _run(self):
        while True:
            self.wake.wait(timeout=RETRY)
            self.wake.clear()
            if self.items():
                self.run_once()
            time.sleep(0.1)
