#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render one TikZ picture (read from stdin) to SVG + PDF, and print a manifest.

Called by tikz.lua for each .tikz, .circuitikz or .quantikz code block.

    echo '\\node[draw] {hi};' | ./tools/tikz.py --outdir figures --library tikz

Output on stdout, one line of JSON:
    {"file": "<abs path to .svg>", "pdf": "<abs path to .pdf>",
     "width": <pt>, "height": <pt>}

Figures are content-addressed by a hash of the source plus the library, so an
unchanged diagram is compiled once and reused on every later build. Compiling
LaTeX per diagram is slow; the cache is what makes it tolerable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Each library gets the minimum preamble it needs. `standalone` crops the page
# to the picture, so the SVG has no page margins to fight with.
PREAMBLES = {
    "tikz": r"\usepackage{tikz}",
    "circuitikz": "\n".join([
        r"\usepackage[siunitx, americanvoltages]{circuitikz}",
        # US-style gate shapes, which is what the course's figures have always
        # used and what students will meet in the textbooks.
        r"\ctikzset{logic ports=ieee}",
        r"\ctikzset{logic ports origin=center}",
    ]),
    "quantikz": "\n".join([
        r"\usepackage{tikz}",
        r"\usetikzlibrary{quantikz}",
    ]),
}

TEMPLATE = r"""\documentclass[border=2pt,varwidth=\maxdimen]{standalone}
\usepackage{lmodern}
%(preamble)s
%(extra)s
\begin{document}
%(body)s
\end{document}
"""


def render(source: str, library: str, outdir: Path, extra: str, force: bool) -> dict:
    key = hashlib.sha1(
        "\0".join([library, extra, source]).encode("utf-8")
    ).hexdigest()[:16]
    outdir.mkdir(parents=True, exist_ok=True)
    svg_path = outdir / f"tikz-{key}.svg"
    pdf_path = outdir / f"tikz-{key}.pdf"
    meta_path = outdir / f"tikz-{key}.json"

    if not force and svg_path.exists() and meta_path.exists() and pdf_path.exists():
        return json.loads(meta_path.read_text())

    tex = TEMPLATE % {
        "preamble": PREAMBLES.get(library, PREAMBLES["tikz"]),
        "extra": extra,
        "body": source,
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "fig.tex").write_text(tex, encoding="utf-8")
        run = subprocess.run(
            ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "fig.tex"],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        built = tmp_path / "fig.pdf"
        if run.returncode != 0 or not built.exists():
            log = (tmp_path / "fig.log")
            detail = ""
            if log.exists():
                errors = [
                    line
                    for line in log.read_text(errors="ignore").splitlines()
                    if line.startswith("!") or "Undefined control sequence" in line
                ]
                detail = "\n".join(errors[:6])
            raise SystemExit(
                f"tikz: lualatex failed for library {library!r}\n{detail or run.stdout[-800:]}"
            )

        shutil.copyfile(built, pdf_path)
        # pdftocairo rather than dvisvgm: dvisvgm's --pdf mode needs Ghostscript
        # or mutool wired in, and pdftocairo emits pure <path> geometry with no
        # text or font elements at all. That means the SVG has no font
        # dependency and draws identically everywhere, Canvas included.
        svg = subprocess.run(
            ["pdftocairo", "-svg", str(built), str(svg_path)],
            capture_output=True,
            text=True,
        )
        if svg.returncode != 0 or not svg_path.exists():
            raise SystemExit(f"tikz: pdftocairo failed\n{svg.stderr[-800:]}")

    width = height = None
    match = re.search(
        r'width=["\']([\d.]+)pt["\']\s+height=["\']([\d.]+)pt["\']',
        svg_path.read_text(encoding="utf-8", errors="ignore")[:2000],
    )
    if match:
        width, height = float(match.group(1)), float(match.group(2))

    meta = {
        "file": str(svg_path.resolve()),
        "pdf": str(pdf_path.resolve()),
        "width": width,
        "height": height,
        "library": library,
    }
    meta_path.write_text(json.dumps(meta))
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="figures")
    parser.add_argument("--library", default="tikz", choices=sorted(PREAMBLES))
    parser.add_argument("--preamble", default="", help="extra preamble lines")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = sys.stdin.read().strip()
    if not source:
        print("tikz: empty source", file=sys.stderr)
        return 1

    meta = render(
        source, args.library, Path(args.outdir), args.preamble, args.force
    )
    sys.stdout.write(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
