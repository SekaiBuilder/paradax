"""Genera el icono de Agent OS: hexágono morado con núcleo, estilo squircle macOS.

Produce icon.iconset/ con todos los tamaños y lo compila a .icns con iconutil.
"""
from __future__ import annotations

import subprocess
from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / "icon.iconset"

BG = (13, 17, 23, 255)        # --bg del control center
ACCENT = (124, 58, 237, 255)  # --accent morado
SIZE = 1024


def rounded_rect(draw: ImageDraw.ImageDraw, size: int) -> None:
    margin = int(size * 0.09)  # macOS deja aire alrededor del squircle
    radius = int(size * 0.20)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin], radius=radius, fill=BG
    )


def hexagon(draw: ImageDraw.ImageDraw, size: int) -> None:
    cx, cy = size / 2, size / 2
    r = size * 0.27
    points = [
        (cx + r * sin(a), cy - r * cos(a))
        for a in [i * pi / 3 for i in range(6)]
    ]
    draw.polygon(points, outline=ACCENT, width=max(2, int(size * 0.035)))
    draw.ellipse(
        [cx - size * 0.075, cy - size * 0.075, cx + size * 0.075, cy + size * 0.075],
        fill=ACCENT,
    )


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded_rect(draw, size)
    hexagon(draw, size)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base = render(SIZE)
    sizes = {
        "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
    }
    for name, px in sizes.items():
        base.resize((px, px), Image.LANCZOS).save(OUT / name)
    icns = ROOT / "scripts" / "AgentOS.icns"
    subprocess.run(["iconutil", "-c", "icns", str(OUT), "-o", str(icns)], check=True)
    print(f"Icono: {icns}")


if __name__ == "__main__":
    main()
