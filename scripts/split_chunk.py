#!/usr/bin/env python3
"""Bisect a chunk that came back truncated, and prepare the part prompts.

Big chunks die quietly: the sub-agent writes a file that looks fine until you
compare block counts with the source. The repair is always the same — split the
source at a paragraph boundary, translate the halves, join them back.

    python3 scripts/split_chunk.py <temp_dir> chunk0002 --style readable --lang 简体中文
    # spawn one sub-agent per printed prompt, then:
    python3 scripts/join_chunk.py <temp_dir> chunk0002

Parts are named chunk0002a, chunk0002b, … so nothing collides with the chunk
numbering; `join_chunk.py` removes them again.
"""

import argparse
import os
import re
import sys

import build_prompt  # noqa: E402

SUFFIXES = "abcdefghij"


def _paragraphs(text):
    return [p for p in text.split("\n\n")]


def split_text(text, parts):
    """Split at the paragraph boundary closest to each 1/parts fraction."""
    paras = _paragraphs(text)
    total = len(paras)
    if total < parts * 2:
        raise SystemExit("chunk has too few paragraphs to bisect")

    cuts = []
    window = max(1, total // 10)
    for i in range(1, parts):
        target = int(total * i / parts)
        # prefer a cut right before a heading, within 10% of the target
        best, best_score = target, -1
        for idx in range(max(1, target - window), min(total, target + window + 1)):
            if paras[idx].lstrip().startswith("#"):
                best = idx
                break
            score = len(paras[idx - 1])
            if score > best_score:
                best, best_score = idx, score
        cuts.append(best)

    out, prev = [], 0
    for cut in cuts + [total]:
        out.append("\n\n".join(paras[prev:cut]).strip() + "\n")
        prev = cut
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("chunk_id")
    parser.add_argument("--parts", type=int, default=2)
    parser.add_argument("--style", default="scholarly")
    parser.add_argument("--lang", default="简体中文")
    parser.add_argument("--custom", default=None)
    args = parser.parse_args(argv)

    temp_dir = os.path.abspath(args.temp_dir)
    src = os.path.join(temp_dir, f"{args.chunk_id}.md")
    if not os.path.exists(src):
        raise SystemExit(f"missing chunk: {src}")
    if args.parts > len(SUFFIXES):
        raise SystemExit(f"--parts max {len(SUFFIXES)}")

    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    pieces = split_text(text, args.parts)

    prompts = []
    for suffix, piece in zip(SUFFIXES, pieces):
        part_id = f"{args.chunk_id}{suffix}"
        with open(os.path.join(temp_dir, f"{part_id}.md"), "w", encoding="utf-8") as fh:
            fh.write(piece)
        prompt = build_prompt.render(temp_dir, part_id, args.lang, args.style,
                                     args.custom, os.path.join(temp_dir, "prompts", f"{part_id}.md"))
        prompts.append((part_id, len(piece), prompt))

    print(f"split {args.chunk_id} into {len(prompts)} parts:")
    for part_id, size, prompt in prompts:
        print(f"  {part_id}  {size:6d} chars  -> {prompt}")
    print("\nspawn one sub-agent per prompt, then run join_chunk.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
