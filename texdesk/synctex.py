# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Leitor mínimo de arquivos .synctex.gz para busca direta e inversa.

Coordenadas devolvidas em pontos PDF (bp), origem no canto superior esquerdo
da página — o mesmo sistema usado pelo visualizador no front-end.
"""

import gzip
import os
import re
from pathlib import Path

REC_RE = re.compile(r"^([\[\(hvxkg$])(\d+),(\d+):(-?\d+),(-?\d+)(?::(-?\d+),(-?\d+),(-?\d+))?")

_cache = {}

# faixa (em pontos PDF) em volta da linha de base em que um nó conta como "da linha clicada":
# o clique costuma cair no corpo das letras, acima da linha de base
LINE_BAND_ABOVE = 4
LINE_BAND_BELOW = 12


class SyncTex:
    def __init__(self, path: Path, project_root: Path, main_dir: Path):
        key = (str(path), path.stat().st_mtime)
        if key not in _cache:
            _cache.clear()
            _cache[key] = self._parse(path)
        self.inputs, self.records, self.scale = _cache[key]
        self.root = project_root.resolve()
        self.main_dir = main_dir.resolve()

    @staticmethod
    def _parse(path):
        inputs = {}
        records = []  # (page, tag, line, kind, x, y, w, h, d)
        unit, mag, xoff, yoff = 1.0, 1000.0, 0.0, 0.0
        page = 0
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if line.startswith("Input:"):
                    _, tag, name = line.split(":", 2)
                    inputs[int(tag)] = name
                elif line.startswith("Unit:"):
                    unit = float(line[5:])
                elif line.startswith("Magnification:"):
                    mag = float(line[14:])
                elif line.startswith("X Offset:"):
                    xoff = float(line[9:])
                elif line.startswith("Y Offset:"):
                    yoff = float(line[9:])
                elif line.startswith("{"):
                    page = int(line[1:])
                else:
                    m = REC_RE.match(line)
                    if m and page:
                        k, tag, ln, x, y, w, h, d = m.groups()
                        records.append(
                            (page, int(tag), int(ln), k, int(x), int(y), int(w or 0), int(h or 0), int(d or 0))
                        )
        # sp -> bp ; offsets já estão em sp
        f = unit * (mag / 1000.0) / 65536.0 * 72.0 / 72.27
        scale = (f, xoff * f / unit if unit else 0, yoff * f / unit if unit else 0)
        return inputs, records, scale

    def _bp(self, v, off=0.0):
        return v * self.scale[0] + off

    def _rel(self, name):
        p = Path(name)
        if not p.is_absolute():
            p = self.main_dir / p
        try:
            p = Path(os.path.normpath(p))
            return p.resolve().relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return None

    def _tags_for(self, file):
        want = file.replace("\\", "/").lstrip("./")
        tags = []
        for tag, name in self.inputs.items():
            rel = self._rel(name)
            if rel == want or (rel and rel.removesuffix(".tex") == want.removesuffix(".tex")):
                tags.append(tag)
        return tags

    def view(self, file, line):
        """Código -> PDF: retângulos (página, x, y, w, h) para a linha."""
        tags = set(self._tags_for(file))
        if not tags:
            return []
        recs = [r for r in self.records if r[1] in tags]
        if not recs:
            return []
        # usa a linha exata ou a mais próxima com conteúdo
        lines = sorted({r[2] for r in recs})
        best = min(lines, key=lambda ln: (abs(ln - line), ln < line))
        hits = [r for r in recs if r[2] == best]
        boxes = [r for r in hits if r[3] in "[(" and r[6] > 0] or hits
        page = boxes[0][0]
        out = []
        for r in boxes:
            if r[0] != page:
                continue
            x, y = self._bp(r[4], self.scale[1]), self._bp(r[5], self.scale[2])
            h = self._bp(r[7]) or 10
            w = self._bp(r[6]) or 20
            out.append({"page": page, "x": x, "y": y - h, "w": w, "h": h + self._bp(r[8])})
        return out[:6]

    def edit(self, page, x, y):
        """PDF -> código: arquivo e linha mais próximos do ponto clicado.

        Prefere os nós de conteúdo (glifos, kerns, glue, matemática) da mesma linha do
        clique: eles carregam o arquivo e a linha exatos de onde o texto veio. As caixas de
        linha não servem para isso, porque o TeX as atribui ao ponto em que o parágrafo
        termina (que pode ser outro arquivo, quando o texto vem de um \\input).
        """
        rels = {tag: self._rel(name) if name else None for tag, name in self.inputs.items()}
        best, best_score = None, None
        for r in self.records:
            if r[0] != page or r[2] <= 0 or not rels.get(r[1]):
                continue
            rx, ry = self._bp(r[4], self.scale[1]), self._bp(r[5], self.scale[2])
            if r[3] in "[(":
                if r[6] <= 0:
                    continue
                w, h, dd = self._bp(r[6]), self._bp(r[7]), self._bp(r[8])
                if not (rx <= x <= rx + w and ry - h <= y <= ry + dd):
                    continue
                score = (h + dd) / 20.0  # caixa que contém o clique: a menor ganha (~0,5 numa linha)
            elif -LINE_BAND_ABOVE <= ry - y <= LINE_BAND_BELOW:
                score = (abs(rx - x) + 3 * abs(ry - y)) * 0.005  # nó na linha clicada: prioridade
            else:
                score = abs(ry - y) + abs(rx - x) * 0.05 + 1  # nó em outra linha: só se nada melhor
            if best_score is None or score < best_score:
                best, best_score = r, score
        if not best:
            return None
        return {"file": rels[best[1]], "line": best[2]}
