#!/usr/bin/env python3
"""Convert a Calibre-generated EPUB into clean Markdown, using toc.ncx for headings.

usage: epub2md.py <book.epub> <out.md>

Why not `pandoc input.html`: Calibre wraps every paragraph in
`<div class="calibreN"><span class="calibreM">`, which pandoc happily turns into
fenced divs and `{.calibre}` attribute soup. We only want paragraphs, emphasis,
images and headings, so this walks the source documents directly and reads the
heading text from toc.ncx (the EPUB in this repo has no <h1>/<h2> at all —
titles are just underlined spans).
"""

import html as htmlmod
import os
import re
import shutil
import sys
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup, NavigableString, Tag

NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def read_ncx(zf, root):
    """[(depth, title, file, anchor)] in reading order."""
    ncx_path = None
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    opf_path = rootfile.get("full-path")

    opf = ET.fromstring(zf.read(opf_path))
    base = os.path.dirname(opf_path)
    manifest = {}
    for item in opf.findall(".//opf:manifest/opf:item", OPF_NS):
        manifest[item.get("id")] = item.get("href")
    spine = [manifest[i.get("idref")] for i in opf.findall(".//opf:spine/opf:itemref", OPF_NS)
             if i.get("idref") in manifest]
    for item in opf.findall(".//opf:manifest/opf:item", OPF_NS):
        if item.get("media-type") == "application/x-dtbncx+xml":
            ncx_path = os.path.join(base, item.get("href"))
    if not ncx_path:
        ncx_path = os.path.join(base, "toc.ncx")

    ncx = ET.fromstring(zf.read(ncx_path))
    entries = []

    def walk(node, depth):
        for point in node.findall("ncx:navPoint", NCX_NS):
            label = point.find("ncx:navLabel/ncx:text", NCX_NS)
            content = point.find("ncx:content", NCX_NS)
            if label is not None and content is not None:
                src = content.get("src", "")
                file_part, _, anchor = src.partition("#")
                entries.append((depth, (label.text or "").strip(), file_part, anchor))
            walk(point, depth + 1)

    walk(ncx.find("ncx:navMap", NCX_NS), 1)
    return os.path.join(base, spine[0]) and [(d, t, os.path.join(base, f), a) for d, t, f, a in entries], base


def _wrap(text, marker):
    """Apply emphasis without swallowing the neighbouring word: keep spaces outside."""
    if not text.strip():
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{marker}{text.strip()}{marker}{trail}"


def inline_md(node):
    """Serialise inline content to markdown (bold/italic/code/images/links)."""
    out = []
    for child in node.children:
        if isinstance(child, NavigableString):
            out.append(re.sub(r"\s+", " ", str(child)))
            continue
        name = child.name
        classes = child.get("class") or []
        text = inline_md(child)
        if name == "img":
            src = child.get("src", "")
            alt = (child.get("alt") or "").strip()
            out.append(f"![{alt}]({src})")
        elif name in ("b", "strong") or "bold" in classes:
            out.append(_wrap(text, "**"))
        elif name in ("i", "em") or "italic" in classes:
            out.append(_wrap(text, "*"))
        elif name == "sup":
            out.append(f"[{text.strip()}]")   # endnote marker, notes follow the chapter
        elif name == "code":
            out.append(f"`{text.strip()}`")
        elif name == "br":
            out.append(" ")
        else:
            out.append(text)
    return "".join(out)


def paragraphs(soup):
    """Yield (kind, text) where kind is 'p' or 'img'."""
    for el in soup.find_all(["p", "h1", "h2", "h3", "h4", "blockquote", "li"]):
        # Skip paragraphs nested in an already-emitted block (Calibre nests spans, not ps)
        text = re.sub(r"[ \t]+", " ", inline_md(el)).strip()
        if not text:
            continue
        if el.name == "blockquote":
            yield ("q", text)
        elif el.name == "li":
            yield ("li", text)
        else:
            yield ("p", text)
    for img in soup.find_all("img"):
        parent = img.find_parent(["p", "div"])
        # Images that sit inside a paragraph were already emitted with their text
        if parent is None or not parent.get_text(strip=True):
            src = img.get("src", "")
            alt = (img.get("alt") or "").strip()
            if src:
                yield ("img", f"![{alt}]({src})")


NUM_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty",
}


def _is_display_title(text, title):
    """True for the all-caps chapter number/name that repeats the ncx heading."""
    bare = re.sub(r"[*_`#>]", "", text).strip()
    if not bare or len(bare) > len(title) + 20:
        return False
    if bare.lower() in NUM_WORDS:
        return True
    norm = re.sub(r"\W+", " ", bare.lower()).strip()
    tnorm = re.sub(r"\W+", " ", title.lower()).strip()
    return bool(norm) and (norm in tnorm or tnorm.endswith(norm)) and bare.isupper()


def clean_title(t):
    return re.sub(r"\s+", " ", t).strip()


def main():
    epub, out_md = sys.argv[1], sys.argv[2]
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(epub) as zf:
        zf.extractall(tmp)
        entries, base = read_ncx(zf, tmp)

        # group entries by file, in document order
        by_file = {}
        for depth, title, path, anchor in entries:
            by_file.setdefault(path, []).append((depth, title, anchor))

        md = []
        seen_part_divider = False
        title_counts = {}
        for depth, title, _, _ in entries:
            title_counts[title] = title_counts.get(title, 0) + 1

        for path, items in by_file.items():
            full = os.path.join(tmp, path)
            if not os.path.exists(full):
                continue
            raw = open(full, encoding="utf-8", errors="replace").read()

            # split the file at every anchor in this file that the ncx references
            marks = []
            for depth, title, anchor in items:
                if not anchor:
                    marks.append((0, depth, title))
                    continue
                m = re.search(r'id="%s"' % re.escape(anchor), raw)
                marks.append((m.start() if m else 0, depth, title))
            marks.sort()

            for i, (start, depth, title) in enumerate(marks):
                end = marks[i + 1][0] if i + 1 < len(marks) else len(raw)
                chunk = raw[start:end]
                soup = BeautifulSoup(chunk, "html.parser")

                # drop the duplicated title paragraph that Calibre puts at the top
                title_key = re.sub(r"\W+", "", title).lower()
                first_p = soup.find("p")
                if first_p:
                    first_key = re.sub(r"\W+", "", first_p.get_text()).lower()
                    if first_key.startswith(title_key[:24]) and len(first_key) < len(title_key) + 12:
                        first_p.decompose()

                display_title = title
                if title == "THE ROAD TO SERFDOM":
                    seen_part_divider = True
                elif title == "Introduction" and not seen_part_divider and title_counts.get(title, 0) > 1:
                    display_title = "Introduction by the Editor"

                hashes = "#" * min(depth, 3)
                md.append(f"{hashes} {clean_title(display_title)}\n")
                skipped = 0
                for kind, text in paragraphs(soup):
                    if kind == "p" and skipped < 3 and _is_display_title(text, title):
                        skipped += 1
                        continue
                    skipped = 3
                    if kind == "img":
                        md.append(f"{text}\n")
                    elif kind == "q":
                        md.append(f"> {text}\n")
                    elif kind == "li":
                        md.append(f"- {text}\n")
                    else:
                        md.append(f"{text}\n")
                md.append("")

    text = "\n".join(md)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # images live next to the markdown so convert.py copies them into the temp dir
    out_dir = os.path.dirname(os.path.abspath(out_md))
    src_images = os.path.join(tmp, "images")
    if os.path.isdir(src_images):
        dst = os.path.join(out_dir, "images")
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src_images):
            src = os.path.join(src_images, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dst, name))

    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{out_md}: {len(text):,} chars, {text.count(chr(10) + '# ')} + {text.count(chr(10) + '## ')} headings")


if __name__ == "__main__":
    main()
