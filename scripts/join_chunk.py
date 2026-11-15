#!/usr/bin/env python3
"""Join bisected parts back into the canonical chunk and verify the result.

    python3 scripts/join_chunk.py <temp_dir> chunk0002 [--keep-parts]

It concatenates output_chunk0002a.md, output_chunk0002b.md, … in order, merges
their meta files into output_chunk0002.meta.json, re-runs the completeness check
and only then deletes the parts. If the joined result still looks truncated it
keeps everything and exits non-zero, so you can bisect again with --parts 3.
"""

import argparse
import glob
import json
import os
import re
import sys

import verify_chunk  # noqa: E402

SUFFIXES = "abcdefghij"


def _part_ids(temp_dir, chunk_id):
    ids = []
    for suffix in SUFFIXES:
        if os.path.exists(os.path.join(temp_dir, f"output_{chunk_id}{suffix}.md")):
            ids.append(f"{chunk_id}{suffix}")
    return ids


def _merge_meta(temp_dir, chunk_id, parts):
    merged = {
        "schema_version": 1,
        "new_entities": [],
        "alias_hypotheses": [],
        "attribute_hypotheses": [],
        "used_term_sources": [],
        "conflicts": [],
    }
    found = False
    for part in parts:
        path = os.path.join(temp_dir, f"output_{part}.meta.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError:
            continue
        found = True
        for key in ("new_entities", "alias_hypotheses", "attribute_hypotheses", "conflicts"):
            merged[key].extend(data.get(key) or [])
        merged["used_term_sources"].extend(data.get("used_term_sources") or [])

    merged["used_term_sources"] = sorted(set(merged["used_term_sources"]))
    if found:
        with open(os.path.join(temp_dir, f"output_{chunk_id}.meta.json"), "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("chunk_id")
    parser.add_argument("--keep-parts", action="store_true", help="keep the part files for inspection")
    args = parser.parse_args(argv)

    temp_dir = os.path.abspath(args.temp_dir)
    parts = _part_ids(temp_dir, args.chunk_id)
    if not parts:
        raise SystemExit(f"no part outputs found for {args.chunk_id} (expected output_<chunk>a.md …)")

    pieces = []
    for part in parts:
        with open(os.path.join(temp_dir, f"output_{part}.md"), encoding="utf-8") as fh:
            pieces.append(fh.read().strip())

    joined = "\n\n".join(pieces).strip() + "\n"
    target = os.path.join(temp_dir, f"output_{args.chunk_id}.md")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(joined)

    meta_ok = _merge_meta(temp_dir, args.chunk_id, parts)
    verdict = verify_chunk.check(temp_dir, args.chunk_id)

    print(f"joined {len(parts)} parts -> {args.chunk_id} ({len(joined):,} chars)")
    print(f"meta merged: {'yes' if meta_ok else 'no part metas found'}")
    print(f"verdict: {verdict['status']}  {verdict.get('detail', '')}")
    if verdict["status"] != "ok":
        print("not removing parts — bisect again with a higher --parts")
        return 1

    if not args.keep_parts:
        for part in parts:
            for name in (f"{part}.md", f"output_{part}.md", f"output_{part}.meta.json",
                         os.path.join("prompts", f"{part}.md")):
                path = os.path.join(temp_dir, name)
                if os.path.exists(path):
                    os.remove(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
