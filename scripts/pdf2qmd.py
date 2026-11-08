#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf4llm", "pyyaml", "requests", "beautifulsoup4"]
# ///
"""First-pass conversion of a reference PDF (a vendor manual) to a Quarto page.

    ./scripts/pdf2qmd.py source/files/Manual.pdf --out manuals
    ./scripts/pdf2qmd.py --diff --render --check manuals/*/*.qmd
    ./scripts/pdf2qmd.py --tidy manuals/*/*.qmd       # re-run the cleanup
    ./scripts/pdf2qmd.py --push manuals/my-manual/my-manual.qmd

Writes <out>/<slug>/<slug>.qmd plus its images (fig-01.png ...). The
draft is NOT finished: it is machine output that a person (or an agent with
the PDF open) must review (skills/review-manual). Every image gets alt text
"TODO-ALT", and --check fails until each has real alt text of at most 120
characters, so an unreviewed draft cannot be pushed by accident.

The YAML header carries `source-pdf:` (the PDF's path, relative to the
workspace) and `canvas-title:` (the page title). modules.py can then link
the page in place of the PDF.

Locally written instructions are not converted this way. They are
transcribed by hand into a guide (skills/transcribe-guide).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
_cfg = config.settings_or_defaults()
ROOT = _cfg.root if _cfg else Path.cwd()
ALT_LIMIT = _cfg.alt_limit if _cfg else 120


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def display(name: str) -> str:
    """A page title from a file name: "Hall_Effect-Manual.pdf" -> "Hall Effect Manual"."""
    stem = Path(name).stem.replace("_", " ")
    stem = re.sub(r"(?<=[a-z])-(?=[A-Z])", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def slug_of(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower())
    return s.strip("-")


# Characters from the Symbol font land in the Private Use Area; map the
# common ones back (TeachSpin manuals use them for every Greek letter).
SYMBOL_FONT = {
    "\uf061": "α", "\uf062": "β", "\uf067": "γ", "\uf064": "δ", "\uf044": "Δ",
    "\uf065": "ε", "\uf06c": "λ", "\uf06d": "μ", "\uf06e": "ν", "\uf070": "π",
    "\uf072": "ρ", "\uf073": "σ", "\uf074": "τ", "\uf066": "φ", "\uf063": "χ",
    "\uf079": "ψ", "\uf077": "ω", "\uf057": "Ω", "\uf071": "θ", "\uf0b1": "±",
    "\uf0bb": "≈", "\uf0b4": "×", "\uf0d7": "·", "\uf0d6": "√", "\uf0b0": "°",
    "\uf0ae": "→", "\uf0a3": "≤", "\uf0b3": "≥", "\uf0b5": "∝", "\uf0a5": "∞",
}


def clean(md: str) -> str:
    """Remove the predictable noise pymupdf4llm leaves in vendor PDFs."""
    md = md.translate(str.maketrans(SYMBOL_FONT))
    # OCR of the text inside pictures: labels, logos, scribbles.
    md = re.sub(r"<!-- Start of picture text -->.*?<!-- End of picture text -->",
                "", md, flags=re.S)
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"</?mark>", "", md)
    # Bold inside headings: "#### **1. Notes**" -> "#### 1. Notes".
    md = re.sub(r"^(#+)\s*\*\*(.+?)\*\*\s*$", r"\1 \2", md, flags=re.M)
    # Lines that are only a page number.
    md = re.sub(r"^\s*\d{1,3}\s*$", "", md, flags=re.M)
    # Every image needs alt text; mark it for review.
    md = re.sub(r"!\[\]\(([^)]+)\)", r'![](\1){fig-alt="TODO-ALT"}', md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def shift_headings(md: str) -> str:
    """Make the shallowest heading level 1 (Canvas shows it as h2)."""
    levels = [len(m) for m in re.findall(r"^(#+) ", md, flags=re.M)]
    if not levels or min(levels) == 1:
        return md
    k = min(levels) - 1
    return re.sub(r"^(#+) ", lambda m: "#" * (len(m.group(1)) - k) + " ",
                  md, flags=re.M)


MATH_GARBLE = re.compile(r"_\S{1,6}_\s{2,}\S|\s{3,}_\S{1,6}_")


def tidy(md: str, title: str) -> str:
    """Second-pass cleanup, from the Planck's constant pilot. Idempotent, so
    it can be re-run over a draft (`--tidy`) without harm."""
    # Strikeout and empty-bold debris.
    md = re.sub(r"~~.*?~~", "", md)
    md = re.sub(r"\*\*\s*\*\*", " ", md)
    md = re.sub(r"\*\*<sup>\*\*(.*?)\*\*</sup>\*\*", r"<sup>\1</sup>", md)
    # Running headers and footers: short lines repeated three or more times.
    lines = md.split("\n")
    counts: dict[str, int] = {}
    for ln in lines:
        key = ln.strip()
        if key and len(key) < 120 and not key.startswith(("!", "|", "#", "-")):
            counts[key] = counts.get(key, 0) + 1
    # Only lines that look like running heads or footers: real notes and
    # procedure steps also repeat word for word (Keithley 2110 lost dozens).
    footerish = re.compile(r"©|®|™|www\.|https?://|@|\bRev\b|\bpage\b|\d{3}-\d{3,}"
                           r"|^[A-Z0-9 ,.&/-]{4,}$", re.I)
    repeated = {k for k, v in counts.items()
                if v >= 3 and len(k) < 90 and footerish.search(k)
                and not re.fullmatch(r"[*_\s]*", k)}
    lines = [ln for ln in lines if ln.strip() not in repeated]
    md = "\n".join(lines)
    # Hyphens lost at line breaks: "socalled" when "so-called" also occurs.
    for a, b in set(re.findall(r"\b([A-Za-z]{2,})-([A-Za-z]{2,})\b", md)):
        md = re.sub(rf"\b{a}{b}\b", f"{a}-{b}", md)
    # Numbered sections set the heading levels, whatever level pymupdf chose:
    # "1. Notes" -> #, "6.1 ..." -> ##, "6.1.2 ..." -> ###.
    numbered = re.findall(r"^#+ (\d+(?:\.\d+)*)\.?\s", md, flags=re.M)
    if len(numbered) >= 3:
        def level(m: re.Match) -> str:
            depth = m.group(2).count(".") + 1 - m.group(2).endswith(".")
            return "#" * max(1, depth) + " " + m.group(2) + m.group(3)
        md = re.sub(r"^(#+) (\d+(?:\.\d+)*\.?)(\s.*)$", level, md, flags=re.M)
        # Unnumbered "headings" before the first numbered one are the title
        # block (vendor, product, catalogue numbers): plain paragraphs.
        first = re.search(r"^# \d", md, flags=re.M)
        if first:
            head = re.sub(r"^#+ ", "", md[: first.start()], flags=re.M)
            md = head + md[first.start():]
    # Headings that are really garbled equations, and garbled math anywhere:
    # mark for review; --check fails on the marker.
    out = []
    for ln in md.split("\n"):
        if MATH_GARBLE.search(ln) and "TODO-MATH" not in ln:
            ln = "TODO-MATH: " + re.sub(r"^#+ ", "", ln)
        out.append(ln)
    md = "\n".join(out)
    # No "Source" section at the end (the instructor's call in the pilot
    # course): the page title names the manual, and the YAML keeps source-pdf.
    return re.sub(r"\n{3,}", "\n\n", md)


def split_header(text: str) -> tuple[str, str]:
    """(YAML header block including fences, body)."""
    _, yml, body = text.split("---", 2)
    return f"---{yml}---", body


def convert(pdf: Path, out_dir: Path, title: str | None = None) -> Path:
    import pymupdf4llm

    title = title or display(pdf.name)
    slug = slug_of(title)
    out = out_dir / slug
    out.mkdir(parents=True, exist_ok=True)
    images = out / "images"
    md = pymupdf4llm.to_markdown(str(pdf), write_images=True,
                                 image_path=str(images),
                                 image_format="png", dpi=150)
    # pymupdf4llm names images after the PDF (spaces, apostrophes) and writes
    # paths relative to the working directory. Rename them fig-NN.png and
    # point at them relative to the qmd.
    n = 0

    def rename(m: re.Match) -> str:
        nonlocal n
        src = Path(m.group(1))
        if not src.is_absolute():
            src = Path.cwd() / src
        n += 1
        dest = images / f"fig-{n:02d}{src.suffix}"
        src.rename(dest)
        return f"![](images/{dest.name})"

    md = re.sub(r"!\[\]\(([^)]+)\)", rename, md)
    body = tidy(shift_headings(clean(md)), title)
    header = {
        "title": title,
        "canvas-title": title,
        "source-pdf": rel(pdf),
        "format": {"html": {"toc": True, "toc-depth": 2,
                            "html-math-method": "mathjax"}},
    }
    qmd = out / f"{slug}.qmd"
    qmd.write_text("---\n" + yaml.safe_dump(header, sort_keys=False,
                                            allow_unicode=True)
                   + "---\n\n<!-- DRAFT from scripts/pdf2qmd.py: review "
                   "against the PDF before pushing. -->\n\n" + body)
    return qmd


def source_pdf(qmd: Path) -> Path | None:
    """The PDF a converted page came from (its source-pdf key)."""
    meta = yaml.safe_load(split_header(qmd.read_text())[0].strip("-")) or {}
    src = str(meta.get("source-pdf", ""))
    if not src:
        return None
    for pdf in (ROOT / src, qmd.parent / src):
        if pdf.is_file():
            return pdf
    return None


def missing_words(qmd: Path) -> list[str]:
    """Words of 4+ letters in the source PDF that the page never uses: the
    pilot's one-command completeness check. Footers show up here too, which
    is expected."""
    import subprocess

    pdf = source_pdf(qmd)
    if pdf is None:
        return []
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                          text=True).stdout
    words = lambda t: {w.lower() for w in re.findall(r"[A-Za-z]{4,}", t)}
    return sorted(words(text) - words(qmd.read_text()))


def missing_lines(qmd: Path) -> list[str]:
    """Sentence-length PDF lines that occur fewer times on the page than in
    the PDF. Catches dropped repeats (a note or step that recurs word for
    word), which the word diff cannot see. Lines on a large share of pages
    are running heads and are skipped."""
    import collections
    import subprocess

    pdf = source_pdf(qmd)
    if pdf is None:
        return []
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                          text=True).stdout
    norm = lambda x: re.sub(r"\s+", " ", re.sub(r"[`*_|\\~$#>]", "", x)).strip().lower()
    page = norm(qmd.read_text())
    pages = text.split("\f")
    count, on_pages = collections.Counter(), collections.Counter()
    for pg in pages:
        seen = set()
        for ln in pg.split("\n"):
            n = norm(ln)
            if len(n) >= 35:
                count[n] += 1
                seen.add(n)
        on_pages.update(seen)
    out = []
    for n, c in count.items():
        if on_pages[n] > max(3, len(pages) // 4):
            continue
        have = page.count(n)
        # A line found verbatim but fewer times is a dropped repeat. A line
        # not found at all is usually rewrapping, hyphenation or math, which
        # the word diff already covers.
        if 0 < have < c:
            out.append(f"{have}/{c}x  {n[:100]}")
    return out


def check_html(html: Path, qmd: Path) -> list[str]:
    """The rendered page, as YuJa sees it."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html.read_text(), "html.parser")
    main = soup.find("main") or soup
    problems = []
    # Text like "<No Data Selected>" is parsed as an HTML tag and silently
    # swallows the rest of the page. Every source heading must survive.
    body = split_header(qmd.read_text())[1]
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    want = len(re.findall(r"^#{1,6} ", body, flags=re.M))
    got = len(main.find_all(re.compile(r"^h[1-6]$"))) - (1 if main.find("h1", class_="title") else 0)
    if got < want:
        problems.append(f"rendered page has {got} headings but the source has {want}: "
                        "content was swallowed (escape any <Text> written in angle brackets)")
    for img in main.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if not alt:
            problems.append(f"rendered <img> without alt: {img.get('src')}")
        elif len(alt) > ALT_LIMIT:
            problems.append(f"rendered alt text is {len(alt)} characters")
    for table in main.find_all("table"):
        if not table.find("th"):
            problems.append("rendered table has no header cells")
    for a in main.find_all("a", href=True):
        # Quarto's per-line anchors in code blocks are aria-hidden, and
        # screen readers skip them.
        if a.get("aria-hidden") == "true" or a["href"].startswith("#cb"):
            continue
        if a.get_text(strip=True) in (a["href"], ""):
            problems.append(f"link text is the bare URL or empty: {a['href'][:60]}")
    return problems


def check(paths: list[Path], diff: bool = False, render: bool = False,
          lines: bool = False) -> int:
    """Local lint for the things YuJa scores, so most issues are caught
    before a push instead of after a rescan."""
    import subprocess

    bad = 0
    for p in paths:
        s = p.read_text()
        body = split_header(s)[1] if s.startswith("---") else s
        problems = []
        alts = re.findall(r'fig-alt="([^"]*)"', s) + re.findall(r'\balt="([^"]*)"', s)
        problems += ["image needs alt text" for a in alts if a in ("", "TODO-ALT")]
        problems += [f"alt text is {len(a)} characters (limit {ALT_LIMIT})"
                     for a in alts if len(a) > ALT_LIMIT]
        if re.search(r"!\[[^\]]*\]\([^)]+\)(?!\{)", s):
            problems.append("image without an attribute block (no alt text)")
        if "DRAFT from scripts/pdf2qmd.py" in s:
            problems.append("still marked DRAFT; review it and remove the marker")
        for marker in ("TODO-MATH",):
            if marker in s:
                problems.append(f"unresolved {marker}")
        comments = [c for c in re.findall(r"<!--.*?-->", body, flags=re.S)
                    if "DRAFT from" not in c and "NOTES.md" not in c]
        if comments:
            problems.append("HTML comment in student-facing source "
                            "(students can read it in View Source)")
        if "~~" in body:
            problems.append("strikeout debris (~~)")
        if re.search(r"(?<![(<\[\"])https?://\S+", body):
            problems.append("bare URL; give it descriptive link text")
        levels = [len(m) for m in re.findall(r"^(#+) ", body, flags=re.M)]
        for a, b in zip(levels, levels[1:]):
            if b > a + 1:
                problems.append(f"heading level skips from {a} to {b}")
                break
        if re.search(r"\[(click here|here|link|this)\]\(", s, flags=re.I):
            problems.append("non-descriptive link text")
        if render:
            r = subprocess.run(["quarto", "render", str(p), "--to", "html"],
                               capture_output=True, text=True)
            if r.returncode:
                problems.append("quarto render failed: "
                                + r.stderr.strip().splitlines()[-1][:200])
            else:
                problems += check_html(p.with_suffix(".html"), p)
        for msg in dict.fromkeys(problems):
            print(f"{rel(p)}: {msg}")
        if diff:
            gone = missing_words(p)
            if gone:
                print(f"{rel(p)}: {len(gone)} source words not on "
                      f"the page: {' '.join(gone[:60])}")
        if lines:
            short = missing_lines(p)
            if short:
                print(f"{rel(p)}: {len(short)} PDF lines appear fewer "
                      "times on the page than in the PDF (dropped repeats):")
                for ln in short[:40]:
                    print("    " + ln)
        bad += bool(problems)
    print(f"{len(paths) - bad}/{len(paths)} files pass")
    return 1 if bad else 0


def push(paths: list[Path]) -> int:
    """Check, render and push each finished page (unpublished). A page that
    fails the check is not pushed. Then add the page to its module
    (modules.py) in place of the PDF."""
    import subprocess

    failed = 0
    for p in paths:
        if check([p], render=True):
            print(f"not pushing {rel(p)}")
            failed += 1
            continue
        title = yaml.safe_load(split_header(p.read_text())[0].strip("-"))["canvas-title"]
        r = subprocess.run([str(SCRIPTS / "canvas.py"), "--yes", "push", "page",
                            str(p.with_suffix(".html")), "--title", title,
                            "--named-parts"],
                           capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or [r.stderr.strip()])[-1]
        print(f"{'pushed' if r.returncode == 0 else 'PUSH FAILED'} {title}: {last}")
        failed += r.returncode != 0
    return 1 if failed else 0


def retidy(paths: list[Path]) -> None:
    """Re-run the second-pass cleanup over existing drafts."""
    for p in paths:
        head, body = split_header(p.read_text())
        title = (yaml.safe_load(head.strip("-")) or {}).get("title", p.stem)
        p.write_text(head + tidy(body, title))
        print(f"tidied {rel(p)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", nargs="+", type=Path, metavar="QMD")
    ap.add_argument("--diff", action="store_true",
                    help="with --check: list source words missing from the page")
    ap.add_argument("--lines", action="store_true",
                    help="with --check: list PDF lines that occur fewer times on the page")
    ap.add_argument("--render", action="store_true",
                    help="with --check: render to HTML and lint the result")
    ap.add_argument("--tidy", nargs="+", type=Path, metavar="QMD",
                    help="re-run the second-pass cleanup on drafts")
    ap.add_argument("--push", nargs="+", type=Path, metavar="QMD",
                    help="check, render and push finished pages (unpublished)")
    ap.add_argument("pdfs", nargs="*", type=Path, help="PDFs to convert")
    ap.add_argument("--out", type=Path, default=Path("manuals"),
                    help="folder for the drafts (default: manuals/)")
    ap.add_argument("--title", help="page title (one PDF only; default from the file name)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing draft")
    args = ap.parse_args()
    if args.check:
        return check([p.resolve() for p in args.check], args.diff, args.render,
                     args.lines)
    if args.push:
        return push([p.resolve() for p in args.push])
    if args.tidy:
        retidy([p.resolve() for p in args.tidy])
        return 0
    if not args.pdfs:
        ap.error("give PDFs to convert, or --check/--tidy/--push")
    if args.title and len(args.pdfs) > 1:
        ap.error("--title works with one PDF only")
    out_dir = args.out.resolve()
    for pdf in args.pdfs:
        title = args.title or display(pdf.name)
        dest = out_dir / slug_of(title) / f"{slug_of(title)}.qmd"
        if dest.exists() and not args.force:
            print(f"skip {pdf.name} (already converted: {rel(dest)}; --force redoes it)")
            continue
        print(f"{pdf.name} -> {rel(convert(pdf.resolve(), out_dir, title))}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
