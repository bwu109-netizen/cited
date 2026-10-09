"""List lines with CJK characters in tracked files, grouped by file.

Reader-facing files (Markdown, LICENSE, text) are listed line by line; code and data files are only counted,
split into comment lines and other lines (strings, data), because Chinese there is usually intended
(A-share / HK company names, quotes from filings, Chinese UI strings, Chinese-language prompts).

  .venv/bin/python scripts/cjk_scan.py [--lines]      # --lines also prints every reader-facing line
"""
import re
import subprocess
import sys
from collections import defaultdict

CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
READER = re.compile(r"(\.md|\.txt|LICENSE|\.example)$")
CODE = re.compile(r"\.(py|js|css|html|yml|yaml|toml|sh)$")
COMMENT = {".py": "#", ".yml": "#", ".yaml": "#", ".toml": "#", ".sh": "#", ".js": "//", ".css": "/*", ".html": "<!--"}


def files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and not f.startswith("data/")]


def main():
    show = "--lines" in sys.argv
    reader, code, data = {}, {}, {}
    for f in files():
        try:
            lines = open(f, encoding="utf-8").read().split("\n")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        hits = [(n, ln) for n, ln in enumerate(lines, 1) if CJK.search(ln)]
        if not hits:
            continue
        if READER.search(f):
            reader[f] = (hits, len(lines))
        elif CODE.search(f):
            ext = "." + f.rsplit(".", 1)[-1]
            c = COMMENT[ext]
            com = sum(1 for _, ln in hits if ln.strip().startswith((c, '"""', "'''", "*")))
            code[f] = (com, len(hits) - com)
        else:
            data[f] = len(hits)

    print("## Reader-facing files (Markdown / text)\n")
    print("| file | lines with CJK | total lines |\n|---|---|---|")
    for f, (h, total) in sorted(reader.items(), key=lambda x: -len(x[1][0])):
        print(f"| {f} | {len(h)} | {total} |")
    if show:
        for f, (h, _) in sorted(reader.items()):
            print(f"\n### {f}")
            for n, ln in h:
                print(f"{n}: {ln[:160]}")
    print("\n## Code (count only: comment lines / other lines such as strings)\n")
    print("| file | comment lines | other lines |\n|---|---|---|")
    for f, (com, other) in sorted(code.items()):
        print(f"| {f} | {com} | {other} |")
    print("\n## Data files (count only)\n")
    print("| file | lines with CJK |\n|---|---|")
    for f, n in sorted(data.items()):
        print(f"| {f} | {n} |")


if __name__ == "__main__":
    main()
