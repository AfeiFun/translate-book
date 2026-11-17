import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import convert  # noqa: E402
import ocr_unlimited  # noqa: E402


class DecodeBpeTextTests(unittest.TestCase):
    def test_decodes_byte_level_bpe_spaces_newlines_and_utf8(self):
        raw = "HelloĠworld!ĊTheĠsuccessâĢĶsomeĠclaimâĢĶofĠâĢľpower.âĢĿ"
        self.assertEqual(
            ocr_unlimited.decode_bpe_text(raw),
            'Hello world!\nThe success—some claim—of “power.”',
        )

    def test_leaves_plain_utf8_untouched(self):
        plain = "Regular text with — em-dash and 中文。"
        self.assertEqual(ocr_unlimited.decode_bpe_text(plain), plain)


class ParseAndStitchTests(unittest.TestCase):
    def test_strips_header_page_number_and_stitches_hyphen_and_table(self):
        p1_raw = (
            "<|det|>page_number [185, 73, 206, 88]<|/det|>6\n"
            "<|det|>header [247, 72, 517, 90]<|/det|>Power in Organizations\n"
            "<|det|>sub_title [180, 95, 420, 115]<|/det|>Introduction\n"
            "<|det|>text [180, 120, 920, 200]<|/det|>As they devel-\n"
        )
        p2_raw = (
            "<|det|>header [247, 72, 517, 90]<|/det|>Power in Organizations\n"
            "<|det|>text [180, 100, 920, 180]<|/det|>oped new political skills.\n"
            "<|det|>text [180, 190, 600, 220]<|/det|>Table 2-1: Summary Scores\n"
            "<|det|>table [180, 230, 900, 450]<|/det|><table><tr><th>A</th></tr>\n<tr><td>1</td></tr></table>\n"
        )
        p1 = ocr_unlimited.parse_unlimited_ocr_output(p1_raw)
        p2 = ocr_unlimited.parse_unlimited_ocr_output(p2_raw)

        md, audit = ocr_unlimited.stitch_pages([
            {"page": 1, "blocks": p1["blocks"], "cropped_figures": []},
            {"page": 2, "blocks": p2["blocks"], "cropped_figures": []},
        ])
        self.assertNotIn("Power in Organizations", md)
        self.assertIn("## Introduction", md)
        self.assertIn("As they developed new political skills.", md)
        self.assertIn("<table><tr><th>A</th></tr><tr><td>1</td></tr></table>", md)
        self.assertEqual(audit["expected_tables"], 1)
        self.assertEqual(audit["tables"][0]["id"], "2-1")

    def test_crops_figure_region_from_page_render(self):
        raw = (
            "<|det|>image_caption [250, 100, 750, 140]<|/det|>Figure 6-1\nCommunication Networks\n"
            "<|det|>image [200, 200, 450, 500]<|/det|>\n"
            "<|det|>image [550, 200, 800, 500]<|/det|>\n"
        )
        parsed = ocr_unlimited.parse_unlimited_ocr_output(raw)
        with tempfile.TemporaryDirectory() as tmp:
            page_png = os.path.join(tmp, "page.png")
            Image.new("RGB", (1000, 1000), (255, 255, 255)).save(page_png)
            img_dir = os.path.join(tmp, "images")
            cropped = ocr_unlimited.crop_page_figures(page_png, parsed, img_dir, 123)
            self.assertEqual(len(cropped), 1)
            self.assertEqual(cropped[0]["rel_path"], "images/p0123_fig1.png")
            self.assertTrue(os.path.isfile(os.path.join(img_dir, "p0123_fig1.png")))
            md, audit = ocr_unlimited.stitch_pages([
                {"page": 123, "blocks": parsed["blocks"], "cropped_figures": cropped}
            ])
            self.assertIn("![Figure 6-1](images/p0123_fig1.png)", md)
            self.assertEqual(audit["expected_figures"], 1)


class ScannedPdfDetectionTests(unittest.TestCase):
    def test_detects_scanned_vs_text_pdf(self):
        fitz = convert._import_pymupdf()
        if fitz is None:
            self.skipTest("PyMuPDF not installed")

        with tempfile.TemporaryDirectory() as tmp:
            text_pdf = os.path.join(tmp, "born_digital.pdf")
            d1 = fitz.open()
            p1 = d1.new_page(width=400, height=500)
            p1.insert_text((50, 100), "Normal born digital text.", fontsize=12)
            d1.save(text_pdf)
            d1.close()
            self.assertFalse(convert.is_scanned_pdf(text_pdf))

            scan_pdf = os.path.join(tmp, "scanned.pdf")
            img_path = os.path.join(tmp, "scan.png")
            Image.new("RGB", (400, 500), (240, 240, 240)).save(img_path)
            d2 = fitz.open()
            p2 = d2.new_page(width=400, height=500)
            p2.insert_image(fitz.Rect(0, 0, 400, 500), filename=img_path)
            d2.save(scan_pdf)
            d2.close()
            self.assertTrue(convert.is_scanned_pdf(scan_pdf))


if __name__ == "__main__":
    unittest.main()
