#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""Our accessibility checklist: catch YuJa Panorama issues before a push.

    ./scripts/a11y_check.py guides/*/*.html           # rendered pages
    ./scripts/a11y_check.py --canvas                  # every page on Canvas
    ./scripts/a11y_check.py --canvas "Lab 1"
    ./scripts/a11y_check.py --links ...               # also test external links
    ./scripts/a11y_check.py --compare <list dir> <issues.json>   # vs Panorama

Each rule is one Panorama issue type, added when we first had to fix that
issue after a scan (see the case log in docs/panorama-issues.md). The rule
names the issue, so a Panorama report and this checklist can be read side
by side. When a scan finds something this misses, add a rule here before
fixing the page.

`canvas.py push page` runs these rules on every page it pushes and prints
what fails. Exit status is 1 if any page has a severe or major finding.
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

_cfg = config.settings_or_defaults()

# Calibrated against Panorama's scan of 70 pages (Nov 2026); see
# docs/panorama-issues.md. Where we are stricter than Panorama, it says so.
# The limits can be changed in course.toml [panorama] and [checks].
ALT_LIMIT = _cfg.alt_limit if _cfg else 120
                     # Panorama's help text says 120. One school's setting
                     # was 240 and a 244-character alt passed; keep 120.
# ContentLengthIssue is "over 3000 words", counted as page_parts.tokens()
# counts them ("CONF:VOLT:DC" is three), not by whitespace: a page of 2,456
# words and 3,020 tokens failed (Nov 8 2026). We warn a little early.
WORD_LIMIT = _cfg.word_limit if _cfg else 2900
# Sites that answer Panorama's link checker with a 404 although the page is
# there for a browser (and for check_links), so the link always fails the
# scan. Name the page in plain text instead of linking it.
SCANNER_BLOCKED = tuple(_cfg.scanner_blocked) if _cfg else ("knowledge.ni.com",)
# Links on these hosts are not tested (the course's own Canvas, the library
# proxy): they need a login, so a test would always fail.
OWN_HOSTS = tuple(_cfg.own_hosts) if _cfg else ()
# Rendered below 10 pt with the browser's default styles, which is what
# Panorama measures (fontSizeMinimum 10 by default); Canvas's stylesheet is not
# applied. Seen in scans: code, pre, h5, h6. Plain <sub>/<sup> passed.
SMALL_TAGS = ("code", "pre", "kbd", "samp", "h5", "h6", "small")


@dataclass(frozen=True)
class Finding:
    issue: str        # Panorama's issueTypeIdentifier, without ":HTML"
    severity: str     # Panorama's severity
    message: str

    def __str__(self) -> str:
        return f"{self.issue} [{self.severity}]: {self.message}"


def text_of(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def check_body(html: str, links: bool = False) -> list[Finding]:
    """Findings for one page body (the HTML sent to, or stored by, Canvas)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    out: list[Finding] = []

    # LongAlternativeTextIssue (Franck-Hertz guide, Nov 2026): the whole
    # figure description was in alt. Short alt; long text visible.
    for img in main.find_all("img"):
        alt = img.get("alt")
        # ODU has Panorama's "Treat Empty Alt Tags as Decorative Images"
        # turned off, so alt="" fails like a missing alt (home page card
        # icons, Reprocess scan Nov 7), and an empty-alt image inside a link
        # fails a second time as DecorativeImageAsLink.
        if alt is None or not alt.strip():
            out.append(Finding("MissingAlternativeTextIssue", "severe",
                               f"image without alt text: {img.get('src', '')[-50:]}"))
            if img.find_parent("a"):
                out.append(Finding("DecorativeImageAsLinkIssue", "severe",
                                   f"image with empty alt inside a link: {img.get('src', '')[-50:]}"))
        elif len(alt) > ALT_LIMIT:
            out.append(Finding("LongAlternativeTextIssue", "severe",
                               f"alt is {len(alt)} characters (limit {ALT_LIMIT}): {alt[:50]}..."))

    # EmptyHyperlinkIssue: Pandoc's per-line anchors in code blocks count,
    # even though they are aria-hidden.
    # canvas.py's _fix_text_a11y strips the #cb anchors at push.
    empty = [a for a in main.find_all("a", href=True)
             if not text_of(a) and not a.get("aria-label") and not a.find("img", alt=True)]
    if empty:
        code = sum(1 for a in empty if a["href"].startswith("#cb"))
        out.append(Finding("EmptyHyperlinkIssue", "severe",
                           f"{len(empty)} link(s) with no text"
                           + (f", {code} of them code-line anchors" if code else "")))

    # HyperlinkContextIssue: link text that is a URL or a bare domain.
    # Stricter than Panorama, which passed "www.graulab.org" but failed
    # "thorlabs.com"; an address is poor link text either way.
    for a in main.find_all("a", href=True):
        t = text_of(a)
        if t and re.fullmatch(r"(https?://)?(www\.)?[\w-]+(\.[\w-]+)+(/\S*)?", t, re.I):
            out.append(Finding("HyperlinkContextIssue", "severe",
                               f"link text is an address: {t[:60]}"))

    # MissingTableContentIssue: a table whose data cells are all empty (a
    # blank data table for students to fill in), or that has a header row
    # and no data rows at all (Nov 9 2026: 19 vendor-manual pages scored 29
    # for a header-only "Observations" table). A few empty cells pass.
    for table in main.find_all("table"):
        if not table.find("th"):
            out.append(Finding("MissingTableHeadersIssue", "severe",
                               f"table without header cells: {text_of(table)[:50]}"))
        elif not table.find("caption"):
            # canvas.py push page adds one; the syllabus push did not.
            out.append(Finding("MissingTableCaptionIssue", "severe",
                               f"table without caption: {text_of(table)[:50]}"))
        cells = table.find_all("td")
        blank = [td for td in cells if not text_of(td) and not td.find("img")]
        if len(blank) == len(cells):
            cap = table.find("caption")
            out.append(Finding("MissingTableContentIssue", "severe",
                               f"every data cell is empty in table "
                               f"{text_of(cap)[:40] if cap else text_of(table)[:40]!r}"))

    # SkippedHeadingIssue: a heading more than one level below the one
    # before it. Canvas shows the title as h1, so the body starts at h2
    # (discussions that began at h3, Reprocess scan Nov 7).
    last = 1
    for h in main.find_all(re.compile(r"^h[1-6]$")):
        level = int(h.name[1])
        if level > last + 1:
            out.append(Finding("SkippedHeadingIssue", "severe",
                               f"<{h.name}> after <h{last}>: {text_of(h)[:50]}"))
        last = level

    # SmallFontSizeIssue: elements the browser shrinks by default. A
    # monospace element is fixed only by `font-family: monospace, monospace`
    # (an explicit 1em still renders at 13 px); others by an explicit size.
    # canvas.py's _fix_text_a11y applies both at push.
    small: dict[str, int] = {}
    for tag in SMALL_TAGS:
        for el in main.find_all(tag):
            style = el.get("style") or ""
            if tag in ("code", "pre", "kbd", "samp"):
                if "monospace, monospace" in style:
                    continue
            elif "font-size" in style:
                continue
            small[tag] = small.get(tag, 0) + 1
    for el in main.find_all(style=re.compile(r"font-size")):
        m = re.search(r"font-size:\s*([\d.]+)(px|pt|em|rem|%)", el["style"])
        if m:
            v, unit = float(m.group(1)), m.group(2)
            pt = {"px": v * 0.75, "pt": v, "em": v * 12, "rem": v * 12, "%": v * 0.12}[unit]
            if pt < 10:
                small[f"font-size {m.group(0)[10:].strip()}"] = small.get(f"font-size {m.group(0)[10:].strip()}", 0) + 1
    if small:
        out.append(Finding("SmallFontSizeIssue", "major",
                           "text under 10 pt by default: "
                           + ", ".join(f"{n} <{t}>" if not t.startswith("font") else f"{n} x {t}"
                                       for t, n in small.items())))

    # ContentLengthIssue: more than 3000 words on one page.
    from page_parts import tokens

    words = tokens(main)
    if words > WORD_LIMIT:
        out.append(Finding("ContentLengthIssue", "minor",
                           f"about {words} words as Panorama counts them (its limit is "
                           f"3000); split the page"))

    # BrokenHyperlinkIssue that no link test reproduces (see SCANNER_BLOCKED).
    for a in main.find_all("a", href=True):
        if any(f"//{host}" in a["href"] for host in SCANNER_BLOCKED):
            out.append(Finding("BrokenHyperlinkIssue", "severe",
                               f"Panorama's scanner gets a 404 from this site: "
                               f"{text_of(a)[:40]!r} -> {a['href'][:70]}"))

    if links:
        out += check_links(main)
    return out


def check_links(main) -> list[Finding]:
    """BrokenHyperlinkIssue: external links that do not resolve. Slow, so
    opt-in. A 403 is often a site refusing scripts, not a dead page, so only
    404/410 and connection failures count."""
    import requests

    out = []
    seen = set()
    for a in main.find_all("a", href=True):
        url = a["href"]
        # Our own Canvas pages need a login, and the library proxy a MIDAS
        # one; neither can be tested from a script.
        if (not url.startswith("http") or url in seen
                or any(h in url for h in OWN_HOSTS)):
            continue
        seen.add(url)
        try:
            r = requests.get(url, timeout=20, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (accessibility link check)"})
            if r.status_code in (404, 410):
                out.append(Finding("BrokenHyperlinkIssue", "severe",
                                   f"{r.status_code}: {text_of(a)[:40]!r} -> {url[:70]}"))
        except requests.RequestException as e:
            out.append(Finding("BrokenHyperlinkIssue", "severe",
                               f"{type(e).__name__}: {text_of(a)[:40]!r} -> {url[:70]}"))
    return out


def compare(list_dir: Path, issues_json: Path) -> int:
    """Validate the checklist against a Panorama scan: run it on every web
    page Panorama scored (`yuja.sh list` dump) and compare issue types with
    Panorama's (`yuja.sh issues` output). Broken links are left out (they
    need --links), and so are rules Panorama has no counterpart for."""
    import json

    from canvas_api import Canvas

    docs = {}
    for f in sorted(list_dir.glob("json-*.json")):
        d = json.loads(f.read_text())
        if "getPaginatedCourseDocuments" in d["url"]:
            for x in json.loads(d["body"]).get("documents", []):
                docs[x["displayName"]] = x
    theirs = {p["displayName"]: {i["issueTypeIdentifier"].split(":")[0] for i in p["issues"]}
              for p in json.loads(issues_json.read_text())}
    c = Canvas.from_env()
    pages = {p["title"]: p for p in c.paginate(f"courses/{c.course_id}/pages")}
    skip = {"BrokenHyperlinkIssue"}
    agree = n = 0
    for name, d in sorted(docs.items()):
        if d["format"] == "pdf" or name not in pages:
            continue
        page = c.get(f"courses/{c.course_id}/pages/{pages[name]['url']}")
        if page["updated_at"] > d["inserted"]:
            continue  # changed since Panorama scanned it
        n += 1
        want = (theirs.get(name, set()) if d["score"] < 100 else set()) - skip
        got = {f.issue for f in check_body(page.get("body") or "")} - skip
        if got == want:
            agree += 1
        else:
            print(f"{d['score']:>4} {name}: Panorama only {sorted(want - got)}, "
                  f"checklist only {sorted(got - want)}")
    print(f"\nsame issue types on {agree} of {n} pages")
    return 0


def failing(findings: list[Finding]) -> bool:
    return any(f.severity in ("severe", "major") for f in findings)


def report(name: str, findings: list[Finding]) -> None:
    mark = "FAIL" if failing(findings) else ("ok* " if findings else "ok  ")
    print(f"{mark} {name}")
    for f in findings:
        print(f"       {f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", type=Path, help="rendered .html pages")
    ap.add_argument("--canvas", nargs="*", metavar="TITLE",
                    help="check pages as stored on Canvas (all, or these titles)")
    ap.add_argument("--links", action="store_true", help="also request every external link")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("LIST_DIR", "ISSUES_JSON"),
                    help="validate the rules against a Panorama scan")
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)

    bad = 0
    for f in args.files:
        # Check what a push would send, not the raw Quarto page: the push
        # adds table captions and scope, fixes code fonts and removes
        # comments, and splits a long page into parts.
        from canvas import prepare_html
        import page_parts

        body = prepare_html(f, None, None, True, upload_assets=False)
        parts = page_parts.split(body, f.stem, lambda t: "#", "manuals" in f.parts)
        if len(parts) > 1:
            print(f"     ({f}: would be pushed as {len(parts)} parts)")
        found = [x for _, b in parts for x in check_body(b, args.links)]
        report(str(f), list(dict.fromkeys(found)))
        bad += failing(found)
    if args.canvas is not None:
        from canvas_api import Canvas

        c = Canvas.from_env()
        pages = list(c.paginate(f"courses/{c.course_id}/pages", per_page=100))
        if args.canvas:
            pages = [p for p in pages if p["title"] in args.canvas]
        for p in sorted(pages, key=lambda p: p["title"]):
            body = c.get(f"courses/{c.course_id}/pages/{p['url']}").get("body") or ""
            found = check_body(body, args.links)
            report(p["title"], found)
            bad += failing(found)
    print(f"\n{bad} page(s) fail")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
