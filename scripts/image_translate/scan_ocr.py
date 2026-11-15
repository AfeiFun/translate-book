import subprocess, json, os
from PIL import Image, ImageOps, ImageEnhance

# Set IMG_SCRATCH to a work dir holding clean_images/ and the compiled ocr_bin (swiftc ocr.swift -o ocr_bin)
SCRATCH = os.environ.get("IMG_SCRATCH", ".")
TARGETS = [f"{i:06d}.jpg" for i in range(7, 20)] + ["000022.jpg", "000036.jpg", "000040.jpg"]

results = {}
for fn in TARGETS:
    src = f"{SCRATCH}/clean_images/{fn}"
    if fn == "000010.jpg":
        src = f"{SCRATCH}/clean_images/000010_upright.jpg"
    im = Image.open(src).convert("L")
    W, H = im.size
    found = []
    # Full image + 3x3 overlapping tiles
    crops = [(0, 0, W, H)]
    for r in range(3):
        for c in range(3):
            x0 = max(0, int((c*0.33 - 0.06)*W))
            x1 = min(W, int(((c+1)*0.33 + 0.06)*W))
            y0 = max(0, int((r*0.33 - 0.06)*H))
            y1 = min(H, int(((r+1)*0.33 + 0.06)*H))
            crops.append((x0, y0, x1, y1))

    for (x0, y0, x1, y1) in crops:
        cw, ch = x1 - x0, y1 - y0
        scale = 4 if (cw < W or ch < H) else 3
        up = im.crop((x0, y0, x1, y1)).resize((cw*scale, ch*scale), Image.Resampling.LANCZOS)
        variants = [
            up,
            ImageOps.invert(up),
            ImageOps.equalize(up),
            ImageOps.invert(ImageOps.equalize(up)),
        ]
        for v in variants:
            p = f"{SCRATCH}/tmp_ocr.png"
            v.save(p)
            items = json.loads(subprocess.check_output([f"{SCRATCH}/ocr_bin", p]).decode())
            for it in items:
                # Convert Vision bottom-left coords in tile to top-left [0..1] in full image
                vx0 = it["x"]
                vy_bottom = it["y"]
                vw = it["w"]
                vh = it["h"]
                vy_top = 1.0 - (vy_bottom + vh)
                gx0 = (x0 + vx0 * cw) / W
                gy0 = (y0 + vy_top * ch) / H
                gw = vw * cw / W
                gh = vh * ch / H
                found.append({
                    "text": it["text"],
                    "x0": round(gx0, 4),
                    "y0": round(gy0, 4),
                    "x1": round(gx0 + gw, 4),
                    "y1": round(gy0 + gh, 4),
                    "cx": round(gx0 + gw/2, 4),
                    "cy": round(gy0 + gh/2, 4),
                })

    # Deduplicate overlapping boxes keeping longest text
    uniq = []
    for f in found:
        matched = False
        for i, u in enumerate(uniq):
            if abs(f["cx"] - u["cx"]) < 0.035 and abs(f["cy"] - u["cy"]) < 0.02:
                matched = True
                if len(f["text"]) > len(u["text"]):
                    uniq[i] = f
                break
        if not matched:
            uniq.append(f)

    uniq.sort(key=lambda z: (z["y0"], z["x0"]))
    results[fn] = {"width": W, "height": H, "boxes": uniq}
    print(f"{fn}: {len(uniq)} boxes")

with open(f"{SCRATCH}/ocr_boxes.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("Done!")
