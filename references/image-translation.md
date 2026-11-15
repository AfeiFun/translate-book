# Translating Text Inside Images (maps, diagrams, cartoons)

Field notes from *Why Nations Fail* (49 images, 23 needed translation). Goal: every
English label in a map/diagram becomes Simplified Chinese; dots, borders, shading stay.

## 0. Scope first — ask the user
Inventory ALL images before touching any. Classify each: needs translation (maps,
labeled diagrams, captions inside the bitmap) / pure photo / non-English / decorative.
**Ask whether to keep cover and title page as the original** (the user said yes). Keep
them byte-identical.

## 1. Preprocess (critical — this crashed the agent)
Book JPEGs were 1-channel grayscale with an **Adobe APP14 (0xFFEE) segment**. Feeding
them to the vision model returned `INVALID_ARGUMENT (code 400)` and killed the session.
- Detect: scan JPEG markers for `0xFFEE`. Strip it losslessly (copy bytes minus the
  segment) or re-save as RGB baseline JPEG. Always work from the cleaned copies.
- Never batch-read many raw images into the model; read cleaned ones, a few at a time.
- Sideways maps (landscape rotated 90°): rotate upright first, and ship the upright
  version (the HTML/EPUB just references the file, size change is fine).

## 2. Tool choice
| Approach | Result |
|---|---|
| Image generation model (redraw map) | Fine for sparse maps, but costs quota (hit `429` after 7 images), may alter geography and drops dots. Use only if it faithfully preserves the base map. |
| **Local engine** `scripts/image_translate/render_engine.py` | Deterministic, free, keeps every original pixel except the label boxes. Preferred for dense maps. |

Engine: 2× Lanczos upscale → per-label **inpaint** of the erase box (mask text pixels,
Laplace-diffuse the surrounding shade; or `erase_mode:"white"`) → draw Chinese with
macOS fonts (STHeiti Medium for labels, Songti for captions). macOS Vision OCR
(`ocr.swift` → `scan_ocr.py`) gives rough boxes (it garbles text; use positions only).

## 3. Workflow per image
1. Make a coordinate-grid preview (lines every 0.1) and READ it to get exact label
   boxes in normalized [0..1] coords. OCR boxes are a starting hint, not truth.
2. Translate names using the book's own glossary (`glossary.json`) and body text
   (`grep` the chapters: e.g. 特兰斯凯, 勃固, 阿马尔菲). Be consistent with the text.
3. Write items: `erase` box, `text`, centre/anchor, `size`, `color`, `halo`,
   `erase_mode`, optional `thresh` (see `example_render_batch.py`).
4. Render, then **read the output image** and look for: leftover English fragments,
   white rectangles, erased dots/borders, text overlapping lines.

## 4. Hard-won rules
- **Keep dots/markers OUTSIDE erase boxes** (city dots, capitals); start the erase box
  just past the dot and left/right-anchor the text next to it.
- **Text polarity**: decide dark-on-light vs white-on-dark per label. `dark_text` masks
  pixels below threshold, `light_text` above. Using the wrong mode leaves ghost text.
- **Threshold on mixed backgrounds**: a label straddling white (255) and gray (~190)
  with an auto threshold masks the whole gray region → ugly white box. Pass an explicit
  `thresh` (e.g. 145–185 for gray land, 105–120 for dark fills, 205–215 on near-white
  railway maps), and prefer 90 Laplace iterations.
- **Over a texture/lines** (railways, borders, hatching): `halo:true, halo_width:1`
  with a contrasting stroke keeps text crisp. Don't halo on flat fills.
- **White legend/ocean/blank areas**: just `erase_mode:"white"`.
- **Boxed/oval nodes** (Maya network): shrink the erase box ~0.007 so the box border
  survives, then draw the text centred.
- **Captions**: erase the bottom strip, redraw "地图 N：…" centred; wrap with `\n` when
  long (Map 16).
- **Long names**: shrink size (7.5–8.5 px) or split into two lines; verify no overlap.
- Pad erase boxes a little (the engine adds 0.4%) because OCR boxes are tight.
- Remaining faint "ghost" fragments of old text on gray fills are the usual last 5%:
  fix by widening that item's box or tightening `thresh`, re-render, re-read.

## 5. Verification and delivery
- Output must be RGB baseline JPEG with **no 0xFFEE**; assert this before copying.
- Copy to BOTH the build temp dir `images/` and the repo `images/` under the same file
  names. `merge_and_build.py` rebuilds docx/epub when image mtimes are newer.
- After build, open the EPUB zip and compare SHA-256 of each translated image with the
  verified file; confirm kept originals (cover/title) are byte-identical.
- Read EVERY rendered image once at full size before declaring done.
