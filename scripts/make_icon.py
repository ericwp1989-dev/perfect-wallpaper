"""Draw the app icon into assets/icon.ico and assets/icon.png.

A console badge: a dark hexagon with a holographic blue rim, a rising orange star,
and four corner brackets that frame it like a screen being fitted. Drawn large and
shrunk for each size, with heavier lines for the small sizes so it reads at 16 pixels.
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 1024
HULL = (9, 16, 26, 255)
RIM = (70, 200, 255, 255)
STAR = (255, 138, 31, 255)
CORE = (255, 214, 140, 255)


def hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(30, 390, 60)]


def badge(small: bool) -> Image.Image:
    rim, bracket = (52, 64) if small else (30, 40)
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.polygon(hexagon(512, 512, 500), fill=RIM)
    d.polygon(hexagon(512, 512, 500 - rim), fill=HULL)

    # the star, rising over a horizon, with a soft glow (left out at small sizes)
    cx, cy, r = 512, 640, 200
    if not small:
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((cx - r - 60, cy - r - 60, cx + r + 60, cy + r + 60), fill=STAR[:3] + (150,))
        glow = glow.filter(ImageFilter.GaussianBlur(48))
        inside = Image.new("L", image.size, 0)
        ImageDraw.Draw(inside).polygon(hexagon(512, 512, 500 - rim), fill=255)
        ImageDraw.Draw(inside).rectangle((0, cy, SIZE, SIZE), fill=0)  # no glow below the horizon
        glow.putalpha(ImageChops.multiply(glow.getchannel("A"), inside))
        image.alpha_composite(glow)
        d = ImageDraw.Draw(image)
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=STAR)
    d.pieslice((cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55), 180, 360, fill=CORE)
    d.rectangle((cx - r - 40, cy, cx + r + 40, cy + bracket * 0.6), fill=RIM)  # the horizon

    # corner brackets around the scene
    left, top, right, bottom = 236, 330, 788, 790
    arm = 110
    for x, y, dx, dy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
        d.line([(x, y + dy * arm), (x, y), (x + dx * arm, y)], fill=RIM, width=bracket, joint="curve")
    return image


def main():
    ASSETS.mkdir(exist_ok=True)
    large, small = badge(small=False), badge(small=True)
    sizes = {s: (small if s <= 32 else large).resize((s, s), Image.Resampling.LANCZOS)
             for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)}
    sizes[256].save(ASSETS / "icon.png")
    sizes[256].save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes], append_images=list(sizes.values()))
    print(f"Wrote {ASSETS / 'icon.ico'} and icon.png")


if __name__ == "__main__":
    main()
