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
    """Split at the paragraph boundary closest to each 1/parts character share."""
    paras = text.split("\n\n")
    total = len(paras)
    if total < parts * 2:
        raise SystemExit("chunk has too few paragraphs to bisect")

    total_chars = len(text)
    cuts = []
    for i in range(1, parts):
        target_chars = total_chars * i / parts

        # paragraph index whose cumulative end sits closest to the character target
        pos, best_idx, best_diff = 0, 1, None
        for idx, para in enumerate(paras):
            pos += len(para) + 2
            diff = abs(pos - target_chars)
            if best_diff is None or diff < best_diff:
                best_idx, best_diff = idx + 1, diff

        # a heading within ~10% of the paragraphs makes a cleaner cut
        window = max(1, total // 10)
        headings = [k for k in range(max(1, best_idx - window), min(total, best_idx + window + 1))
                    if paras[k].lstrip().startswith("#")]
        cuts.append(min(headings, key=lambda k: abs(k - best_idx)) if headings else best_idx)

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
