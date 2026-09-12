"""Generate the ZFA Achievement logo: a rounded, indigo-violet gradient tile
with a bold 'ZFA' monogram. Produces assets/logo.png (256), a few sizes, and
assets/logo.ico for the window / .exe icon.

    python make_logo.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

GRAD_A = (124, 92, 255)   # #7c5cff indigo
GRAD_B = (177, 76, 255)   # #b14cff violet


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "Arial.ttf"):
        path = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4  # supersample for smooth edges, then downscale
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # Diagonal gradient.
    grad = Image.new("RGB", (s, s))
    px = grad.load()
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * s)
            px[x, y] = tuple(int(GRAD_A[i] + (GRAD_B[i] - GRAD_A[i]) * t) for i in range(3))

    # Rounded-square mask.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255
    )
    img.paste(grad, (0, 0), mask)

    # Subtle glassy highlight on the top half, composited (not overwriting).
    hl = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle(
        [int(s * 0.06), int(s * 0.06), int(s * 0.94), int(s * 0.5)],
        radius=int(s * 0.16), fill=(255, 255, 255, 26),
    )
    hl.putalpha(Image.composite(hl.getchannel("A"), Image.new("L", (s, s), 0), mask))
    img = Image.alpha_composite(img, hl)

    draw = ImageDraw.Draw(img)
    # 'ZFA' monogram.
    zfa = _font(int(s * 0.34))
    draw.text(
        (s / 2, s * 0.42), "ZFA", font=zfa, fill=(255, 255, 255, 255), anchor="mm",
    )
    # Thin caption.
    cap = _font(int(s * 0.085))
    draw.text(
        (s / 2, s * 0.72), "ACHIEVEMENT", font=cap, fill=(233, 221, 255, 235),
        anchor="mm",
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    master = render(256)
    master.save(os.path.join(ASSETS, "logo.png"))
    render(64).save(os.path.join(ASSETS, "logo_64.png"))
    render(32).save(os.path.join(ASSETS, "logo_32.png"))

    icon_sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    master.save(os.path.join(ASSETS, "logo.ico"), sizes=icon_sizes)
    print("wrote assets/logo.png, logo_64.png, logo_32.png, logo.ico")


if __name__ == "__main__":
    main()
