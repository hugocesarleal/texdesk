# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

"""Gera docs/social-preview.png (1280x640), a imagem que aparece quando o link do
repositório é compartilhado. Uso: python scripts/previa_social.py (precisa do Pillow).

A imagem é enviada em GitHub > Settings > General > Social preview.
"""

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "social-preview.png"
W, H, S = 1280, 640, 3  # desenha 3x maior e reduz no fim (bordas suaves)

BG, BG2 = (13, 17, 23), (22, 30, 40)
GREEN, GREEN_SOFT = (19, 138, 54), (47, 180, 90)
TEXT, MUTED = (240, 244, 248), (150, 162, 178)


def font(names, size):
    """Primeira fonte encontrada (Windows, macOS ou Linux)."""
    dirs = [Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path("/usr/share/fonts")]
    for name in names:
        for d in dirs:
            hits = list(d.rglob(name)) if d.exists() else []
            if hits:
                return ImageFont.truetype(str(hits[0]), size * S)
    sys.exit(f"Fonte não encontrada: {names}")


def path_points(d):
    """Polígonos de um path SVG simples (M, h, v, H, V, l, z), como os do logo."""
    polys, cur, x, y = [], [], 0.0, 0.0
    for cmd, args in re.findall(r"([MhvHVlLz])([^MhvHVlLz]*)", d):
        nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", args)]
        if cmd == "M":
            x, y = nums[0], nums[1]
            cur = [(x, y)]
            for i in range(2, len(nums), 2):  # pares extras depois do M são linhas
                x, y = nums[i], nums[i + 1]
                cur.append((x, y))
        elif cmd in "hH":
            for n in nums:
                x = x + n if cmd == "h" else n
                cur.append((x, y))
        elif cmd in "vV":
            for n in nums:
                y = y + n if cmd == "v" else n
                cur.append((x, y))
        elif cmd in "lL":
            for i in range(0, len(nums), 2):
                x, y = (x + nums[i], y + nums[i + 1]) if cmd == "l" else (nums[i], nums[i + 1])
                cur.append((x, y))
        elif cmd == "z":
            polys.append(cur)
            if cur:
                x, y = cur[0]
            cur = []
    if cur:
        polys.append(cur)
    return polys


def draw_logo(img, ox, oy, size):
    """Desenha static/logo.svg (viewBox 96x96) na posição e tamanho dados (em pixels finais)."""
    svg = (ROOT / "static" / "logo.svg").read_text(encoding="utf-8")
    k = size * S / 96
    d = ImageDraw.Draw(img)

    def pt(px, py):
        return (ox * S + px * k, oy * S + py * k)

    d.rounded_rectangle([pt(0, 0), pt(96, 96)], radius=20 * k, fill=GREEN)
    d.rounded_rectangle([pt(18, 20), pt(78, 62)], radius=4 * k, fill="white")
    for p in path_points("M10 68h76l-6 10H16z"):
        d.polygon([pt(*q) for q in p], fill="white")
    group = svg[svg.index('<g fill="#138a36">') :]
    for dd in re.findall(r'd="([^"]+)"', group):
        for p in path_points(dd):
            d.polygon([pt(*q) for q in p], fill=GREEN)


def main():
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    # fundo: leve degradê diagonal e grade de pontos discreta
    for i in range(H * S):
        t = i / (H * S)
        c = tuple(int(BG[j] + (BG2[j] - BG[j]) * t) for j in range(3))
        d.line([(0, i), (W * S, i)], fill=c)
    for gx in range(40, W, 32):
        for gy in range(40, H, 32):
            d.ellipse([(gx * S - 2, gy * S - 2), (gx * S + 2, gy * S + 2)], fill=(30, 40, 52))
    d.rectangle([(0, 0), (W * S, 10 * S)], fill=GREEN)

    draw_logo(img, 96, 150, 220)

    bold = font(["segoeuib.ttf", "SF-Pro-Display-Bold.otf", "DejaVuSans-Bold.ttf"], 112)
    regular = font(["segoeui.ttf", "SF-Pro-Display-Regular.otf", "DejaVuSans.ttf"], 38)
    small = font(["seguisb.ttf", "segoeui.ttf", "DejaVuSans.ttf"], 22)
    mono = font(["CascadiaMono.ttf", "consola.ttf", "DejaVuSansMono.ttf"], 26)

    x = 372 * S
    d.text((x, 150 * S), "TexDesk", font=bold, fill=TEXT)
    d.text((x, 290 * S), "Editor LaTeX que roda no seu computador:", font=regular, fill=MUTED)
    d.text((x, 340 * S), "escreva, compile e veja o PDF lado a lado.", font=regular, fill=MUTED)

    # selos com os recursos principais
    cx, cy = x, 420 * S
    for label in ["Tectonic", "SyncTeX", "Funciona offline", "Histórico", "Google Drive"]:
        tw = d.textlength(label, font=small)
        box = [(cx, cy), (cx + tw + 32 * S, cy + 44 * S)]
        d.rounded_rectangle(box, radius=22 * S, fill=(27, 52, 37), outline=(40, 95, 60), width=2 * S)
        d.text((cx + 16 * S, cy + 8 * S), label, font=small, fill=GREEN_SOFT)
        cx += tw + 44 * S

    d.text((96 * S, 560 * S), "github.com/hugocesarleal/texdesk", font=mono, fill=MUTED)
    lic = "Código aberto · licença MIT"
    d.text((W * S - 96 * S - d.textlength(lic, font=mono), 560 * S), lic, font=mono, fill=MUTED)

    OUT.parent.mkdir(exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(f"{OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
