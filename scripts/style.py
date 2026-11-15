#!/usr/bin/env python3
"""Translation style presets.

A style is a short list of *executable* rules, not adjectives. Every sub-agent
receives the same block, which is what keeps 300 independent translations from
drifting into three different registers.

    python3 scripts/style.py list
    python3 scripts/style.py show readable
    python3 scripts/style.py resolve readable      # prints the block for a prompt
"""

import argparse
import os
import sys

STYLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles")
DEFAULT_STYLE = "scholarly"


def available():
    """Style names found in scripts/styles/, sorted, with the default first."""
    if not os.path.isdir(STYLE_DIR):
        return []
    names = sorted(f[:-3] for f in os.listdir(STYLE_DIR) if f.endswith(".md"))
    if DEFAULT_STYLE in names:
        names.remove(DEFAULT_STYLE)
        names.insert(0, DEFAULT_STYLE)
    return names


def load(name):
    """Return the rule text for a style (heading line removed)."""
    if not name:
        name = DEFAULT_STYLE
    path = os.path.join(STYLE_DIR, f"{name}.md")
    if not os.path.isfile(path):
        raise ValueError(
            f"unknown style {name!r}; available: {', '.join(available())}"
        )
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().strip().split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return name, "\n".join(lines).strip()


def block(name):
    """Prompt-ready block, or empty string for no style."""
    if not name or name == "none":
        return ""
    _, text = load(name)
    return "## 翻译风格（必须全书一致）\n\n" + text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["list", "show", "resolve"])
    parser.add_argument("style", nargs="?", default=None)
    args = parser.parse_args(argv)

    if args.command == "list":
        for name in available():
            marker = " (default)" if name == DEFAULT_STYLE else ""
            print(f"{name}{marker}")
        return 0

    try:
        if args.command == "show":
            name, text = load(args.style)
            print(f"# {name}\n\n{text}")
        else:
            print(block(args.style))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
