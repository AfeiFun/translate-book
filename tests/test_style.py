import contextlib
import io
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import style  # noqa: E402


class StyleTests(unittest.TestCase):
    def test_default_is_listed_first(self):
        names = style.available()
        self.assertEqual(names[0], "scholarly")
        for name in ("readable", "literary", "plain", "bilingual"):
            self.assertIn(name, names)

    def test_load_strips_heading(self):
        name, text = style.load("readable")
        self.assertEqual(name, "readable")
        self.assertFalse(text.startswith("#"))
        self.assertIn("欧化", text)

    def test_block_is_prompt_ready(self):
        block = style.block("literary")
        self.assertTrue(block.startswith("## 翻译风格"))
        self.assertIn("节奏", block)

    def test_none_means_no_block(self):
        self.assertEqual(style.block("none"), "")
        self.assertEqual(style.block(""), "")

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            style.load("shakespearean")

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(style.main(["list"]), 0)
            self.assertEqual(style.main(["show", "plain"]), 0)
            self.assertEqual(style.main(["resolve", "bilingual"]), 0)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(style.main(["resolve", "nope"]), 1)
        self.assertIn("unknown style", err.getvalue())


if __name__ == "__main__":
    unittest.main()
