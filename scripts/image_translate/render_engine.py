import os, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_dilation

SONGTI_REG = ("/System/Library/Fonts/Supplemental/Songti.ttc", 6)
SONGTI_BOLD = ("/System/Library/Fonts/Supplemental/Songti.ttc", 1)
HEITI_MED = ("/System/Library/Fonts/STHeiti Medium.ttc", 1)
HEITI_LIGHT = ("/System/Library/Fonts/STHeiti Light.ttc", 1)

def get_font(font_spec, size):
    return ImageFont.truetype(font_spec[0], size, index=font_spec[1])

def inpaint_box(arr, x0, y0, x1, y1, mode="auto", thresh_override=None):
    """Erase text in [x0:x1, y0:y1] while preserving surrounding background shade/gradient."""
    H, W = arr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return arr, 255.0

    if mode == "white":
        arr[y0:y1, x0:x1] = 255
        return arr, 255.0

    # Sample border ring outside box to estimate background brightness
    bx0, by0 = max(0, x0 - 4), max(0, y0 - 4)
    bx1, by1 = min(W, x1 + 4), min(H, y1 + 4)
    ring_pixels = []
    if by0 < y0: ring_pixels.append(arr[by0:y0, bx0:bx1].ravel())
    if y1 < by1: ring_pixels.append(arr[y1:by1, bx0:bx1].ravel())
    if bx0 < x0: ring_pixels.append(arr[y0:y1, bx0:x0].ravel())
    if x1 < bx1: ring_pixels.append(arr[y0:y1, x1:bx1].ravel())
    ring = np.concatenate(ring_pixels) if ring_pixels else arr[y0:y1, x0:x1].ravel()
    bg_med = float(np.median(ring))

    patch = arr[y0:y1, x0:x1].astype(np.float32)
    p10 = float(np.percentile(patch, 10))
    p90 = float(np.percentile(patch, 90))

    if mode == "dark_text" or (mode == "auto" and abs(p10 - bg_med) >= abs(p90 - bg_med)):
        # Dark text on lighter background
        if thresh_override is not None:
            thresh = float(thresh_override)
        elif bg_med > 235:
            thresh = min(226.0, bg_med - max(20.0, 0.15 * (bg_med - p10)))
        else:
            thresh = bg_med - max(22.0, 0.25 * (bg_med - p10))
        mask = patch < thresh
    else:
        # Bright/white text on darker background
        if thresh_override is not None:
            thresh = float(thresh_override)
        else:
            thresh = bg_med + max(18.0, 0.25 * (p90 - bg_med))
        mask = patch > thresh

    if not np.any(mask):
        return arr, bg_med

    mask = binary_dilation(mask, iterations=2)

    # Iterative Laplace diffusion from unmasked pixels
    work = patch.copy()
    work[mask] = bg_med
    for _ in range(90):
        padded = np.pad(work, 1, mode='edge')
        avg = 0.25 * (padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:])
        work[mask] = avg[mask]

    arr[y0:y1, x0:x1] = np.clip(work, 0, 255).astype(np.uint8)
    return arr, bg_med

def render_image(src_path, dst_path, items, caption=None, caption_y0=None, scale=2):
    """
    items: list of dicts:
      erase: (x0, y0, x1, y1) in [0..1] top-left coords (optional)
      text: str (Chinese text, supports \n)
      cx, cy: center in [0..1] (or x, y with anchor)
      anchor: 'mm' (default), 'lm', etc.
      size: font size in 1x pixels (multiplied by scale)
      font: 'heiti' | 'heiti_light' | 'songti' | 'songti_bold'
      color: 'auto' | 'black' | 'white'
      halo: bool (default False)
      erase_mode: 'auto' | 'white' | 'dark_text' | 'light_text'
    """
    im = Image.open(src_path).convert("L")
    W0, H0 = im.size
    W, H = W0 * scale, H0 * scale
    im_up = im.resize((W, H), Image.Resampling.LANCZOS)
    arr = np.array(im_up)

    # First erase caption strip if provided
    if caption_y0 is not None:
        cy_px = int(caption_y0 * H)
        arr[cy_px:, :] = 255

    # Erase all boxes first (so adjacent labels don't erase each other's newly drawn text)
    bg_samples = []
    for it in items:
        boxes = []
        if "erase" in it and it["erase"] is not None:
            boxes.append(it["erase"])
        if "extra_erase" in it and it["extra_erase"]:
            boxes.extend(it["extra_erase"])
        if boxes:
            pad_x = int(0.004 * W)
            pad_y = int(0.004 * H)
            bg_med = 255.0
            for ex0, ey0, ex1, ey1 in boxes:
                arr, bg_med = inpaint_box(
                    arr,
                    int(ex0 * W) - pad_x,
                    int(ey0 * H) - pad_y,
                    int(ex1 * W) + pad_x,
                    int(ey1 * H) + pad_y,
                    mode=it.get("erase_mode", "auto"),
                    thresh_override=it.get("thresh", None),
                )
            bg_samples.append(bg_med)
        else:
            bg_samples.append(255.0)

    out_im = Image.fromarray(arr).convert("RGB")
    draw = ImageDraw.Draw(out_im)

    font_map = {
        "heiti": HEITI_MED,
        "heiti_light": HEITI_LIGHT,
        "songti": SONGTI_REG,
        "songti_bold": SONGTI_BOLD,
    }

    for it, bg_med in zip(items, bg_samples):
        txt = it.get("text", "")
        if not txt:
            continue
        fspec = font_map.get(it.get("font", "heiti"), HEITI_MED)
        fsize = int(it.get("size", 11) * scale)
        font = get_font(fspec, fsize)
        col_opt = it.get("color", "auto")
        if col_opt == "white" or (col_opt == "auto" and bg_med < 135):
            fill = (255, 255, 255)
            halo_col = (30, 30, 30)
        else:
            fill = (15, 15, 15)
            halo_col = (255, 255, 255)

        anchor = it.get("anchor", "mm")
        px = int(it.get("cx", it.get("x", 0.5)) * W)
        py = int(it.get("cy", it.get("y", 0.5)) * H)
        sw = int(it.get("halo_width", 2) * (scale / 2)) if it.get("halo", False) else 0

        if "\n" in txt:
            lines = txt.split("\n")
            line_h = int(fsize * 1.2)
            start_y = py - (len(lines) - 1) * line_h // 2
            for li, line in enumerate(lines):
                draw.text(
                    (px, start_y + li * line_h), line, font=font, fill=fill,
                    anchor=anchor, stroke_width=sw, stroke_fill=halo_col if sw else None
                )
        else:
            draw.text(
                (px, py), txt, font=font, fill=fill,
                anchor=anchor, stroke_width=sw, stroke_fill=halo_col if sw else None
            )

    if caption:
        cap_font_size = int(14 * scale)
        # Auto-fit if wider than 94% of image width
        cap_font = get_font(SONGTI_REG, cap_font_size)
        bbox = draw.textbbox((0, 0), caption, font=cap_font)
        while (bbox[2] - bbox[0]) > 0.94 * W and cap_font_size > 16:
            cap_font_size -= 1
            cap_font = get_font(SONGTI_REG, cap_font_size)
            bbox = draw.textbbox((0, 0), caption, font=cap_font)

        cap_y = int(((caption_y0 + 1.0) / 2.0) * H) if caption_y0 is not None else int(0.98 * H)
        if "\n" in caption:
            lines = caption.split("\n")
            lh = int(cap_font_size * 1.25)
            sy = int((caption_y0 + 0.012) * H) + cap_font_size // 2
            for li, line in enumerate(lines):
                draw.text((W // 2, sy + li * lh), line, font=cap_font, fill=(15, 15, 15), anchor="mm")
        else:
            draw.text((W // 2, cap_y), caption, font=cap_font, fill=(15, 15, 15), anchor="mm")

    out_im.save(dst_path, format="JPEG", quality=95)
    return W, H
