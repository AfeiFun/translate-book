#!/usr/bin/env python3
"""
ocr_unlimited.py - Offline scanned-PDF to Markdown extraction via Unlimited-OCR (MLX).

Converts scanned or mixed PDFs page-by-page using a locally cached
`sahilchachra/unlimited-ocr-4bit-mlx` (or compatible) model via `mlx-vlm`.
Outputs clean Markdown with:
- running headers, footers, and page numbers stripped
- tables preserved as HTML `<table>` blocks
- detected figures cropped from page renders into `images/`
- cross-page broken sentences and hyphenated words stitched cleanly
- per-page checkpointing under `<work_dir>/ocr_pages/` for resume support
"""

import argparse
import glob
import json
import os
import re
import sys
import tempfile
import time

DEFAULT_MODEL_ID = "sahilchachra/unlimited-ocr-4bit-mlx"
DEFAULT_PROMPT = "<image>document parsing."

_DET_BLOCK_RE = re.compile(
    r"<\|det\|>([a-zA-Z0-9_]+)\s*(\[[^\]]*\])<\|/det\|>(.*?)(?=<\|det\|>|$)",
    re.S,
)
_TABLE_CLEAN_RE = re.compile(r"\s*\n\s*")
_SENTENCE_END_RE = re.compile(r'[.!?:;"\'”’)\]]\s*$')
_FIG_CAPTION_RE = re.compile(r"^(?:Figure|Fig\.?)\s+(\d+(?:[.-]\d+)*)\b", re.I)
_TBL_CAPTION_RE = re.compile(r"^Table\s+(\d+(?:[.-]\d+)*)\b", re.I)


def _bytes_to_unicode():
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


_UNICODE_TO_BYTE = {v: k for k, v in _bytes_to_unicode().items()}


def decode_bpe_text(text):
    """Decode GPT-2 byte-level BPE artifacts (e.g. Ġ, Ċ, âĢĶ) into UTF-8."""
    if not text:
        return ""
    if "Ġ" not in text and "Ċ" not in text and "âĢ" not in text:
        return text
    buf = bytearray()
    parts = []
    for ch in text:
        b = _UNICODE_TO_BYTE.get(ch)
        if b is not None:
            buf.append(b)
        else:
            if buf:
                parts.append(buf.decode("utf-8", errors="replace"))
                buf.clear()
            parts.append(ch)
    if buf:
        parts.append(buf.decode("utf-8", errors="replace"))
    return "".join(parts)


def find_cached_snapshot(model_id=DEFAULT_MODEL_ID):
    """Return local HuggingFace cache snapshot path if model_id is cached, else model_id."""
    if os.path.isdir(model_id):
        return model_id
    cache_key = "models--" + model_id.replace("/", "--")
    pattern = os.path.expanduser(f"~/.cache/huggingface/hub/{cache_key}/snapshots/*")
    snaps = sorted(glob.glob(pattern))
    for snap in snaps:
        if os.path.isfile(os.path.join(snap, "config.json")):
            return snap
    return model_id


def find_ocr_python():
    """Return Python executable with `mlx_vlm` installed, or None."""
    env_py = os.environ.get("TRANSLATE_BOOK_OCR_PYTHON")
    candidates = []
    if env_py:
        candidates.append(env_py)
    candidates.append(sys.executable)
    candidates.append(os.path.expanduser("~/.local/share/translate-book-ocr-venv/bin/python"))

    import subprocess
    for py in candidates:
        if not py or not os.path.exists(py):
            continue
        try:
            rc = subprocess.run(
                [py, "-c", "import mlx_vlm, pymupdf"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            if rc.returncode == 0:
                return py
        except Exception:
            continue
    return None


def _parse_bbox(raw_bbox):
    try:
        vals = json.loads(raw_bbox)
        if isinstance(vals, list) and len(vals) == 4:
            return [int(v) for v in vals]
    except Exception:
        pass
    return None


def parse_unlimited_ocr_output(raw_text):
    """Parse Unlimited-OCR tagged output into structured page blocks.

    Returns dict with:
      - blocks: list of {"kind": str, "bbox": [x0,y0,x1,y1]|None, "text": str}
      - image_bboxes: list of [x0,y0,x1,y1] (normalized 0..1000)
      - caption_bboxes: list of (bbox, text) for image captions
    """
    decoded = decode_bpe_text(raw_text).strip()
    matches = list(_DET_BLOCK_RE.finditer(decoded))
    if not matches:
        clean = decoded.strip()
        return {
            "blocks": ([{"kind": "text", "bbox": None, "text": clean}] if clean else []),
            "image_bboxes": [],
            "caption_bboxes": [],
        }

    blocks = []
    image_bboxes = []
    caption_bboxes = []
    for m in matches:
        kind = m.group(1).strip().lower()
        bbox = _parse_bbox(m.group(2))
        body = m.group(3).strip()

        if kind in ("page_number", "header", "footer"):
            continue
        if kind == "image":
            if bbox:
                image_bboxes.append(bbox)
                blocks.append({"kind": "image", "bbox": bbox, "text": ""})
            continue
        if kind == "table":
            clean_tbl = _TABLE_CLEAN_RE.sub("", body).strip()
            if clean_tbl:
                blocks.append({"kind": "table", "bbox": bbox, "text": clean_tbl})
            continue
        if kind in ("title", "sub_title") and body and not body.lstrip().startswith("#"):
            prefix = "# " if kind == "title" else "## "
            body = prefix + body
        if kind == "image_caption" and bbox:
            caption_bboxes.append((bbox, body))
        if body:
            blocks.append({"kind": kind, "bbox": bbox, "text": body})

    return {
        "blocks": blocks,
        "image_bboxes": image_bboxes,
        "caption_bboxes": caption_bboxes,
    }


def crop_page_figures(page_img_path, parsed_page, images_dir, page_num):
    """Crop detected figure boxes from a rendered page PNG and return image metadata list."""
    img_boxes = parsed_page.get("image_bboxes") or []
    if not img_boxes:
        return []

    from PIL import Image
    os.makedirs(images_dir, exist_ok=True)
    im = Image.open(page_img_path)
    W, H = im.size

    # Merge all figure boxes on the page into one composite crop if there are multiple sub-panels
    # under a Figure caption, bounding top above sub-labels up to caption bottom when available.
    x0 = min(b[0] for b in img_boxes)
    y0 = min(b[1] for b in img_boxes)
    x1 = max(b[2] for b in img_boxes)
    y1 = max(b[3] for b in img_boxes)

    # Blank verso/flyleaf scans occasionally cause the VLM to emit a single
    # full-page `[0, 0, 999, 999]` image box without any text or captions.
    non_img_blocks = [b for b in (parsed_page.get("blocks") or []) if b.get("kind") != "image"]
    if len(img_boxes) == 1 and (x1 - x0 >= 950 and y1 - y0 >= 950) and not non_img_blocks:
        return []

    # Check if a Figure caption sits just above y0; if sub-labels like "Star"/"Wheel"
    # lie between caption.y1 and y0, extend y0 slightly upward without touching the main caption.
    cap_bboxes = parsed_page.get("caption_bboxes") or []
    fig_caps = [(cb, txt) for cb, txt in cap_bboxes if _FIG_CAPTION_RE.match(txt.strip())]
    y0_locked_to_caption = False
    if fig_caps:
        cap_box = fig_caps[0][0]
        if cap_box[3] <= y0:
            # Allow sub-labels between main Figure caption bottom and first box top.
            y0 = min(y0, cap_box[3] + 4)
            y0_locked_to_caption = True

    px0 = max(0, int((x0 - 15) / 1000.0 * W))
    py0 = max(0, int((y0 if y0_locked_to_caption else y0 - 6) / 1000.0 * H))
    px1 = min(W, int((x1 + 15) / 1000.0 * W))
    py1 = min(H, int((y1 + 8) / 1000.0 * H))

    if px1 <= px0 + 10 or py1 <= py0 + 10:
        return []

    fname = f"p{page_num:04d}_fig1.png"
    out_path = os.path.join(images_dir, fname)
    im.crop((px0, py0, px1, py1)).save(out_path)
    label = fig_caps[0][1].splitlines()[0].strip() if fig_caps else f"Figure p.{page_num}"
    return [{
        "rel_path": f"images/{fname}",
        "label": label,
        "page": page_num,
        "norm_bbox": [max(0, x0 - 15), y0, min(1000, x1 + 15), min(1000, y1 + 8)],
    }]


def stitch_pages(page_entries):
    """Stitch parsed page blocks into clean Markdown, merging cross-page split paragraphs.

    Each entry in `page_entries` is {"page": int, "blocks": [...], "cropped_figures": [...]}.
    Returns (markdown_text, audit_summary).
    """
    out_blocks = []
    figures = []
    tables = []
    seen_fig_ids = set()
    seen_tbl_ids = set()

    for entry in page_entries:
        pno = entry["page"]
        cropped = entry.get("cropped_figures") or []
        fig_inserted_for_page = False

        for blk in entry.get("blocks") or []:
            kind = blk["kind"]
            txt = blk["text"].strip()

            if kind == "image":
                if cropped and not fig_inserted_for_page:
                    fig = cropped[0]
                    out_blocks.append(("image", f"![{fig['label']}]({fig['rel_path']})"))
                    fig_inserted_for_page = True
                continue

            if not txt:
                continue

            # Drop internal diagram sub-labels (e.g. "All-Channel") already enclosed in the figure crop.
            if (
                kind == "image_caption"
                and cropped
                and blk.get("bbox")
                and not _FIG_CAPTION_RE.match(txt)
                and not re.match(r"^(?:Note:|Source:|SOURCE:)", txt)
            ):
                cb = cropped[0].get("norm_bbox")
                bx = blk["bbox"]
                if cb and bx[0] >= cb[0] and bx[2] <= cb[2] and bx[1] >= cb[1] and bx[3] <= cb[3]:
                    continue

            fm = _FIG_CAPTION_RE.match(txt.splitlines()[0].strip())
            if fm and fm.group(1) not in seen_fig_ids:
                seen_fig_ids.add(fm.group(1))
                figures.append({"id": fm.group(1), "page": pno, "caption": txt.splitlines()[0].strip()})

            tm = _TBL_CAPTION_RE.match(txt.splitlines()[0].strip())
            if tm and tm.group(1) not in seen_tbl_ids:
                seen_tbl_ids.add(tm.group(1))
                tables.append({"id": tm.group(1), "pages": [pno], "caption": txt.splitlines()[0].strip()})

            if kind == "table":
                if not tm and not tables:
                    pass
                out_blocks.append(("table", txt))
                continue

            if (
                kind == "text"
                and out_blocks
                and out_blocks[-1][0] == "text"
                and not _SENTENCE_END_RE.search(out_blocks[-1][1])
                and not txt.startswith("#")
                and not _FIG_CAPTION_RE.match(txt)
                and not _TBL_CAPTION_RE.match(txt)
                and not re.match(r"^(?:Note:|Source:|SOURCE:|\d+\.\s)", txt)
            ):
                prev_txt = out_blocks[-1][1]
                if re.search(r"[A-Za-z]-\s*$", prev_txt) and re.match(r"^[a-z]", txt):
                    merged = re.sub(r"-\s*$", "", prev_txt) + txt
                else:
                    merged = prev_txt + " " + txt
                out_blocks[-1] = ("text", merged)
            else:
                out_blocks.append((kind, txt))

        if cropped and not fig_inserted_for_page:
            fig = cropped[0]
            out_blocks.append(("image", f"![{fig['label']}]({fig['rel_path']})"))

    markdown = "\n\n".join(txt for _, txt in out_blocks).strip() + "\n"
    actual_img_count = sum(1 for k, _ in out_blocks if k == "image")
    actual_tbl_count = sum(1 for k, _ in out_blocks if k == "table")
    audit = {
        "expected_figures": max(len(figures), actual_img_count),
        "expected_tables": max(len(tables), actual_tbl_count),
        "figures": figures,
        "tables": tables,
        "vector_figure_ids": [],
        "ocr_engine": "unlimited-ocr",
    }
    return markdown, audit


def _prepare_model_dir(model_path_or_id):
    """Return (resolved_dir, temp_dir_or_None) with model_type normalized to 'unlimited-ocr'."""
    src = find_cached_snapshot(model_path_or_id)
    if not os.path.isdir(src):
        return src, None
    cfg_path = os.path.join(src, "config.json")
    if not os.path.isfile(cfg_path):
        return src, None
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if cfg.get("model_type") == "unlimited-ocr":
        return src, None

    cfg["model_type"] = "unlimited-ocr"
    tmp_obj = tempfile.TemporaryDirectory(prefix="unlimited_ocr_cfg_")
    td = tmp_obj.name
    for fn in os.listdir(src):
        if fn == "config.json":
            with open(os.path.join(td, "config.json"), "w", encoding="utf-8") as out:
                json.dump(cfg, out, indent=2)
        else:
            os.symlink(os.path.join(src, fn), os.path.join(td, fn))
    return td, tmp_obj


def parse_page_range(spec, total_pages):
    """Parse 1-based page specification like '1-10,16' into sorted page numbers."""
    if not spec:
        return list(range(1, total_pages + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo = max(1, int(a))
            hi = min(total_pages, int(b))
            pages.update(range(lo, hi + 1))
        else:
            p = int(part)
            if 1 <= p <= total_pages:
                pages.add(p)
    return sorted(pages)


def run_ocr(
    pdf_path,
    output_md,
    images_dir=None,
    work_dir=None,
    model_id=DEFAULT_MODEL_ID,
    dpi=200,
    page_spec=None,
    max_tokens=3072,
    audit_path=None,
):
    """Run local Unlimited-OCR across a PDF, caching each page for resume support."""
    import pymupdf
    from mlx_vlm import load, generate

    out_dir = os.path.dirname(os.path.abspath(output_md))
    os.makedirs(out_dir, exist_ok=True)
    if images_dir is None:
        images_dir = os.path.join(out_dir, "images")
    if work_dir is None:
        work_dir = os.path.join(out_dir, "ocr_pages")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    target_pages = parse_page_range(page_spec, total_pages)

    model = None
    processor = None
    tmp_holder = None
    page_entries = []
    t_start = time.time()

    try:
        for idx, pno in enumerate(target_pages, 1):
            raw_cache = os.path.join(work_dir, f"p{pno:04d}.raw.txt")
            img_cache = os.path.join(work_dir, f"p{pno:04d}.png")

            if not os.path.exists(img_cache):
                doc[pno - 1].get_pixmap(dpi=dpi, alpha=False).save(img_cache)

            if os.path.exists(raw_cache):
                raw_txt = open(raw_cache, encoding="utf-8").read()
            else:
                if model is None:
                    resolved, tmp_holder = _prepare_model_dir(model_id)
                    model, processor = load(resolved)
                t0 = time.time()
                res = generate(
                    model,
                    processor,
                    DEFAULT_PROMPT,
                    image=[img_cache],
                    max_tokens=max_tokens,
                    temperature=0.0,
                    verbose=False,
                )
                raw_txt = decode_bpe_text(res.text if hasattr(res, "text") else str(res))
                with open(raw_cache, "w", encoding="utf-8") as f:
                    f.write(raw_txt)
                elapsed = time.time() - t0
                if idx % 10 == 0 or idx == len(target_pages) or idx <= 3:
                    print(f"[ocr] page {pno}/{total_pages} ({idx}/{len(target_pages)}) in {elapsed:.2f}s", flush=True)

            parsed = parse_unlimited_ocr_output(raw_txt)
            cropped = crop_page_figures(img_cache, parsed, images_dir, pno)
            page_entries.append({
                "page": pno,
                "blocks": parsed["blocks"],
                "cropped_figures": cropped,
            })
    finally:
        doc.close()
        if tmp_holder is not None:
            tmp_holder.cleanup()

    markdown_text, audit = stitch_pages(page_entries)
    audit["pdf_file"] = os.path.basename(pdf_path)
    audit["page_count"] = total_pages
    with open(output_md, "w", encoding="utf-8") as f:
        f.write(markdown_text)
    if audit_path:
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=2)

    print(
        f"Unlimited-OCR complete: {len(target_pages)} page(s) in {time.time() - t_start:.1f}s -> {output_md}"
    )
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pdf_path", help="Path to scanned PDF")
    parser.add_argument("-o", "--output", required=True, help="Output Markdown path")
    parser.add_argument("--images-dir", default=None, help="Directory for cropped figures")
    parser.add_argument("--work-dir", default=None, help="Per-page OCR checkpoint directory")
    parser.add_argument("--audit-json", default=None, help="Optional pdf_assets_audit.json output path")
    parser.add_argument("--model", default=DEFAULT_MODEL_ID, help="HuggingFace ID or local model directory")
    parser.add_argument("--dpi", type=int, default=200, help="Rasterization DPI (default: 200)")
    parser.add_argument("--pages", default=None, help="Optional 1-based page range, e.g. 1-10,16")
    parser.add_argument("--max-tokens", type=int, default=3072, help="Max tokens per page (default: 3072)")
    args = parser.parse_args(argv)

    run_ocr(
        args.pdf_path,
        args.output,
        images_dir=args.images_dir,
        work_dir=args.work_dir,
        model_id=args.model,
        dpi=args.dpi,
        page_spec=args.pages,
        max_tokens=args.max_tokens,
        audit_path=args.audit_json,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
