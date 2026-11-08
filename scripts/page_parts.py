"""Split a long page into several Canvas pages, with a contents box on each.

YuJa Panorama marks any page over 3,000 words (ContentLengthIssue), and a
long manual is hard to use on one page anyway. `canvas.py push page` calls
`split()` on every page it pushes. A page within WORD_BUDGET comes back
whole; a longer one is cut at its chapters (top-level sections), and a
chapter that is itself too long is cut at its subsections, then between
paragraphs.

The source stays one .qmd. By default part 1 keeps the page's title (so
links to it keep working) and the others are "<title> (Part k of n)". With
`named` (vendor manuals), the parts are all "<title> (Part k of n): <where it
starts>", the chapter or, partway through one, its first subheading. Each part opens with a contents box (every part, named by its
chapters, and this part's chapters as in-page links) and ends with
Previous / Next links. A link to an anchor that landed in another part is
pointed at that part's page, and footnotes go with the part that cites
them. The plan depends only on the page's text, so `modules.py` gets
the same part titles from `titles()` without pushing anything.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import math
import re
from dataclasses import dataclass, field

# Panorama counts more words than the visible text holds (it flagged pages
# of 2,976 and 2,998 visible words), and the contents box adds some.
WORD_BUDGET = 2400
# Panorama's count matches tokens(): "CONF:VOLT:DC" is three words, "1.5"
# one. Keithley Part 19 (2,456 words, 3,020 tokens) failed and EDU-QCRY1
# Part 4 (2,185 words, 2,997 tokens) passed, Nov 8 2026. If a finished part
# page (contents box, "(continued)" headings and footnotes included) is over
# TOKEN_LIMIT, the split is redone with a smaller budget.
try:
    import config as _config
    _cfg = _config.settings_or_defaults()
except SystemExit:  # imported by a Python too old for course.toml
    _cfg = None
TOKEN_LIMIT = _cfg.word_limit if _cfg else 2900
# Longest "<chapter>, <subheading>" in a manual part's title.
NAME_LIMIT = 90
_TOKEN = re.compile(r"\w+(?:['’.]\w+)*")


def words(el) -> int:
    if isinstance(el, str):
        return len(el.split())
    return len(el.get_text(" ", strip=True).split())


def tokens(el) -> int:
    text = el if isinstance(el, str) else el.get_text(" ", strip=True)
    return len(_TOKEN.findall(text))


def _heading(el):
    return el.find(re.compile(r"^h[1-6]$"), recursive=False) if hasattr(el, "find") else None


def _is_section(el) -> bool:
    return getattr(el, "name", None) == "section"


@dataclass
class Piece:
    nodes: list
    chapter: str | None       # id of the top-level section this came from
    chapter_title: str | None
    first: bool               # the start of its chapter
    words: int
    # Headings of the sections this piece sits inside, outermost first, as
    # (tag, text). A part that starts mid-section repeats them, marked
    # "(continued)", so its headings do not skip levels.
    context: list = field(default_factory=list)


@dataclass
class Part:
    title: str
    pieces: list = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(p.words for p in self.pieces)

    def chapters(self) -> list[tuple[str, str]]:
        seen, out = set(), []
        for p in self.pieces:
            if p.chapter and p.chapter not in seen:
                seen.add(p.chapter)
                out.append((p.chapter, p.chapter_title))
        return out


def _pieces(el, chapter, chapter_title, first, budget, context=()) -> list[Piece]:
    """`el` as one piece, or cut into several if it is over budget."""
    n = words(el)
    context = list(context)
    if n <= budget or not _is_section(el):
        return [Piece([el], chapter, chapter_title, first, n, context)]  # a table, figure... stays whole
    h = _heading(el)
    inner = context + ([(h.name, " ".join(h.get_text(" ", strip=True).split()))] if h else [])
    kids = [k for k in el.children if getattr(k, "name", None) or str(k).strip()]
    out: list[Piece] = []
    # A section's heading and the text before its first subsection stay
    # together, in a copy of the section so its id (the anchor) survives.
    if _is_section(el):
        shell = copy.copy(el)
        shell.clear()
        lead = []
        while kids and not _is_section(kids[0]):
            lead.append(kids.pop(0))
        for k in lead:
            shell.append(k.extract())
        if words(shell) > budget:
            # A long section with no subsections: cut between paragraphs.
            return _by_paragraph(shell, chapter, chapter_title, first, budget, context, inner) + [
                q for k in kids for q in _pieces(k.extract(), chapter, chapter_title, False, budget, inner)]
        out.append(Piece([shell], chapter, chapter_title, first, words(shell), context))
        first = False
    for k in kids:
        out += _pieces(k.extract(), chapter, chapter_title, first and not out, budget, inner)
    return out


def _by_paragraph(section, chapter, chapter_title, first, budget, context, inner) -> list[Piece]:
    kids = [k.extract() for k in list(section.children)]
    shell = copy.copy(section)
    shell.clear()
    out, cur, n = [], [], 0
    for k in kids:
        w = words(k) if (getattr(k, "name", None) or str(k).strip()) else 0
        if cur and n + w > budget:
            out.append((cur, n))
            cur, n = [], 0
        cur.append(k)
        n += w
    if cur:
        out.append((cur, n))
    pieces = []
    for i, (nodes, n) in enumerate(out):
        if i == 0:
            for k in nodes:
                shell.append(k)
            pieces.append(Piece([shell], chapter, chapter_title, first, n, context))
        else:
            pieces.append(Piece(nodes, chapter, chapter_title, False, n, inner))
    return pieces


def _heading_text(h) -> str:
    """A heading's words, without footnote markers, and with no space added
    around inline tags ("T<sub>2</sub>" is "T2", not "T 2")."""
    h = copy.copy(h)
    for ref in h.select("a.footnote-ref"):
        ref.decompose()
    return " ".join(h.get_text().split())


def _chapter_title(section) -> str:
    h = _heading(section)
    return _heading_text(h) if h else ""


def _first_heading(part: Part):
    """The part's first subsection heading: the first h3, or if it has none
    the first h4, and so on (a SCPI command heading or a "5.1.2." names a
    part worse than its section does). None if it has no subheadings."""
    for level in range(3, 7):
        tag = f"h{level}"
        for p in part.pieces:
            for n in p.nodes:
                if getattr(n, "name", None) == tag:
                    return n
                h = n.find(tag) if hasattr(n, "find") else None
                if h is not None:
                    return h
    return None


def _name(part: Part) -> str:
    """Where a part starts, for its page title: the chapter it opens with,
    or, when it starts partway through one, the chapter and its first
    subheading."""
    first = part.pieces[0]
    chapters = part.chapters()
    if first.chapter is None:
        return chapters[0][1] if chapters else "Introduction"
    if first.first:
        return first.chapter_title
    h = _first_heading(part)
    if h is None:
        return f"{first.chapter_title} (continued)"
    sub = _heading_text(h)
    # A long chapter title and subheading together make a title too long
    # to read in a module list; the subheading alone still places the part.
    both = f"{first.chapter_title}, {sub}"
    return both if len(both) <= NAME_LIMIT else sub


def plan(main, title: str, budget: int = WORD_BUDGET,
         named: bool = False) -> tuple[list[Part], object]:
    """Parts for the body `main` (a parsed tag; consumed). Returns the parts
    and the footnotes list (an <ol>, or None). With `named` (the vendor
    manuals), every part's title says its number and where it starts,
    part 1 included: "<title> (Part 3 of 9): <chapter>"."""
    parts, footnotes = _plan(main, title, budget)
    if named and len(parts) > 1:
        for i, part in enumerate(parts):
            part.title = f"{title} (Part {i + 1} of {len(parts)}): {_name(part)}"
    return parts, footnotes


def _plan(main, title: str, budget: int) -> tuple[list[Part], object]:
    footnotes = None
    for app in main.select("#quarto-appendix, section.footnotes"):
        ol = app.find("ol")
        if ol is not None and app.select_one("li[id^=fn]"):
            footnotes = ol.extract()
        app.decompose()
    total = words(main)
    if total <= budget:
        return [Part(title, [Piece(list(main.children), None, None, True, total)])], footnotes
    pieces: list[Piece] = []
    for el in [k.extract() for k in list(main.children)]:
        if not (getattr(el, "name", None) or str(el).strip()):
            continue
        if _is_section(el):
            pieces += _pieces(el, el.get("id"), _chapter_title(el), True, budget)
        else:
            pieces.append(Piece([el], None, None, True, words(el)))
    n = math.ceil(total / budget)
    target = total / n
    groups: list[list[Piece]] = [[]]
    cur = 0
    for p in pieces:
        if groups[-1] and (cur + p.words > budget or cur >= target):
            groups.append([])
            cur = 0
        groups[-1].append(p)
        cur += p.words
    k = len(groups)
    parts = [Part(title if i == 0 else f"{title} (Part {i + 1} of {k})", g)
             for i, g in enumerate(groups)]
    return parts, footnotes


def titles(body_html: str, title: str, named: bool = False) -> list[str]:
    # The links between parts are text-free, so any address will do.
    return [t for t, _ in split(body_html, title, lambda t: "", named)]


def _label(part: Part) -> str:
    ch = [t for _, t in part.chapters()]
    if not ch:
        return "Introduction"
    return ch[0] if len(ch) == 1 else f"{ch[0]} to {ch[-1]}"


def split(body_html: str, title: str, page_url, named: bool = False) -> list[tuple[str, str]]:
    """[(title, body)] for each part. `page_url(title)` gives the address a
    part's page has (or will have) on Canvas, for the links between parts."""
    from bs4 import BeautifulSoup

    budget = WORD_BUDGET
    while True:
        parts, footnotes = plan(BeautifulSoup(body_html, "html.parser"), title,
                                budget, named)
        if len(parts) == 1:
            return [(title, body_html)]
        out = _assemble(parts, footnotes, page_url)
        if budget <= 1000 or all(tokens(BeautifulSoup(b, "html.parser")) <= TOKEN_LIMIT
                                 for _, b in out):
            return out
        budget -= 100


def _assemble(parts, footnotes, page_url) -> list[tuple[str, str]]:
    from bs4 import BeautifulSoup

    # Which part holds each anchor, for links that now cross pages.
    home: dict[str, int] = {}
    for i, part in enumerate(parts):
        for piece in part.pieces:
            for node in piece.nodes:
                if getattr(node, "get", None) and node.get("id"):
                    home[node["id"]] = i
                if hasattr(node, "find_all"):
                    for el in node.find_all(id=True):
                        home.setdefault(el["id"], i)
    notes = {li["id"]: li for li in footnotes.find_all("li", id=True)} if footnotes else {}

    out = []
    for i, part in enumerate(parts):
        doc = BeautifulSoup("", "html.parser")
        doc.append(_contents(doc, parts, i, page_url))
        for piece in part.pieces:
            if piece is part.pieces[0] and not piece.first:
                for name, text in piece.context:
                    h = doc.new_tag(name)
                    h.string = f"{text} (continued)"
                    doc.append(h)
            for node in piece.nodes:
                doc.append(node)
        # Footnotes cited in this part, keeping their numbers.
        cited = [a["href"][1:] for a in doc.find_all("a", href=True)
                 if a["href"].startswith("#fn") and not a["href"].startswith("#fnref")]
        if cited and notes:
            sec = doc.new_tag("section", attrs={"role": "doc-endnotes"})
            h = doc.new_tag("h2")
            h.string = "Footnotes"
            sec.append(h)
            ol = doc.new_tag("ol")
            for fid in dict.fromkeys(cited):
                if fid in notes:
                    li = copy.copy(notes[fid])
                    m = re.search(r"\d+", fid)
                    if m:
                        li["value"] = m.group(0)
                    ol.append(li)
            sec.append(ol)
            doc.append(sec)
        # Point in-page links whose target moved to another part at that page.
        for a in doc.find_all("a", href=True):
            href = a["href"]
            if href.startswith("#") and len(href) > 1:
                j = home.get(href[1:])
                if j is not None and j != i:
                    a["href"] = page_url(parts[j].title) + href
        doc.append(_prev_next(doc, parts, i, page_url))
        out.append((part.title, doc.decode()))
    return out


BOX = ("border: 1px solid #d4d7da; border-left: 4px solid #003057; "
       "border-radius: 6px; padding: 12px 18px; margin: 0 0 24px")


def _contents(doc, parts, i, page_url):
    """The box at the top of each part: every part, by its chapters, with
    this part's chapters as links within the page."""
    box = doc.new_tag("div", attrs={"role": "navigation",
                                    "aria-label": "Parts of this document",
                                    "style": BOX})
    p = doc.new_tag("p", attrs={"style": "margin: 0 0 6px"})
    b = doc.new_tag("strong")
    b.string = f"This document is in {len(parts)} parts. This is part {i + 1}."
    p.append(b)
    box.append(p)
    ol = doc.new_tag("ol", attrs={"style": "margin: 0; padding-left: 1.4em; line-height: 1.7"})
    for j, part in enumerate(parts):
        li = doc.new_tag("li")
        if j == i:
            # Canvas strips aria-current, so the words say it.
            s = doc.new_tag("strong")
            s.string = _label(part) + " (this page)"
            li.append(s)
            chapters = part.chapters()
            if len(chapters) > 1:
                ul = doc.new_tag("ul", attrs={"style": "margin: 0"})
                for cid, ctitle in chapters:
                    cli = doc.new_tag("li")
                    a = doc.new_tag("a", href=f"#{cid}")
                    a.string = ctitle
                    cli.append(a)
                    ul.append(cli)
                li.append(ul)
        else:
            a = doc.new_tag("a", href=page_url(part.title))
            a.string = _label(part)
            li.append(a)
        ol.append(li)
    box.append(ol)
    return box


def _prev_next(doc, parts, i, page_url):
    nav = doc.new_tag("div", attrs={
        "role": "navigation", "aria-label": "Previous and next part",
        "style": ("display: flex; flex-wrap: wrap; justify-content: space-between; "
                  "gap: 12px; border-top: 1px solid #d4d7da; margin-top: 32px; "
                  "padding-top: 12px")})
    for j, word in ((i - 1, "Previous"), (i + 1, "Next")):
        span = doc.new_tag("span")
        if 0 <= j < len(parts):
            a = doc.new_tag("a", href=page_url(parts[j].title))
            a.string = f"{word}: part {j + 1}, {_label(parts[j])}"
            span.append(a)
        nav.append(span)
    return nav
