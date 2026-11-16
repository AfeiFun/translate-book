import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_chunks  # noqa: E402


class CheckChunkTests(unittest.TestCase):
    def _write(self, tmp, name, text):
        path = os.path.join(tmp, name)
        Path(path).write_text(text, encoding="utf-8")
        return path

    def test_clean_translation_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(tmp, "output_chunk0001.md", "# 标题\n\n这是一段中文译文。\n")
            src = self._write(tmp, "chunk0001.md", "# Title\n\nThis is English.\n")
            self.assertEqual(qa_chunks.check_chunk(out, src), [])

    def test_empty_and_untranslated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(qa_chunks.check_chunk(self._write(tmp, "a.md", "  \n"))[0], "empty output")
            self.assertIn("no CJK", qa_chunks.check_chunk(self._write(tmp, "b.md", "Just English here."))[0])

    def test_ocr_tilde_and_fences(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = qa_chunks.check_chunk(self._write(tmp, "c.md", "中文 pa~ 结尾\n```\ncode\n"))
            joined = "; ".join(problems)
            self.assertIn("tilde", joined)
            self.assertIn("code fences", joined)

    def test_heading_inflation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(tmp, "output_chunk0002.md", "## 一\n## 二\n## 三\n## 四\n")
            src = self._write(tmp, "chunk0002.md", "plain text no headings\n")
            problems = qa_chunks.check_chunk(out, src)
            self.assertTrue(any("headings inflated" in p for p in problems))

    def test_missing_output_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "manifest.json")).write_text(
                json.dumps({"chunks": [{"id": "chunk0001"}]}), encoding="utf-8")
            ids, findings = qa_chunks.run(tmp)
            self.assertEqual(ids, ["chunk0001"])
            self.assertEqual(findings["chunk0001"], ["missing output"])

    def test_main_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "chunk0001.md")).write_text("# T\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(qa_chunks.main([tmp]), 1)
            Path(os.path.join(tmp, "output_chunk0001.md")).write_text("中文译文\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(qa_chunks.main([tmp]), 0)

    def test_count_markdown_assets_and_book_conservation(self):
        sample = (
            "![图 1](images/a.png)\n"
            "<img src=\"images/b.jpg\" alt=\"b\">\n"
            "```md\n"
            "| fake | table |\n"
            "| --- | --- |\n"
            "```\n\n"
            "| 列1 | 列2 |\n"
            "| --- | ---: |\n"
            "| A | 1 |\n\n"
            "<table><thead><tr><th>X</th></tr></thead></table>\n"
        )
        imgs, tbls = qa_chunks.count_markdown_assets(sample)
        self.assertEqual(imgs, 2)
        self.assertEqual(tbls, 2)

        with tempfile.TemporaryDirectory() as tmp:
            Path(os.path.join(tmp, "chunk0001.md")).write_text("# T\n", encoding="utf-8")
            Path(os.path.join(tmp, "output_chunk0001.md")).write_text("只有一段中文。\n", encoding="utf-8")
            Path(os.path.join(tmp, "pdf_assets_audit.json")).write_text(
                json.dumps({
                    "expected_figures": 1,
                    "expected_tables": 1,
                    "vector_figure_ids": ["2.1"],
                    "tables": [{"id": "3.1", "pages": [5]}],
                }),
                encoding="utf-8",
            )
            _, findings = qa_chunks.run(tmp)
            self.assertIn("_book", findings)
            joined = "; ".join(findings["_book"])
            self.assertIn("missing figures", joined)
            self.assertIn("missing tables", joined)

            Path(os.path.join(tmp, "output_chunk0001.md")).write_text(sample + "\n中文内容。\n", encoding="utf-8")
            _, findings_ok = qa_chunks.run(tmp)
            self.assertNotIn("_book", findings_ok)


if __name__ == "__main__":
    unittest.main()
