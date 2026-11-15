import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_prompt  # noqa: E402


class BuildPromptTests(unittest.TestCase):
    def _temp_dir(self, tmp, chunks=("chunk0001",)):
        for cid in chunks:
            Path(os.path.join(tmp, f"{cid}.md")).write_text(
                f"# Chapter\n\nSome English body for {cid}.\n", encoding="utf-8")
        return tmp

    def test_renders_all_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._temp_dir(tmp, ("chunk0001", "chunk0002"))
            out = os.path.join(tmp, "prompt.md")
            build_prompt.render(tmp, "chunk0002", "简体中文", "readable", "保留注释原文", out)
            text = Path(out).read_text(encoding="utf-8")
            self.assertIn("简体中文", text)
            self.assertIn("## 翻译风格", text)
            self.assertIn("保留注释原文", text)
            self.assertIn(os.path.join(tmp, "chunk0002.md"), text)
            self.assertIn(os.path.join(tmp, "output_chunk0002.md"), text)
            self.assertIn("邻居上下文", text)          # chunk0001 provides the previous excerpt
            self.assertIn('"schema_version"', text)
            self.assertNotIn("{TERM_TABLE}", text)

    def test_no_glossary_drops_term_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._temp_dir(tmp)
            out = os.path.join(tmp, "prompt.md")
            build_prompt.render(tmp, "chunk0001", "简体中文", "scholarly", None, out)
            text = Path(out).read_text(encoding="utf-8")
            self.assertNotIn("## 术语一致性", text)
            self.assertNotIn("## 邻居上下文", text)     # no neighbouring chunk
            self.assertIn("## 完成要求", text)

    def test_custom_from_file_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._temp_dir(tmp)
            notes = os.path.join(tmp, "notes.md")
            Path(notes).write_text("本书为定本，注释保留英文。", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = build_prompt.main([tmp, "chunk0001", "--custom", notes])
            self.assertEqual(rc, 0)
            text = Path(os.path.join(tmp, "prompts", "chunk0001.md")).read_text(encoding="utf-8")
            self.assertIn("注释保留英文", text)

    def test_unknown_style_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._temp_dir(tmp)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                rc = build_prompt.main([tmp, "chunk0001", "--style", "nope"])
            self.assertEqual(rc, 1)
            self.assertIn("unknown style", err.getvalue())

    def test_missing_chunk_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                build_prompt.render(tmp, "chunk9999", "简体中文", "scholarly", None, None)


if __name__ == "__main__":
    unittest.main()
