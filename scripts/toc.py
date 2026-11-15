#!/usr/bin/env python3
"""Book-level table of contents for the merged HTML.

The sidebar TOC inserted by merge_and_build only exists in `book.html`. Ebook
readers (EPUB/DOCX/PDF) need a TOC *page* inside the document, and a printed
PDF wants page numbers next to each entry.

This module builds that page: it rewrites heading ids to ASCII (Calibre's EPUB
splitter cannot resolve non-ASCII fragments and silently points every entry at
the first split file), inserts a two-level list with dotted leaders, and can
resolve the printed folio numbers from a PDF built with placeholder numbers.

CLI (used by merge_and_build --toc, handy on its own when re-styling a built book):

    python3 toc.py insert <in.html> <out.html> [numbers.json] [--title 目录]
    python3 toc.py pages  <book.pdf> <out.json> <in.html>
"""

import argparse
import html as htmlmod
import json
import re
import sys

BEGIN = "<!-- book-toc:begin -->"
END = "<!-- book-toc:end -->"
STYLE_ID = "book-toc-style"

HEAD_RE = re.compile(r'<h([1-6])([^>]*)>(.*?)</h\1>', re.S)
TAG_RE = re.compile(r"<[^>]+>")
ID_RE = re.compile(r'id="([^"]+)"')

DEFAULT_TITLES = {
    "zh": "目录",
    "ja": "目次",
    "ko": "목차",
    "ru": "Содержание",
}


def strip_tags(text):
    return htmlmod.unescape(TAG_RE.sub("", text)).strip()


def toc_title_for(lang_code, override=None):
    if override:
        return override
    return DEFAULT_TITLES.get((lang_code or "en")[:2], "Contents")


def has_cjk(text):
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text or ""))


def strip_existing_toc(html):
    """Make insertion idempotent: drop a TOC block from an earlier run."""
    html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", html, flags=re.S)
    return re.sub(r'<style id="%s">.*?</style>\n?' % STYLE_ID, "", html, flags=re.S)


def collect_headings(html, levels=(1, 2), start_heading=None, skip_texts=()):
    """Return [(level, id, text)] for headings that belong in the TOC.

    `start_heading` trims the title block: everything before that heading is
    ignored. When omitted, the TOC starts at the second level-1 heading, which
    is where most books begin their real content (the first h1 is the title).
    """
    items = []
    for m in HEAD_RE.finditer(html):
        level = int(m.group(1))
        attrs = m.group(2)
        text = strip_tags(m.group(3))
        if not text or 'class="title"' in attrs:
            continue
        if text in skip_texts:
            continue
        idm = ID_RE.search(attrs)
        items.append([level, idm.group(1) if idm else "", text])

    if start_heading:
        for i, it in enumerate(items):
            if it[2] == start_heading:
                items = items[i:]
                break
    else:
        h1_seen = 0
        cut = None
        for i, it in enumerate(items):
            if it[0] == 1:
                h1_seen += 1
                if h1_seen == 2:
                    cut = i
                    break
        if cut is not None:
            items = items[cut:]

    return [tuple(it) for it in items if it[0] in levels]


def rewrite_heading_ids(html, items):
    """Give every TOC heading an ASCII id (sec001...) and return the new list."""
    out, used = [], 0
    for level, old_id, text in items:
        used += 1
        new_id = "sec%03d" % used
        out.append((level, new_id, text))
        if old_id:
            html = html.replace('id="%s"' % old_id, 'id="%s"' % new_id, 1)
    return html, out


def build_toc_block(items, numbers=None, title="目录"):
    rows = []
    numbered = bool(numbers)
    for i, (level, hid, text) in enumerate(items):
        cls = "toc-l1" if level == 1 else "toc-l2"
        label = htmlmod.escape(text, quote=False)
        if numbered:
            num = numbers[i] if i < len(numbers) else ""
            rows.append(
                '<li class="%s"><a href="#%s"><span class="toc-text">%s</span>'
                '<span class="toc-dots"></span><span class="toc-page">%s</span></a></li>'
                % (cls, hid, label, htmlmod.escape(str(num), quote=False))
            )
        else:
            rows.append('<li class="%s"><a href="#%s">%s</a></li>' % (cls, hid, label))
    return (
        "%s\n<section class=\"book-toc\">\n"
        '<h1 class="book-toc-title" id="book-toc-top">%s</h1>\n'
        '<ul class="book-toc-list">\n%s\n</ul>\n</section>\n%s\n'
        % (BEGIN, htmlmod.escape(title, quote=False), "\n".join(rows), END)
    )


TOC_CSS = """<style id="book-toc-style">
.book-toc { page-break-before: always; page-break-after: always; }
.book-toc-title { margin-bottom: 1.6rem; }
.book-toc-list { list-style: none; padding: 0; margin: 0; font-size: 0.86em; line-height: 1.75; }
.book-toc-list li { margin: 0; }
.book-toc-list a { display: flex; align-items: baseline; text-decoration: none; color: inherit; }
.toc-text { flex: 0 1 auto; }
.toc-dots { flex: 1 1 auto; border-bottom: 1px dotted #bbb; margin: 0 .45em 0 .35em; transform: translateY(-.28em); min-width: 1.2em; }
.toc-page { flex: 0 0 auto; font-variant-numeric: tabular-nums; }
.toc-l2 { padding-left: 1.3em; }
.toc-l1 a { font-weight: 600; margin-top: .5em; }
</style>"""


def insert_toc(html, numbers=None, title="目录", levels=(1, 2),
               start_heading=None, skip_texts=()):
    """Insert (or replace) the TOC page. Returns (html, items)."""
    html = strip_existing_toc(html)
    items = collect_headings(html, levels=levels, start_heading=start_heading,
                             skip_texts=skip_texts)
    if not items:
        raise ValueError("no headings found for the table of contents")
    html, items = rewrite_heading_ids(html, items)

    block = build_toc_block(items, numbers, title)
    anchor = None
    for level, hid, text in items:
        if level == 1:
            anchor = re.search(r'<h1 id="%s"' % re.escape(hid), html)
            if anchor:
                break
    if anchor is None:
        anchor = re.search(r'<h%d id="%s"' % (items[0][0], re.escape(items[0][1])), html)
    if anchor is None:
        raise ValueError("could not locate the first TOC heading in the HTML")

    html = html[: anchor.start()] + block + html[anchor.start():]
    if STYLE_ID not in html:
        html = html.replace("</head>", TOC_CSS + "\n</head>", 1)
    return html, items


# ---------------------------------------------------------------------------
# PDF page numbers
# ---------------------------------------------------------------------------

def _page_folio(page, body_size):
    """Printed page number at the bottom of a page, or None."""
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    for block in reversed(blocks):
        text = block[4].strip()
        if re.fullmatch(r"\d{1,4}", text):
            return int(text)
    return None


def _page_heading_text(page, min_size):
    chunks = []
    for blk in page.get_text("dict").get("blocks", []):
        lines = []
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            if spans and max(s.get("size", 0) for s in spans) >= min_size:
                lines.append("".join(s["text"] for s in spans))
        if lines:
            chunks.append("".join(lines))
    return re.sub(r"\s+", "", "".join(chunks))


def resolve_pdf_pages(pdf_path, titles, min_heading_size=11.5):
    """Map each title (document order) to the printed page number in a PDF.

    Headings are told apart from body text by font size; the lookup is
    monotonic so repeated titles resolve to successive occurrences. The printed
    folio is read from the page footer, so an unnumbered cover does not skew
    the numbers.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "PDF page numbers need PyMuPDF (pip install pymupdf); "
            "build once without --toc-pages if you cannot install it"
        ) from exc

    doc = fitz.open(pdf_path)
    heads, folios = [], []
    for page in doc:
        heads.append(_page_heading_text(page, min_heading_size))
        folios.append(_page_folio(page, min_heading_size))

    out, cursor = [], 0
    for title in titles:
        key = re.sub(r"\s+", "", title)
        found = ""
        for pno in range(cursor, len(heads)):
            if key and key in heads[pno]:
                folio = folios[pno]
                found = str(folio if folio is not None else pno + 1)
                cursor = pno
                break
        out.append(found)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_insert = sub.add_parser("insert", help="insert or replace the TOC page")
    p_insert.add_argument("src")
    p_insert.add_argument("dst")
    p_insert.add_argument("numbers", nargs="?", default=None, help="JSON list of page numbers")
    p_insert.add_argument("--title", default="目录")
    p_insert.add_argument("--levels", default="1,2")
    p_insert.add_argument("--start", default=None, help="heading text where the TOC starts")

    p_pages = sub.add_parser("pages", help="resolve printed page numbers from a PDF")
    p_pages.add_argument("pdf")
    p_pages.add_argument("dst")
    p_pages.add_argument("html")

    args = parser.parse_args(argv)

    if args.command == "insert":
        with open(args.src, encoding="utf-8") as fh:
            html = fh.read()
        numbers = None
        if args.numbers:
            if args.numbers.lstrip().startswith("["):
                numbers = json.loads(args.numbers)      # inline JSON list
            else:
                with open(args.numbers, encoding="utf-8") as fh:
                    numbers = json.load(fh)
        levels = tuple(int(x) for x in args.levels.split(",") if x.strip())
        out, items = insert_toc(html, numbers, args.title, levels, args.start)
        with open(args.dst, "w", encoding="utf-8") as fh:
            fh.write(out)
        print("toc entries: %d (numbers: %d)" % (len(items), len(numbers or [])))
        return 0

    with open(args.html, encoding="utf-8") as fh:
        html = fh.read()
    items = collect_headings(html, levels=(1, 2, 3))
    pages = resolve_pdf_pages(args.pdf, [t for _, _, t in items])
    with open(args.dst, "w", encoding="utf-8") as fh:
        json.dump(pages, fh, ensure_ascii=False)
    missing = [t for t, p in zip([i[2] for i in items], pages) if not p]
    print("resolved %d/%d headings; missing: %s" % (len(pages) - len(missing), len(pages), missing[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
