#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Sort the source course's documents into what to do with each.

    ./scripts/triage.py                 # every PDF/DOCX/PPTX under source/
    ./scripts/triage.py source/modules/03*/*.pdf

Writes triage.csv in the workspace: one row per document, with the facts
(pages, words, words per page, tagged, images) and a suggested action. The
suggestion is a guess from those facts and the file name; a person or the
agent reviews each row and fills the `decision` column with one of:

    guide    locally written instructions: transcribe by hand into a guide
             (skills/transcribe-guide)
    manual   vendor or reference document: pdf2qmd.py, then review
             (skills/review-manual)
    doi      a journal paper: link its DOI instead of hosting the PDF
    drop     template boilerplate or a duplicate: leave it out
    keep     keep as it is (only if it already passes, or is not student-facing)

Re-running keeps every decision already filled in. Needs poppler's
pdftotext, pdfinfo and pdfimages.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

FIELDS = ["path", "pages", "words", "words_per_page", "tagged", "images",
          "scanned", "suggested", "decision", "notes"]
DOCS = (".pdf", ".docx", ".doc", ".pptx", ".ppt")


def run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def facts(pdf: Path) -> dict:
    info = run("pdfinfo", str(pdf))
    pages = int(m.group(1)) if (m := re.search(r"^Pages:\s+(\d+)", info, re.M)) else 0
    tagged = "yes" if re.search(r"^Tagged:\s+yes", info, re.M) else "no"
    words = len(re.findall(r"[A-Za-z]{2,}", run("pdftotext", str(pdf), "-")))
    images = max(0, len(run("pdfimages", "-list", str(pdf)).splitlines()) - 2)
    wpp = round(words / pages) if pages else 0
    return {"pages": pages, "words": words, "words_per_page": wpp,
            "tagged": tagged, "images": images,
            # A page of real text has hundreds of words; a scan has none.
            "scanned": "yes" if pages and wpp < 30 else "no"}


def suggest(path: Path, f: dict) -> str:
    name = path.name.lower()
    if re.search(r"10\.\d{4,}|doi|journal|phys\.? ?rev|am\.? ?j\.? ?phys|arxiv", name):
        return "doi"
    if re.search(r"manual|user ?guide|datasheet|data sheet|brochure|spec", name):
        return "manual"
    if re.search(r"instruction|lab|procedure|handout|experiment|guide|worksheet", name):
        return "guide"
    if re.search(r"template|copy of|\(\d\)|syllabus template", name):
        return "drop"
    return "manual" if f.get("pages", 0) > 15 else "guide"


def main() -> int:
    cfg = config.settings()
    paths = [Path(p) for p in sys.argv[1:]] or sorted(
        p for p in cfg.source_dir.rglob("*") if p.suffix.lower() in DOCS)
    if not paths:
        raise SystemExit(f"no documents under {cfg.source_dir}; run export_course.py first")
    out = cfg.root / "triage.csv"
    old = {}
    if out.exists():
        with open(out, newline="") as fh:
            old = {r["path"]: r for r in csv.DictReader(fh)}
    rows = []
    for p in paths:
        rel = str(p.resolve().relative_to(cfg.root))
        f = facts(p) if p.suffix.lower() == ".pdf" else {
            "pages": "", "words": "", "words_per_page": "", "tagged": "",
            "images": "", "scanned": ""}
        row = {"path": rel, **f, "suggested": suggest(p, f) if f["pages"] != "" else "guide",
               "decision": old.get(rel, {}).get("decision", ""),
               "notes": old.get(rel, {}).get("notes", "")}
        if p.suffix.lower() != ".pdf":
            row["notes"] = row["notes"] or "Office file: open it, or export to PDF first"
        rows.append(row)
        print(f"{row['suggested']:<7} {str(f['pages']):>4}p {str(f['words_per_page']):>5} w/p "
              f"{'SCAN ' if f['scanned'] == 'yes' else '     '}{rel}")
    for rel, r in old.items():  # keep rows for files not re-scanned this run
        if rel not in {x["path"] for x in rows}:
            rows.append(r)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["path"]))
    undecided = sum(1 for r in rows if not r.get("decision"))
    print(f"\nWrote {out.name}: {len(rows)} documents, {undecided} without a decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
