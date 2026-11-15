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

import join_chunk  # noqa: E402
import split_chunk  # noqa: E402


class SplitTextTests(unittest.TestCase):
    def test_splits_into_requested_parts_without_loss(self):
        text = "\n\n".join(f"段{i}。" * 3 for i in range(20))
        parts = split_chunk.split_text(text, 2)
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.strip() for p in parts))
        joined = "".join(p.replace("\n", "") for p in parts)
        self.assertEqual(
            joined.replace(" ", ""),
            text.replace("\n", "").replace(" ", ""),
        )

    def test_prefers_a_heading_boundary(self):
        paras = [f"段{i}。" for i in range(10)]
        paras[6] = "# 第六章 转折"
        text = "\n\n".join(paras)
        parts = split_chunk.split_text(text, 2)
        self.assertTrue(parts[1].startswith("# 第六章"))

    def test_rejects_tiny_chunk(self):
        with self.assertRaises(SystemExit):
            split_chunk.split_text("只有一段。", 2)


class SplitJoinTests(unittest.TestCase):
    def _prepare(self, tmp):
        src = os.path.join(tmp, "chunk0002.md")
        Path(src).write_text("\n\n".join(f"段落{i}的内容。" for i in range(12)), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = split_chunk.main([tmp, "chunk0002", "--parts", "2"])
        self.assertEqual(rc, 0)
        return src

    def test_split_creates_parts_and_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp)
            for name in ("chunk0002a.md", "chunk0002b.md",
                         os.path.join("prompts", "chunk0002a.md")):
                self.assertTrue(os.path.exists(os.path.join(tmp, name)), name)

    def test_join_merges_meta_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp)
            Path(os.path.join(tmp, "output_chunk0002a.md")).write_text(
                "\n\n".join(f"第一部分第{i}段译文。" for i in range(6)) + "\n", encoding="utf-8")
            Path(os.path.join(tmp, "output_chunk0002b.md")).write_text(
                "\n\n".join(f"第二部分第{i}段译文。" for i in range(6)) + "\n", encoding="utf-8")
            Path(os.path.join(tmp, "output_chunk0002a.meta.json")).write_text(
                json.dumps({"schema_version": 1, "new_entities": [], "alias_hypotheses": [],
                            "attribute_hypotheses": [], "used_term_sources": ["Hayek"],
                            "conflicts": []}), encoding="utf-8")
            Path(os.path.join(tmp, "output_chunk0002b.meta.json")).write_text(
                json.dumps({"schema_version": 1, "new_entities": [], "alias_hypotheses": [],
                            "attribute_hypotheses": [], "used_term_sources": ["Mises"],
                            "conflicts": []}), encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = join_chunk.main([tmp, "chunk0002"])
            self.assertEqual(rc, 0, buf.getvalue())
            joined = Path(os.path.join(tmp, "output_chunk0002.md")).read_text(encoding="utf-8")
            self.assertIn("第一部分第0段译文", joined)
            self.assertIn("第二部分第5段译文", joined)
            meta = json.loads(Path(os.path.join(tmp, "output_chunk0002.meta.json")).read_text(encoding="utf-8"))
            self.assertEqual(meta["used_term_sources"], ["Hayek", "Mises"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "output_chunk0002a.md")))

    def test_join_keeps_parts_when_still_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp)
            Path(os.path.join(tmp, "output_chunk0002a.md")).write_text("短。\n", encoding="utf-8")
            Path(os.path.join(tmp, "output_chunk0002b.md")).write_text("短。\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = join_chunk.main([tmp, "chunk0002"])
            self.assertEqual(rc, 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "output_chunk0002a.md")))


if __name__ == "__main__":
    unittest.main()
