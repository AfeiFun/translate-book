#!/usr/bin/env python3
"""Render one self-contained prompt file per chunk.

The orchestrator no longer has to paste the rule list, the term table and the
neighbour excerpts together by hand for every chunk — which is where 300-chunk
runs go wrong. This writes the whole thing to a file; the sub-agent only has to
read that file.

    python3 scripts/build_prompt.py <temp_dir> chunk0042 --style readable
    python3 scripts/build_prompt.py <temp_dir> chunk0042 -o /tmp/prompts/chunk0042.md
    python3 scripts/build_prompt.py <temp_dir> --all --style scholarly --out-dir /tmp/prompts

Exit codes: 0 ok, 1 unknown style / missing chunk.
"""

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(SCRIPT_DIR, "prompt_template.md")

import style as style_mod  # noqa: E402


def _run(script, *args):
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script), *args],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def render(temp_dir, chunk_id, lang_name, style_name, custom, out_path):
    temp_dir = os.path.abspath(temp_dir)
    chunk_file = os.path.join(temp_dir, f"{chunk_id}.md")
    if not os.path.exists(chunk_file):
        raise SystemExit(f"missing source chunk: {chunk_file}")

    output_file = os.path.join(temp_dir, f"output_{chunk_id}.md")
    meta_file = os.path.join(temp_dir, f"output_{chunk_id}.meta.json")

    term_table = _run("glossary.py", "print-terms-for-chunk", temp_dir, f"{chunk_id}.md")
    neighbours = _run("chunk_context.py", temp_dir, f"{chunk_id}.md")

    style_block = style_mod.block(style_name)
    custom_block = ""
    if custom:
        custom_block = "## 本书的附加要求\n\n" + custom.strip()

    text = open(TEMPLATE, encoding="utf-8").read()
    values = {
        "TARGET_LANGUAGE": lang_name,
        "CHUNK_FILE": chunk_file,
        "OUTPUT_FILE": output_file,
        "META_FILE": meta_file,
        "CHUNK_ID": chunk_id,
        "STYLE_BLOCK": style_block,
        "CUSTOM_INSTRUCTIONS": custom_block,
        "TERM_TABLE": ("## 术语一致性\n\n下表「原文」列或「别名」列任一形式出现时，必须使用「译文」列译法。\n\n"
                       + term_table if term_table else ""),
        "NEIGHBOR_CONTEXT": ("## 邻居上下文（只读）\n\n以下摘录只用于判断代词、性别、别名与跨片段指代；"
                            "不要翻译，也不要写入输出。\n\n" + neighbours if neighbours else ""),
    }
    for key, value in values.items():
        text = text.replace("{%s}" % key, value)

    # drop placeholders that had no value so no dangling heading survives
    text = text.replace("\n\n\n", "\n\n")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    if out_path is None:
        out_dir = os.path.join(temp_dir, "prompts")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{chunk_id}.md")

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, out_path)
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("chunk_id", nargs="?", help="e.g. chunk0042 (omit with --all)")
    parser.add_argument("--all", action="store_true", help="render a prompt for every chunk")
    parser.add_argument("--lang", default="简体中文", help="target language name (default: 简体中文)")
    parser.add_argument("--style", default=style_mod.DEFAULT_STYLE,
                        help="style preset; see scripts/style.py list")
    parser.add_argument("--custom", default=None,
                        help="extra requirements, or the path to a file holding them")
    parser.add_argument("-o", "--out", default=None, help="output prompt path (single chunk)")
    parser.add_argument("--out-dir", default=None, help="output directory (with --all)")
    args = parser.parse_args(argv)

    try:
        style_mod.load(args.style)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    custom = args.custom
    if custom and os.path.isfile(custom):
        with open(custom, encoding="utf-8") as fh:
            custom = fh.read()

    if args.all:
        ids = sorted(f[:-3] for f in os.listdir(args.temp_dir)
                     if f.startswith("chunk") and f.endswith(".md")
                     and not f.startswith("output_"))
        out_dir = args.out_dir or os.path.join(args.temp_dir, "prompts")
        os.makedirs(out_dir, exist_ok=True)
        for cid in ids:
            render(args.temp_dir, cid, args.lang, args.style, custom,
                   os.path.join(out_dir, f"{cid}.md"))
        print(f"prompts: {len(ids)} -> {out_dir}")
        return 0

    if not args.chunk_id:
        print("error: pass a chunk id or --all", file=sys.stderr)
        return 1
    path = render(args.temp_dir, args.chunk_id, args.lang, args.style, custom, args.out)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
