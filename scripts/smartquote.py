#!/usr/bin/env python3
"""Convert paired ASCII double quotes to Chinese curly quotes in output_chunk*.md.

Skips fenced code blocks, inline HTML tags, and any line with an odd number of
straight quotes (which is left untouched rather than mis-pairing across lines).

    python3 scripts/smartquote.py <temp_dir>           # dry-run
    python3 scripts/smartquote.py <temp_dir> --apply   # write changes in place
"""

import argparse
import glob
import os
import re
import sys

TAG_RE = re.compile(r"(<[^>]*>)")


def fix_line(line):
    parts = TAG_RE.split(line)
    state_open = True
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # HTML tag: leave attributes untouched
            out.append(part)
            continue
        chars = list(part)
        for j, ch in enumerate(chars):
            if ch == '"':
                chars[j] = "\u201c" if state_open else "\u201d"
                state_open = not state_open
        out.append("".join(chars))
    return "".join(out)


def transform_text(text):
    """Return (new_text, odd_line_count)."""
    if '"' not in text:
        return text, 0
    in_code = False
    odd = 0
    new_lines = []
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            new_lines.append(line)
            continue
        if in_code or '"' not in line:
            new_lines.append(line)
            continue
        # Count quotes outside HTML tags
        non_tag = "".join(TAG_RE.split(line)[::2])
        if non_tag.count('"') % 2:
            odd += 1
            new_lines.append(line)
            continue
        new_lines.append(fix_line(line))
    return "\n".join(new_lines), odd


def run(temp_dir, apply=False):
    changed = []
    total_odd = 0
    for path in sorted(glob.glob(os.path.join(temp_dir, "output_chunk*.md"))):
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        out, odd = transform_text(src)
        total_odd += odd
        if out != src:
            changed.append(os.path.basename(path))
            if apply:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(out)
    return changed, total_odd


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("--apply", action="store_true", help="write changes in place")
    args = parser.parse_args(argv)

    changed, total_odd = run(args.temp_dir, apply=args.apply)
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: {len(changed)} chunks, odd-count lines skipped: {total_odd}")
    if changed:
        short = [c.replace("output_chunk", "").replace(".md", "") for c in changed[:20]]
        print(" ".join(short))
    return 0


if __name__ == "__main__":
    sys.exit(main())
