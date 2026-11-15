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

import smartquote  # noqa: E402


class SmartQuoteTests(unittest.TestCase):
    def test_pairs_quotes_and_preserves_html_tags(self):
        line = '他说"你好"，并看到 <img alt="pic" src="a.jpg"> 的"标题"。'
        out, odd = smartquote.transform_text(line)
        self.assertEqual(odd, 0)
        self.assertEqual(out, '他说“你好”，并看到 <img alt="pic" src="a.jpg"> 的“标题”。')

    def test_skips_odd_line_and_code_fences(self):
        text = '正常"成对"引号\n奇数"引号不改\n```\n"code"\n```'
        out, odd = smartquote.transform_text(text)
        self.assertEqual(odd, 1)
        self.assertIn("正常“成对”引号", out)
        self.assertIn('奇数"引号不改', out)
        self.assertIn('"code"', out)

    def test_cli_dry_run_and_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "output_chunk0001.md"
            p.write_text('测试"引号"转换。\n', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                smartquote.main([tmp])
            self.assertIn('"引号"', p.read_text(encoding="utf-8"))
            with contextlib.redirect_stdout(io.StringIO()):
                smartquote.main([tmp, "--apply"])
            self.assertIn("“引号”", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
