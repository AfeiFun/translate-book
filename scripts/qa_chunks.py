#!/usr/bin/env python3
"""Sanity-check translated chunks before building.

Catches the failure modes that actually show up on long book runs: a chunk the
sub-agent never wrote, an output that is still English, OCR leftovers such as a
stray "~", replacement characters, unbalanced code fences, and headings that a
translator invented.

    python3 scripts/qa_chunks.py <temp_dir> [--strict] [--json]

Exit code is 1 when any chunk fails a check (unless --json, which always
returns 0 and reports findings). --strict also fails on missing meta files.
"""

import argparse
import glob
import json
import os
import re
import sys

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")
_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b[^>]*>", re.I)
_HTML_TABLE_RE = re.compile(r"<table\b", re.I)
_MD_TABLE_SEP_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)?\|?\s*$"
)


def _load_manifest(temp_dir):
    path = os.path.join(temp_dir, "manifest.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _strip_code(text):
    return re.sub(r"`[^`]*`", "", re.sub(r"https?://\S+", "", text))


def check_chunk(path, source_path=None):
    """Return a list of problems for one output chunk."""
    problems = []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except UnicodeDecodeError as exc:
        return [f"not valid UTF-8: {exc}"]

    if not text.strip():
        return ["empty output"]
    if "\ufffd" in text:
        problems.append(f"{text.count(chr(0xFFFD))} replacement characters")

    body = _strip_code(text)
    cjk = len(CJK_RE.findall(body))
    latin = len(LATIN_RE.findall(body))
    if cjk == 0:
        problems.append("no CJK characters (untranslated?)")
    elif latin > cjk * 0.8:
        problems.append(f"suspiciously Latin-heavy ({latin} Latin vs {cjk} CJK)")

    if "~" in text:
        problems.append(f"{text.count('~')} OCR tilde(s) left")

    if text.count("```") % 2:
        problems.append("unbalanced code fences")

    if re.search(r"\b(translation|translated by|here is the translation)\b", text, re.I):
        problems.append("meta talk in the output")

    if source_path and os.path.exists(source_path):
        with open(source_path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        src_heads = len(re.findall(r"^#{1,6} ", src, re.M))
        out_heads = len(re.findall(r"^#{1,6} ", text, re.M))
        if out_heads > src_heads + 2:
            problems.append(f"headings inflated ({src_heads} -> {out_heads})")
    return problems


def count_markdown_assets(text):
    """Return (image_count, table_count) across Markdown and raw HTML blocks."""
    images = len(_IMG_REF_RE.findall(text))
    html_tables = len(_HTML_TABLE_RE.findall(text))
    md_tables = 0
    in_fence = False
    prev_was_table_line = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            prev_was_table_line = False
            continue
        if in_fence:
            continue
        if prev_was_table_line and _MD_TABLE_SEP_RE.match(line):
            md_tables += 1
        prev_was_table_line = "|" in line and bool(stripped)
    return images, html_tables + md_tables


def check_book_assets(temp_dir):
    """Compare translated outputs against pdf_assets_audit.json when present."""
    audit_path = os.path.join(temp_dir, "pdf_assets_audit.json")
    if not os.path.exists(audit_path):
        return []
    try:
        with open(audit_path, encoding="utf-8") as fh:
            audit = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable pdf_assets_audit.json: {exc}"]

    manifest = _load_manifest(temp_dir)
    if manifest:
        out_paths = [os.path.join(temp_dir, f"output_{c['id']}.md") for c in manifest.get("chunks", [])]
    else:
        out_paths = sorted(glob.glob(os.path.join(temp_dir, "output_chunk*.md")))

    combined_parts = []
    for p in out_paths:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    combined_parts.append(fh.read())
            except OSError:
                continue
    if not combined_parts:
        return []

    actual_images, actual_tables = count_markdown_assets("\n\n".join(combined_parts))
    findings = []
    exp_figs = int(audit.get("expected_figures", 0) or 0)
    exp_tbls = int(audit.get("expected_tables", 0) or 0)
    if exp_figs and actual_images < exp_figs:
        vec_ids = audit.get("vector_figure_ids") or []
        hint = f" (vector figures in PDF: {', '.join(vec_ids)})" if vec_ids else ""
        findings.append(
            f"missing figures: found {actual_images} image(s) in translated chunks, "
            f"PDF audit expected {exp_figs}{hint}"
        )
    if exp_tbls and actual_tables < exp_tbls:
        tbl_ids = [t.get("id", "?") for t in audit.get("tables", [])]
        hint = f" (PDF tables: {', '.join(tbl_ids)})" if tbl_ids else ""
        findings.append(
            f"missing tables: found {actual_tables} table(s) in translated chunks, "
            f"PDF audit expected {exp_tbls}{hint}"
        )
    return findings


def run(temp_dir, strict=False):
    manifest = _load_manifest(temp_dir)
    if manifest:
        chunk_ids = [c["id"] for c in manifest.get("chunks", [])]
    else:
        chunk_ids = [os.path.basename(p)[:-3]
                     for p in sorted(glob.glob(os.path.join(temp_dir, "chunk*.md")))
                     if not os.path.basename(p).startswith("output_")]

    findings = {}
    for cid in chunk_ids:
        out = os.path.join(temp_dir, f"output_{cid}.md")
        src = os.path.join(temp_dir, f"{cid}.md")
        if not os.path.exists(out):
            findings[cid] = ["missing output"]
            continue
        problems = check_chunk(out, src)
        if strict and not os.path.exists(os.path.join(temp_dir, f"output_{cid}.meta.json")):
            problems.append("missing meta file")
        if problems:
            findings[cid] = problems

    book_findings = check_book_assets(temp_dir)
    if book_findings:
        findings["_book"] = book_findings
    return chunk_ids, findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("temp_dir")
    parser.add_argument("--strict", action="store_true", help="also fail on missing meta files")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    chunk_ids, findings = run(args.temp_dir, args.strict)

    if args.json:
        print(json.dumps({"checked": len(chunk_ids), "findings": findings},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"checked {len(chunk_ids)} chunks; {len(findings)} with findings")
    for cid, problems in sorted(findings.items()):
        print(f"  {cid}: {'; '.join(problems)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
