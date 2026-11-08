"""Three-way merge of a Canvas edit into a hand-authored canvas/*.html file.

This is what lets `canvas_sync.py pull` behave like `git pull`: a change made
in the Canvas UI is folded into the source, alongside whatever was edited
locally since the last push, and the two only collide where they touched the
same words.

    base     the body as it stood in Canvas right after our last push
    ours     the source file now, comments, wrapping and all
    theirs   the body live in Canvas now

WHY NOT LINES

`git merge-file` works on lines, and lines mean nothing here. Canvas strips the
indentation from every tag it hands back, and saving in its rich-text editor
re-serialises the whole body, so every line of a page reads as changed after a
one-word edit. The merge instead works on tokens: each tag, and each word of
text, compared in a canonical form that ignores what Canvas does on its own
(whitespace, entity spelling, attribute order, the course id, rotating file
verifiers, the attributes it annotates links and images with).

The output is the source file with Canvas's changes spliced in. Everything
Canvas did not change keeps the source's own text, so the explanatory comments
and the line wrapping survive. Where both sides changed the same stretch, the
file gets git-style conflict markers, and the push commands refuse to send a
file that still has them.
"""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser

TOKEN = re.compile(r"<!--.*?-->|<[^>]*>|[^<]+", re.S)
# Word separators inside text. A non-breaking space is a separator too, since
# Canvas's editor freely trades a space for &nbsp; and back.
SPACE = re.compile(r"(?:\s|&nbsp;|&#160;|\xa0)+")

# Attributes Canvas adds by itself. They are not ours, so they never count as
# an edit, and they are stripped before Canvas text is written into a source.
CANVAS_ATTRS = ("data-api-endpoint", "data-api-returntype", "loading",
                "data-decorative")

MARK_OURS = "<<<<<<< repo"
MARK_SEP = "======="
MARK_THEIRS = ">>>>>>> Canvas"
CONFLICT = re.compile(r"^(<<<<<<< |=======\s*$|>>>>>>> )", re.M)


def has_conflicts(text: str) -> bool:
    return bool(CONFLICT.search(text))


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag = None
        self.attrs = []
        self.end = False

    def handle_starttag(self, tag, attrs):
        self.tag, self.attrs = tag, attrs

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        self.tag, self.end = tag, True


class Context:
    """What it takes to put a Canvas body and a source file in the same terms."""

    def __init__(self, course_id: str | int, file_names: dict[str, str] | None = None,
                 placeholder: bool = True):
        self.course_id = str(course_id)
        # Canvas file id -> the file's name, so an <img> rehosted on upload
        # compares equal to the assets/ path it was uploaded from.
        self.file_names = file_names or {}
        # Hand-authored sources write internal links as /courses/COURSE_ID/.
        self.placeholder = placeholder

    def url(self, value: str) -> str:
        value = re.sub(r"https?://[^/\"'\s]+/courses/", "/courses/", value)
        value = re.sub(r"(\?|&amp;|&)verifier=[^\"&\s]*", "", value).rstrip("?")
        value = value.replace(f"/courses/{self.course_id}/", "/courses/COURSE_ID/")
        m = re.search(r"/files/(\d+)", value)
        if m and m.group(1) in self.file_names:
            return "file:" + self.file_names[m.group(1)]
        if value and not re.match(r"[a-z]+:|/|#", value):
            return "file:" + value.rsplit("/", 1)[-1]  # a local asset path
        return value


def _style(value: str) -> str:
    rules = []
    for rule in value.split(";"):
        if ":" in rule:
            prop, val = rule.split(":", 1)
            rules.append(f"{prop.strip().lower()}:{' '.join(val.split())}")
    return ";".join(rules)


def _tag_key(raw: str, ctx: Context) -> str:
    p = _Attrs()
    p.feed(raw)
    p.close()
    if p.tag is None:
        return " ".join(raw.split())
    if p.end:
        return f"</{p.tag}>"
    attrs = []
    for name, value in p.attrs:
        if name in CANVAS_ATTRS:
            continue
        if p.tag == "img" and name in ("width", "height"):
            continue
        value = " ".join((value or "").split())
        if name == "style":
            value = _style(value)
        elif name in ("href", "src"):
            value = ctx.url(value)
        attrs.append((name, value))
    return f"<{p.tag} " + " ".join(f"{n}={v!r}" for n, v in sorted(attrs)) + ">"


class Tokens:
    """A body split into tags and words, each with its place in the raw text."""

    def __init__(self, text: str, ctx: Context):
        self.text = text
        self.keys: list[str] = []
        self.starts: list[int] = []
        self.ends: list[int] = []
        for m in TOKEN.finditer(text):
            raw = m.group(0)
            if raw.startswith("<!--"):
                continue
            if raw.startswith("<"):
                self._add(_tag_key(raw, ctx), m.start(), m.end())
                continue
            pos = 0
            for word in SPACE.split(raw):
                if not word:
                    continue
                at = raw.index(word, pos)
                pos = at + len(word)
                self._add(html.unescape(word), m.start() + at, m.start() + pos)

    def _add(self, key: str, start: int, end: int) -> None:
        self.keys.append(key)
        self.starts.append(start)
        self.ends.append(end)

    def __len__(self):
        return len(self.keys)

    def raw(self, i: int, j: int) -> str:
        """Tokens i..j-1, with the whitespace and comments between them."""
        if i >= j:
            return ""
        return self.text[self.starts[i]:self.ends[j - 1]]


def _sync_regions(base, a, b):
    """Stretches where all three agree (after bzrlib's merge3)."""
    am = SequenceMatcher(None, base, a, autojunk=False).get_matching_blocks()
    bm = SequenceMatcher(None, base, b, autojunk=False).get_matching_blocks()
    ia = ib = 0
    out = []
    while ia < len(am) and ib < len(bm):
        abase, amatch, alen = am[ia]
        bbase, bmatch, blen = bm[ib]
        lo, hi = max(abase, bbase), min(abase + alen, bbase + blen)
        if lo < hi:
            asub = amatch + (lo - abase)
            bsub = bmatch + (lo - bbase)
            out.append((lo, hi, asub, asub + hi - lo, bsub, bsub + hi - lo))
        if abase + alen < bbase + blen:
            ia += 1
        else:
            ib += 1
    out.append((len(base), len(base), len(a), len(a), len(b), len(b)))
    return out


def _regions(base, a, b):
    iz = ia = ib = 0
    for zmatch, zend, amatch, aend, bmatch, bend in _sync_regions(base, a, b):
        if amatch > ia or bmatch > ib or zmatch > iz:
            sa, sb, sz = a[ia:amatch], b[ib:bmatch], base[iz:zmatch]
            if sa == sb:
                yield ("ours", ia, amatch, ib, bmatch)
            elif sa == sz:
                yield ("theirs", ia, amatch, ib, bmatch)
            elif sb == sz:
                yield ("ours", ia, amatch, ib, bmatch)
            else:
                yield ("conflict", ia, amatch, ib, bmatch)
        if zend > zmatch:
            yield ("ours", amatch, aend, bmatch, bend)
        iz, ia, ib = zend, aend, bend


def clean_live(body: str, ctx: Context) -> str:
    """A live Canvas body, rewritten into the terms a source file uses.

    Formatting is left exactly as Canvas has it; only Canvas's own additions
    and its spelling of internal URLs are undone.
    """
    body = re.sub(r"<link[^>]*(?:instructure-uploads|amazonaws)[^>]*>\s*", "", body)
    body = re.sub(r"<script[^>]*(?:instructure-uploads|amazonaws)[^>]*>\s*</script>\s*",
                  "", body)
    body = re.sub(r"\s(?:%s)=\"[^\"]*\"" % "|".join(CANVAS_ATTRS), "", body)
    body = re.sub(r"https?://[^/\"'\s]+(/courses/)", r"\1", body)
    body = re.sub(r"(\?|&amp;|&)verifier=[^\"&\s]*", "", body)
    body = body.replace('?"', '"')
    if ctx.placeholder:
        body = body.replace(f"/courses/{ctx.course_id}/", "/courses/COURSE_ID/")

    def local(m):
        fid = re.search(r"/files/(\d+)", m.group(2))
        name = ctx.file_names.get(fid.group(1)) if fid else None
        return f"{m.group(1)}assets/{name}\"" if name else m.group(0)

    return re.sub(r"(<img[^>]*\ssrc=\")([^\"]*)\"", local, body)


def _same_kind(ours: str, theirs: str) -> str:
    """The source's own spacing, unless Canvas has none where it has some.

    Between tokens, HTML only cares whether there is space at all, not how
    much. So any run of whitespace in the source stands in for any run Canvas
    has, which keeps the source's line breaks and indentation; only a gap that
    one side has and the other lacks ("<em>more" against "<em> more") follows
    Canvas.
    """
    if ours and bool(ours.strip(" \t\r\n")) == bool(theirs.strip(" \t\r\n")) and \
            bool(ours) == bool(theirs):
        return ours
    return theirs


class Result:
    def __init__(self, text: str, conflicts: int, changes: int):
        self.text = text
        self.conflicts = conflicts
        self.changes = changes  # stretches taken from Canvas without conflict


def merge(base_live: str, ours: str, theirs_live: str, ctx: Context,
          label: str = "repo") -> Result:
    """Fold the Canvas edit (base_live -> theirs_live) into `ours`."""
    o = Tokens(clean_live(base_live, ctx), ctx)
    a = Tokens(ours, ctx)
    b = Tokens(clean_live(theirs_live, ctx), ctx)

    out = []
    conflicts = changes = 0
    cursor = 0  # how far into `ours` has been copied

    def gap_a(k: int) -> tuple[int, int]:
        """The stretch of `ours` between token k-1 and token k."""
        lo = a.ends[k - 1] if k else 0
        hi = a.starts[k] if k < len(a) else len(a.text)
        return lo, hi

    def gap_b(k: int) -> str:
        if not 0 < k < len(b):
            return ""
        return b.text[b.ends[k - 1]:b.starts[k]]

    for kind, ia, aend, ib, bend in _regions(o.keys, a.keys, b.keys):
        if kind == "ours":
            continue  # copied from `ours` lazily, by the next splice or the tail
        if kind == "conflict":
            start, end = (a.starts[ia], a.ends[aend - 1]) if aend > ia else gap_a(ia)[1:] * 2
            out.append(a.text[cursor:start])
            out.append(
                f"\n{MARK_OURS} ({label})\n{a.text[start:end]}\n{MARK_SEP}\n"
                f"{b.raw(ib, bend)}\n{MARK_THEIRS} (live)\n"
            )
            conflicts += 1
            cursor = end
            continue

        # Take Canvas's tokens, and with them the spacing on either side, so
        # "lost <em>more" does not come out as "lost <em> more". The source's
        # own spacing is kept wherever it is the same kind (both a line break,
        # or both a space), so indentation survives. The edges are never
        # widened past a comment, or past the start or end of the file.
        lo, _ = gap_a(ia)
        _, hi = gap_a(aend)
        before_a = a.text[lo:a.starts[ia]] if aend > ia else a.text[lo:hi]
        after_a = a.text[a.ends[aend - 1]:hi] if aend > ia else before_a
        if "<!--" in before_a or ia == 0:
            lo, before_a = (a.starts[ia] if aend > ia else hi), ""
        if "<!--" in after_a or aend >= len(a):
            hi, after_a = (a.ends[aend - 1] if aend > ia else lo), ""
        if lo > hi:  # an insertion that can touch neither side
            lo = hi
        if bend > ib:
            new = (_same_kind(before_a, gap_b(ib)) + b.raw(ib, bend)
                   + _same_kind(after_a, gap_b(bend)))
        else:
            # A deletion: one gap closes over where the tokens were.
            new = _same_kind(before_a, gap_b(ib)) if before_a or after_a else ""
        out.append(a.text[cursor:lo])
        out.append(new)
        changes += 1
        cursor = hi
    out.append(a.text[cursor:])
    return Result("".join(out), conflicts, changes)
