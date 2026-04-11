"""
Generate the PWA icon set from scratch using Pillow.

Outputs (all in web/public/):
    icon-192.png              — standard 192×192 PWA icon
    icon-512.png              — standard 512×512 PWA icon
    icon-maskable-512.png     — 512×512 with a 20% inset (safe zone for
                                  Android adaptive icons)
    apple-touch-icon.png      — 180×180 for iOS home screen
    favicon.png               — 32×32 browser tab
    favicon.ico               — multi-size ICO for legacy browsers

Design: a four-stone cairn in slate-50 on a slate-900 background, with
slight per-stone rotation so it reads as hand-stacked rather than a
rigid stack of boxes. Corner radius on the bg + on each stone keeps it
crisp but not playful. Matches the target dark-neutral palette used in
the web UI rewrite.

Run once from the web/public directory:
    python _generate_icons.py
"""
from __future__ import annotations

import math
import os
from PIL import Image, ImageDraw, ImageFilter

# Design tokens — matches globals.css neutral palette
BG = (15, 23, 42, 255)          # slate-900
STONE = (248, 250, 252, 255)    # slate-50
MASTER_SIZE = 1024              # over-render then downscale for antialiasing


def _rounded_rect_rotated(
    draw_on: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    angle_deg: float,
    fill: tuple[int, int, int, int],
) -> None:
    """Draw a rounded rectangle rotated around its own centre."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    # Render the rect onto a transparent tile, rotate, paste back.
    tile = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=fill)
    rotated = tile.rotate(angle_deg, resample=Image.BICUBIC, expand=True)
    rx = x0 + (w - rotated.width) // 2
    ry = y0 + (h - rotated.height) // 2
    draw_on.paste(rotated, (rx, ry), rotated)


def render_master(inset_fraction: float = 0.0) -> Image.Image:
    """Render the master icon at MASTER_SIZE with optional safe-zone inset.

    ``inset_fraction`` is used for the maskable icon — at 0.2 the entire
    cairn is drawn inside an 80% bounding box so Android's adaptive icon
    mask (which can clip up to ~20%) never cuts off any stones.
    """
    img = Image.new('RGBA', (MASTER_SIZE, MASTER_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background plate (rounded for standard, full square for maskable so
    # the OS mask shapes it)
    if inset_fraction == 0.0:
        bg_radius = int(MASTER_SIZE * 0.1875)  # ~19% = iOS-style squircle
        draw.rounded_rectangle((0, 0, MASTER_SIZE, MASTER_SIZE), radius=bg_radius, fill=BG)
    else:
        # Maskable: fill the full square — OS applies its own mask
        draw.rectangle((0, 0, MASTER_SIZE, MASTER_SIZE), fill=BG)

    # Compute the safe-zone box for content
    inset = int(MASTER_SIZE * inset_fraction)
    safe_w = MASTER_SIZE - 2 * inset
    cx = MASTER_SIZE // 2
    base_y = inset + int(safe_w * 0.72)  # base stone sits ~72% down

    # Four stones, widths proportional to safe area, subtle rotations
    stones = [
        # (width_frac, height_px, y_offset_from_base, rotation_deg)
        (0.62, int(safe_w * 0.115), 0, 0.0),             # bottom — largest, level
        (0.50, int(safe_w * 0.108), -int(safe_w * 0.15), -2.2),
        (0.38, int(safe_w * 0.102), -int(safe_w * 0.29), 1.6),
        (0.24, int(safe_w * 0.094), -int(safe_w * 0.42), -1.2),
    ]

    for width_frac, h, y_off, angle in stones:
        w = int(safe_w * width_frac)
        x0 = cx - w // 2
        y0 = base_y + y_off
        x1 = x0 + w
        y1 = y0 + h
        radius = h // 2  # pill-ish, matches the neutral UI radii
        _rounded_rect_rotated(img, (x0, y0, x1, y1), radius, angle, STONE)

    return img


def save_resized(master: Image.Image, size: int, path: str) -> None:
    resized = master.resize((size, size), resample=Image.LANCZOS)
    resized.save(path, 'PNG', optimize=True)
    print(f'  wrote {path} ({size}x{size})')


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    print('Rendering standard master...')
    standard = render_master(inset_fraction=0.0)

    print('Rendering maskable master (20% safe inset)...')
    maskable = render_master(inset_fraction=0.10)

    # Standard PWA icons
    save_resized(standard, 192, 'icon-192.png')
    save_resized(standard, 512, 'icon-512.png')

    # Maskable — Android adaptive
    save_resized(maskable, 512, 'icon-maskable-512.png')

    # Apple touch icon
    save_resized(standard, 180, 'apple-touch-icon.png')

    # Favicons
    save_resized(standard, 32, 'favicon.png')
    save_resized(standard, 16, 'favicon-16.png')

    # ICO with multiple sizes
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    ico_img = standard.resize((64, 64), resample=Image.LANCZOS)
    ico_img.save('favicon.ico', format='ICO', sizes=ico_sizes)
    print('  wrote favicon.ico (16/32/48/64)')

    # Cleanup intermediate small favicon
    if os.path.exists('favicon-16.png'):
        os.remove('favicon-16.png')

    print('Done.')


if __name__ == '__main__':
    main()
