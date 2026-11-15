#!/usr/bin/env python3
"""Check that a translated chunk is complete — not merely non-empty.

A sub-agent that runs out of output budget still writes a file: it just stops
mid-book. This compares the translated chunk with its source and flags the three
shapes that failure takes:

    missing      no output file
    empty        output is blank
    truncated    far fewer blocks than the source (a 100k-char chunk that comes
                 back with 71 of 209 paragraphs looks fine to `ls -l`)
    unterminated output stops without sentence-final punctuation while the
                 source ends on one

    python3 scripts/verify_chunk.py <temp_dir>                 # every chunk
    python3 scripts/verify_chunk.py <temp_dir> chunk0042 ...   # selected
    python3 scripts/verify_chunk.py <temp_dir> --json

Exit code 1 when anything is off, so a batch loop can react to it.
"""

import argparse
import glob
import json
import os
import re
import sys

TERMINAL = "。！？…”』」）】》.!?\"'）"
DEFAULT_RATIO = 0.85


def blocks(text):
    return [b for b in text.split("\n\n") if b.strip()]


def _ends_terminally(text):
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in TERMINAL


def check(temp_dir, chunk_id, ratio_threshold=DEFAULT_RATIO):
    src_path = os.path.join(temp_dir, f"{chunk_id}.md")
    out_path = os.path.join(temp_dir, f"output_{chunk_id}.md")

    if not os.path.exists(src_path):
        return {"chunk": chunk_id, "status": "no-source", "detail": src_path}
    if not os.path.exists(out_path):
        return {"chunk": chunk_id, "status": "missing", "detail": "no output file"}

    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    with open(out_path, encoding="utf-8") as fh:
        out = fh.read()

    if not out.strip():
        return {"chunk": chunk_id, "status": "empty", "detail": "0 bytes of text"}

    src_blocks, out_blocks = len(blocks(src)), len(blocks(out))
    ratio = out_blocks / src_blocks if src_blocks else 1.0
    result = {
        "chunk": chunk_id,
        "status": "ok",
        "src_blocks": src_blocks,
        "out_blocks": out_blocks,
        "block_ratio": round(ratio, 2),
        "src_chars": len(src),
        "out_chars": len(out),
    }

    # A handful of blocks legitimately merge, so demand both a ratio and an
    # absolute gap before shouting "truncated".
    if src_blocks >= 8 and ratio < ratio_threshold and src_blocks - out_blocks >= 2:
        result["status"] = "truncated"
        result["detail"] = f"{out_blocks}/{src_blocks} blocks ({ratio:.0%})"
        return result

    # An unterminated tail is only meaningful when the chunk is also much
    # shorter than its source; otherwise it is a signature line or a list item.
    if (_ends_terminally(src) and not _ends_terminally(out)
            and len(out) < 0.20 * len(src)):
        result["status"] = "unterminated"
        result["detail"] = (f"source ends with {src.rstrip()[-1]!r}, output with "
                            f"{out.rstrip()[-1]!r}; {len(out)}/{len(src)} chars")
        return result

    return result


def collect_ids(temp_dir):
    ids = []
    for path in sorted(glob.glob(os.path.join(temp_dir, "chunk*.md"))):
        name = os.path.basename(path)
        if name.startswith("output_"):
            continue
        ids.append(name[:-3])
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("chunks", nargs="*")
    parser.add_argument("--ratio", type=float, default=DEFAULT_RATIO,
                        help=f"block-count ratio below which a chunk counts as truncated (default {DEFAULT_RATIO})")
    parser.add_argument("--json", action="store_true", help="machine-readable output; exits 0")
    args = parser.parse_args(argv)

    ids = args.chunks or collect_ids(args.temp_dir)
    results = [check(args.temp_dir, cid, args.ratio) for cid in ids]
    bad = [r for r in results if r["status"] != "ok"]

    if args.json:
        print(json.dumps({"checked": len(results), "problems": bad}, ensure_ascii=False, indent=2))
        return 0

    print(f"checked {len(results)} chunks; {len(bad)} need attention")
    for r in bad:
        print(f"  {r['chunk']}: {r['status']} — {r.get('detail', '')}")
        if r["status"] in ("truncated", "unterminated"):
            print(f"    fix: python3 scripts/split_chunk.py <temp_dir> {r['chunk']} --style <style>")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
