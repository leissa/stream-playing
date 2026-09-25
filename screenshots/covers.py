"""Procedural album art for the demo library, one style per album."""

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 800
SERIF = "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf"
SERIF_I = "/usr/share/fonts/liberation/LiberationSerif-Italic.ttf"
SANS_B = "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"
SANS = "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def vgrad(top, bottom, size=S):
    t = np.linspace(0, 1, size)[:, None, None]
    a, b = np.array(hexrgb(top)), np.array(hexrgb(bottom))
    arr = a * (1 - t) + b * t
    return np.repeat(arr, size, axis=1)


def radial(center, inner, outer, radius, size=S):
    y, x = np.mgrid[0:size, 0:size]
    d = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2) / radius
    t = np.clip(d, 0, 1)[..., None]
    a, b = np.array(hexrgb(inner)), np.array(hexrgb(outer))
    return a * (1 - t) + b * t


def grain(img, amount=10, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.asarray(img).astype(float)
    arr += rng.normal(0, amount, arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def img(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def text(draw, xy, s, font, size, fill, anchor="la", spacing=0):
    f = ImageFont.truetype(font, size)
    if spacing:
        x, y = xy
        total = sum(draw.textlength(c, font=f) + spacing for c in s) - spacing
        if anchor[0] == "m":
            x -= total / 2
        for c in s:
            draw.text((x, y), c, font=f, fill=fill, anchor="l" + anchor[1])
            x += draw.textlength(c, font=f) + spacing
    else:
        draw.text(xy, s, font=f, fill=fill, anchor=anchor)


def synthwave():
    im = img(vgrad("#120a2e", "#ff4f8b"))
    d = ImageDraw.Draw(im)
    sun = Image.new("L", (S, S), 0)
    ImageDraw.Draw(sun).ellipse((220, 170, 580, 530), fill=255)
    sun_col = img(vgrad("#ffe45c", "#ff2d75"))
    horizon = 470
    mask = np.asarray(sun).copy()
    for i, y in enumerate(range(360, horizon, 22)):
        mask[y:y + 4 + i * 2, :] = 0
    im.paste(sun_col, (0, 0), Image.fromarray(mask))
    glow = Image.new("RGB", (S, S), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse((190, 140, 610, 560), fill=(120, 20, 90))
    im = Image.blend(im, Image.composite(glow, im, Image.new("L", (S, S), 0)), 0)
    d = ImageDraw.Draw(im)
    d.rectangle((0, horizon, S, S), fill=(16, 6, 40))
    for i in range(-14, 15):
        d.line((S / 2 + i * 18, horizon, S / 2 + i * 150, S), fill=(0, 230, 255), width=2)
    y, step = horizon, 6
    while y < S:
        d.line((0, y, S, y), fill=(0, 230, 255), width=2)
        step *= 1.35
        y += step
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    d = ImageDraw.Draw(im)
    text(d, (S / 2, 80), "NIGHT DRIVE ATLAS", SANS_B, 44, (255, 255, 255), "mm", 6)
    return grain(im, 6, 1)


def mountains():
    im = img(vgrad("#f6c28b", "#d3542f"))
    d = ImageDraw.Draw(im)
    d.ellipse((470, 180, 600, 310), fill=(255, 236, 200))
    rng = random.Random(4)
    cols = ["#b0452e", "#7f2f28", "#51201f", "#2a1216"]
    for layer, col in enumerate(cols):
        base = 360 + layer * 110
        pts = [(0, S)]
        phase = rng.random() * 10
        for x in range(0, S + 10, 10):
            h = (math.sin(x / (90 + layer * 20) + phase) * 45
                 + math.sin(x / 37 + phase * 2) * 12)
            pts.append((x, base + h))
        pts.append((S, S))
        d.polygon(pts, fill=hexrgb(col))
    for _ in range(9):
        x, y = rng.randint(80, 720), rng.randint(560, 760)
        d.polygon([(x, y - 60), (x - 16, y), (x + 16, y)], fill=(24, 10, 12))
    text(d, (60, 70), "Hollow Pines", SERIF_I, 50, (60, 20, 18))
    text(d, (60, 130), "EMBER & ASH", SANS, 26, (60, 20, 18), spacing=8)
    return grain(im, 9, 2)


def rings():
    im = Image.new("RGB", (S, S), hexrgb("#ece7df"))
    d = ImageDraw.Draw(im)
    for i in range(28, 0, -1):
        r = i * 13
        cx, cy = 400 + i * 4, 420 - i * 3
        col = hexrgb("#1f2a44") if i % 2 else hexrgb("#ece7df")
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    d.ellipse((380, 405, 420, 445), fill=hexrgb("#e2553d"))
    text(d, (60, 720), "MIRA KESSLER — QUIET MACHINES", SANS, 22, hexrgb("#1f2a44"), spacing=3)
    return grain(im, 5, 3)


def bauhaus():
    im = Image.new("RGB", (S, S), hexrgb("#f1e9d8"))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 400, 400), fill=hexrgb("#1d3b72"))
    d.pieslice((400, 0, 1200, 800), 90, 180, fill=hexrgb("#e94b35"))
    d.ellipse((120, 120, 280, 280), fill=hexrgb("#f4c430"))
    d.rectangle((0, 400, 400, 800), fill=hexrgb("#f1e9d8"))
    d.polygon([(0, 800), (400, 800), (0, 400)], fill=hexrgb("#222222"))
    for i in range(6):
        d.rectangle((460 + i * 50, 80, 480 + i * 50, 340), fill=hexrgb("#222222"))
    text(d, (440, 700), "THE PAPER", SANS_B, 38, hexrgb("#222222"))
    text(d, (440, 745), "SATELLITES", SANS_B, 38, hexrgb("#222222"))
    return grain(im, 6, 4)


def waves():
    im = img(vgrad("#0d2b3e", "#0a1a26"))
    d = ImageDraw.Draw(im)
    for k in range(40):
        y0 = 120 + k * 15
        amp = 30 * math.exp(-((k - 20) / 10) ** 2) + 3
        pts = [(x, y0 + math.sin(x / 50 + k * 0.3) * amp) for x in range(60, 741, 4)]
        shade = int(120 + 135 * (k / 40))
        d.line(pts, fill=(shade, 220, 230), width=2)
    text(d, (S / 2, 60), "SALTWATER CHOIR", SANS, 24, (200, 235, 240), "mm", 10)
    text(d, (S / 2, 740), "Tidelines", SERIF_I, 44, (200, 235, 240), "mm")
    return grain(im, 5, 5)


def duotone_blobs(seed, c1, c2, bg, title, artist):
    rng = random.Random(seed)
    im = Image.new("RGB", (S, S), hexrgb(bg))
    layer = Image.new("RGB", (S, S), hexrgb(bg))
    d = ImageDraw.Draw(layer)
    for _ in range(7):
        r = rng.randint(140, 320)
        x, y = rng.randint(0, S), rng.randint(0, S)
        d.ellipse((x - r, y - r, x + r, y + r), fill=hexrgb(rng.choice([c1, c2])))
    im = layer.filter(ImageFilter.GaussianBlur(90))
    d = ImageDraw.Draw(im)
    text(d, (60, 690), title, SERIF, 58, (255, 255, 255))
    text(d, (62, 750), artist.upper(), SANS, 20, (255, 255, 255), spacing=6)
    return grain(im, 12, seed)


def jazz():
    im = Image.new("RGB", (S, S), hexrgb("#10233f"))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, S, 300), fill=hexrgb("#1a5fb4"))
    text(d, (50, 60), "BLUE", SANS_B, 150, hexrgb("#f5f0e1"))
    text(d, (50, 200), "HOUR", SANS_B, 90, hexrgb("#10233f"))
    text(d, (340, 212), "SESSIONS", SANS, 60, hexrgb("#f5f0e1"))
    for i in range(12):
        x = 60 + i * 58
        h = 180 + (i * 37) % 200
        d.rectangle((x, 760 - h, x + 30, 760), fill=hexrgb("#e8a33d" if i % 3 == 0 else "#f5f0e1"))
    text(d, (50, 330), "Juniper Oake Quartet", SERIF_I, 36, hexrgb("#e8a33d"))
    return grain(im, 7, 7)


def desert():
    im = img(vgrad("#2b6f8c", "#e8b075"))
    d = ImageDraw.Draw(im)
    d.ellipse((300, 240, 500, 440), fill=hexrgb("#f7e3b5"))
    for layer, col in enumerate(["#c7743b", "#a3552c", "#6e3620"]):
        base = 470 + layer * 100
        pts = [(0, S)] + [(x, base + math.sin(x / 140 + layer * 2) * 50) for x in range(0, S + 5, 5)] + [(S, S)]
        d.polygon(pts, fill=hexrgb(col))
    text(d, (S / 2, 100), "KESTREL & STONE", SERIF, 44, hexrgb("#f7e3b5"), "mm", 4)
    text(d, (S / 2, 155), "copper sky", SERIF_I, 32, hexrgb("#f7e3b5"), "mm")
    return grain(im, 8, 8)


def winter():
    im = img(vgrad("#dfe7ee", "#9fb3c4"))
    d = ImageDraw.Draw(im)
    rng = random.Random(10)
    for _ in range(220):
        x, y, r = rng.randint(0, S), rng.randint(0, S), rng.choice([2, 2, 3, 4])
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))
    d.rectangle((0, 610, S, S), fill=hexrgb("#f4f7fa"))
    for x in (160, 210, 590, 640, 690):
        d.line((x, 610, x, 470), fill=hexrgb("#3c4a57"), width=5)
        for k in range(5):
            d.line((x, 520 + k * 18, x - 30 + k * 4, 500 + k * 18), fill=hexrgb("#3c4a57"), width=3)
            d.line((x, 520 + k * 18, x + 30 - k * 4, 500 + k * 18), fill=hexrgb("#3c4a57"), width=3)
    text(d, (S / 2, 150), "Orla Brennan", SERIF_I, 58, hexrgb("#2f3e4c"), "mm")
    text(d, (S / 2, 220), "SONGS FOR THE LONG WINTER", SANS, 22, hexrgb("#2f3e4c"), "mm", 5)
    return grain(im, 5, 10)


def grid_bloom():
    im = Image.new("RGB", (S, S), hexrgb("#8d8a85"))
    d = ImageDraw.Draw(im)
    for i in range(0, S, 100):
        for j in range(0, S, 100):
            shade = 120 + ((i * 7 + j * 13) % 50)
            d.rectangle((i + 4, j + 4, i + 96, j + 96), fill=(shade, shade - 3, shade - 8))
    for a in range(0, 360, 30):
        x = 500 + math.cos(math.radians(a)) * 70
        y = 300 + math.sin(math.radians(a)) * 70
        d.ellipse((x - 60, y - 60, x + 60, y + 60), fill=hexrgb("#ff5e7e"))
    d.ellipse((460, 260, 540, 340), fill=hexrgb("#ffd23f"))
    text(d, (50, 590), "LUMEN", SANS_B, 80, (30, 30, 30))
    text(d, (50, 670), "DISTRICT", SANS_B, 80, (30, 30, 30))
    return grain(im, 8, 11)


def planets():
    im = img(radial((400, 400), "#2d1b4e", "#0c0717", 600))
    d = ImageDraw.Draw(im)
    rng = random.Random(12)
    for _ in range(160):
        x, y = rng.randint(0, S), rng.randint(0, S)
        d.point((x, y), fill=(255, 255, 255))
    for r in (120, 200, 290, 370):
        d.ellipse((400 - r, 400 - r * 0.45, 400 + r, 400 + r * 0.45), outline=(170, 150, 220), width=2)
    d.ellipse((350, 350, 450, 450), fill=hexrgb("#ffb347"))
    for r, a, col, size in ((120, 30, "#7fd1b9", 22), (200, 160, "#ff6f91", 30),
                            (290, 250, "#9ad0ff", 18), (370, 330, "#f9f871", 26)):
        x = 400 + math.cos(math.radians(a)) * r
        y = 400 + math.sin(math.radians(a)) * r * 0.45
        d.ellipse((x - size, y - size, x + size, y + size), fill=hexrgb(col))
    text(d, (S / 2, 690), "the minor planets", SERIF_I, 52, (240, 230, 255), "mm")
    text(d, (S / 2, 745), "ORBIT SONGS", SANS, 22, (240, 230, 255), "mm", 8)
    return grain(im, 5, 12)


COVERS = {
    "night-drive-atlas": synthwave,
    "ember-and-ash": mountains,
    "quiet-machines": rings,
    "signals-from-the-attic": bauhaus,
    "tidelines": waves,
    "low-tide-radio": lambda: duotone_blobs(21, "#7ec8e3", "#f7a8c4", "#3b3f8f", "Low Tide Radio", "Aurora Vale"),
    "afterglow": lambda: duotone_blobs(33, "#ff9a3c", "#c3195d", "#3d0c3b", "Afterglow", "Velvet Static"),
    "blue-hour-sessions": jazz,
    "copper-sky": desert,
    "songs-for-the-long-winter": winter,
    "concrete-bloom": grid_bloom,
    "orbit-songs": planets,
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, make in COVERS.items():
        make().convert("RGB").save(out / f"{name}.jpg", quality=92)
        print(name)
