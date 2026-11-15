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

import verify_chunk  # noqa: E402


PARA = "这是一个完整的段落，用来模拟译文。\n\n"


def write(tmp, name, text):
    path = os.path.join(tmp, name)
    Path(path).write_text(text, encoding="utf-8")
    return path


class VerifyChunkTests(unittest.TestCase):
    def test_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0001.md", PARA * 5)
            write(tmp, "output_chunk0001.md", PARA * 5)
            verdict = verify_chunk.check(tmp, "chunk0001")
            self.assertEqual(verdict["status"], "ok")
            self.assertEqual(verdict["block_ratio"], 1.0)

    def test_missing_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0001.md", PARA)
            self.assertEqual(verify_chunk.check(tmp, "chunk0001")["status"], "missing")
            write(tmp, "output_chunk0001.md", "   \n")
            self.assertEqual(verify_chunk.check(tmp, "chunk0001")["status"], "empty")

    def test_truncated_detected_by_block_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0002.md", PARA * 20)
            write(tmp, "output_chunk0002.md", PARA * 6)
            verdict = verify_chunk.check(tmp, "chunk0002")
            self.assertEqual(verdict["status"], "truncated")
            self.assertIn("6/20", verdict["detail"])

    def test_small_chunk_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0003.md", PARA * 2)
            write(tmp, "output_chunk0003.md", PARA)
            self.assertEqual(verify_chunk.check(tmp, "chunk0003")["status"], "ok")

    def test_unterminated(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0004.md", ("这是一个完整句子。" * 100) + "\n")
            write(tmp, "output_chunk0004.md", "这是一段没有写完的长句子" + "啊" * 60)
            self.assertEqual(verify_chunk.check(tmp, "chunk0004")["status"], "unterminated")

    def test_cli_json_and_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0001.md", PARA * 20)
            write(tmp, "output_chunk0001.md", PARA)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(verify_chunk.main([tmp]), 1)
            self.assertIn("truncated", buf.getvalue())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(verify_chunk.main([tmp, "--json"]), 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["problems"][0]["status"], "truncated")

    def test_collect_skips_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "chunk0001.md", PARA)
            write(tmp, "output_chunk0001.md", PARA)
            self.assertEqual(verify_chunk.collect_ids(tmp), ["chunk0001"])


if __name__ == "__main__":
    unittest.main()
