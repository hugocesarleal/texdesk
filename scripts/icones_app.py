# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Gera os ícones PNG do aplicativo instalável (static/icons) a partir do static/logo.svg.

O logo só tem retângulos arredondados e caminhos de linhas retas, então é desenhado direto
com o Pillow (sem precisar de um renderizador de SVG). Rode de novo se o logo mudar:

    python scripts/icones_app.py
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "static" / "logo.svg"
OUT = ROOT / "static" / "icons"
NS = "{http://www.w3.org/2000/svg}"
SS = 4  # desenha 4x maior e reduz: bordas suaves


def polygons(d):
    """Polígonos de um caminho SVG com M/L/H/V/Z (absolutos e relativos)."""
    out, cur, x, y = [], [], 0.0, 0.0
    tokens = re.findall(r"[MLHVZmlhvz]|-?\d*\.?\d+", d)
    cmd, i = None, 0
    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    out.append(cur)
                cur = []
                continue
            continue
        n = float(t)
        if cmd in "Mm":
            if cur:
                out.append(cur)
            x, y = (x + n, y + float(tokens[i + 1])) if cmd == "m" else (n, float(tokens[i + 1]))
            cur = [(x, y)]
            i += 2
            cmd = "l" if cmd == "m" else "L"
        elif cmd in "Ll":
            x, y = (x + n, y + float(tokens[i + 1])) if cmd == "l" else (n, float(tokens[i + 1]))
            cur.append((x, y))
            i += 2
        elif cmd in "Hh":
            x = x + n if cmd == "h" else n
            cur.append((x, y))
            i += 1
        elif cmd in "Vv":
            y = y + n if cmd == "v" else n
            cur.append((x, y))
            i += 1
    if cur:
        out.append(cur)
    return out


def draw_logo(size, padding=0.0, background=None):
    """O logo em size x size; padding (fração) deixa margem, para o ícone "maskable"."""
    big = size * SS
    img = Image.new("RGBA", (big, big), background or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inner = big * (1 - 2 * padding)
    k, off = inner / 96, big * padding

    def pt(px, py):
        return (off + px * k, off + py * k)

    def walk(el, fill=None):
        fill = el.get("fill", fill)
        tag = el.tag.replace(NS, "")
        if tag == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h, rx = float(el.get("width")), float(el.get("height")), float(el.get("rx", 0))
            if background and padding and x == 0 and y == 0:
                return  # o fundo verde já é o próprio fundo do ícone "maskable"
            d.rounded_rectangle([pt(x, y), pt(x + w, y + h)], radius=rx * k, fill=fill)
        elif tag == "path":
            for poly in polygons(el.get("d")):
                d.polygon([pt(px, py) for px, py in poly], fill=fill)
        for child in el:
            walk(child, fill)

    walk(ET.parse(LOGO).getroot())
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw_logo(size).save(OUT / f"icon-{size}.png", optimize=True)
    # "maskable": o sistema recorta em círculo ou quadrado; o desenho fica na área segura (80%)
    draw_logo(512, padding=0.1, background=(19, 138, 54, 255)).save(OUT / "icon-maskable-512.png", optimize=True)
    draw_logo(180).save(OUT / "apple-touch-icon.png", optimize=True)
    for p in sorted(OUT.glob("*.png")):
        print(p.relative_to(ROOT), p.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
