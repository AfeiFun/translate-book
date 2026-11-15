import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import toc  # noqa: E402


SAMPLE = """<html><head><title>T</title></head><body>
<h1 class="title">Book Title</h1>
<h1 id="book-title">Book Title</h1>
<h2 id="subtitle">A Subtitle</h2>
<h1 id="preface">Preface</h1>
<h1 id="part-one">Part One</h1>
<h2 id="essay-a">Essay A</h2>
<h2 id="essay-b">Essay B</h2>
</body></html>"""


class CollectHeadingsTests(unittest.TestCase):
    def test_starts_at_second_h1_and_skips_title(self):
        items = toc.collect_headings(SAMPLE)
        self.assertEqual(
            [(lvl, text) for lvl, _, text in items],
            [(1, "Preface"), (1, "Part One"), (2, "Essay A"), (2, "Essay B")],
        )

    def test_explicit_start_heading(self):
        items = toc.collect_headings(SAMPLE, start_heading="Part One")
        self.assertEqual([t for _, _, t in items],
                         ["Part One", "Essay A", "Essay B"])

    def test_level_filter(self):
        items = toc.collect_headings(SAMPLE, levels=(1,))
        self.assertEqual([t for _, _, t in items], ["Preface", "Part One"])


class InsertTocTests(unittest.TestCase):
    def test_inserts_block_and_ascii_ids(self):
        html, items = toc.insert_toc(SAMPLE, ["12", "14", "14", "20"])
        self.assertIn(toc.BEGIN, html)
        self.assertIn('id="book-toc-style"', html)
        self.assertIn("#sec001", html)
        self.assertNotIn('id="preface"', html)
        self.assertIn(">12<", html)
        # heading itself keeps its text
        self.assertIn(">Preface</h1>", html)

    def test_toc_sits_before_first_listed_heading(self):
        html, _ = toc.insert_toc(SAMPLE)
        self.assertLess(html.index(toc.BEGIN), html.index(">Preface</h1>"))
        self.assertGreater(html.index(toc.BEGIN), html.index(">A Subtitle</h2>"))

    def test_idempotent(self):
        once, _ = toc.insert_toc(SAMPLE, ["1"])
        twice, items = toc.insert_toc(once, ["2"])
        self.assertEqual(twice.count(toc.BEGIN), 1)
        self.assertEqual(twice.count('id="book-toc-style"'), 1)
        self.assertEqual(len(items), 4)

    def test_without_numbers_has_no_page_spans(self):
        html, _ = toc.insert_toc(SAMPLE)
        self.assertNotIn('class="toc-page"', html)

    def test_repeated_headings_all_listed(self):
        html = SAMPLE.replace("</body>", "<h2 id='dup-one'>Same</h2><h2 id='dup-two'>Same</h2></body>")
        _, items = toc.insert_toc(html)
        self.assertEqual([t for _, _, t in items].count("Same"), 2)

    def test_no_headings_raises(self):
        with self.assertRaises(ValueError):
            toc.insert_toc("<html><body><p>nothing</p></body></html>")


class TitleTests(unittest.TestCase):
    def test_localized_titles(self):
        self.assertEqual(toc.toc_title_for("zh"), "目录")
        self.assertEqual(toc.toc_title_for("ja-JP"), "目次")
        self.assertEqual(toc.toc_title_for("fr"), "Contents")
        self.assertEqual(toc.toc_title_for("zh", "总目"), "总目")


class ResolvePdfPagesTests(unittest.TestCase):
    def _make_pdf(self, path):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        doc = fitz.open()
        # page 1: cover, no folio
        doc.new_page().insert_text((72, 72), "cover", fontsize=9)
        # page 2: heading "Preface" (18pt) + folio 1
        page = doc.new_page()
        page.insert_text((72, 72), "Preface", fontsize=18)
        page.insert_text((300, 760), "1", fontsize=9)
        # page 3: heading "Part One" + folio 2
        page = doc.new_page()
        page.insert_text((72, 72), "Part One", fontsize=18)
        page.insert_text((300, 760), "2", fontsize=9)
        doc.save(path)

    def test_maps_headings_to_printed_folios(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "book.pdf")
            self._make_pdf(pdf)
            pages = toc.resolve_pdf_pages(pdf, ["Preface", "Part One"])
            self.assertEqual(pages, ["1", "2"])

    def test_missing_heading_reports_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "book.pdf")
            self._make_pdf(pdf)
            pages = toc.resolve_pdf_pages(pdf, ["Preface", "Not There"])
            self.assertEqual(pages, ["1", ""])


if __name__ == "__main__":
    unittest.main()
