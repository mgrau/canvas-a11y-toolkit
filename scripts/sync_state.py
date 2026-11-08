"""Track what we last pushed, so a Canvas-side edit is never silently lost.

The push scripts are one-way. Without a record of what was sent, an edit made
in the Canvas UI is invisible until the next push overwrites it. This module
keeps that record and gives the push commands something to check against.

THE TWO QUESTIONS

For each item there are two independent facts, and it matters which is which:

    source changed   the local file differs from the copy we last pushed
    canvas changed   the live body differs from the copy we last pushed

Only one of those means trouble. Source changed on its own is the normal case:
edit, push. Canvas changed on its own means somebody edited in the browser and
the source is now stale. Both at once is a genuine conflict and the only case
where anything can be lost.

LIKE GIT

The record works the way a remote-tracking branch does. `pushed_hash` is the
last version of the live body this repo has *seen*: set by a push, and moved
forward by `canvas_sync.py pull` once a Canvas edit has been merged into the
source. A push is refused while Canvas holds anything newer, the way git
refuses a push that is not a fast-forward, and the fix is the same: pull,
check the merge, push.

A pull is a three-way merge (see html_merge.py), so it needs the base as well
as its hash. Every push therefore keeps a copy of the body Canvas stored in
canvas/.sync-base/. Items pushed before that existed have no copy until
`canvas_sync.py baseline` takes one.

Assignment settings (due date, points, group, file types) are tracked the
same way, field by field: what we last asked for, and what Canvas had after.
See `merge_settings`.

NORMALISATION

Canvas does not hand back what you gave it. It injects the school's theme stylesheet and a
mobile script, adds data-api-endpoint and loading="lazy" to every image, and
appends a ?verifier= token to file URLs that rotates on its own. Comparing raw
bodies therefore reports a difference every single time. `normalise` strips all
of that so a difference means somebody actually changed the words.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import config  # noqa: E402

_cfg = config.settings_or_defaults()
STATE = (_cfg.root if _cfg else Path.cwd()) / "canvas" / ".sync-state.json"
BASE_DIR = STATE.parent / ".sync-base"

# The assignment settings a push can set, and so the ones a Canvas edit to
# them must not be silently undone.
SETTINGS = ("points_possible", "due_at", "assignment_group_id",
            "submission_types", "allowed_extensions")


def normalise(body: str | None) -> str:
    """Reduce a Canvas body to just its authored content."""
    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(body or "", "html.parser")

    # The source files carry long comments explaining their own design, and
    # Canvas strips comments on the way in. Without this every item compares
    # unequal the instant it is pushed.
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    # Canvas injects these into every page it serves; they are not ours.
    for tag in soup.find_all(["script", "link"]):
        src = tag.get("src") or tag.get("href") or ""
        if "instructure-uploads" in src or "amazonaws" in src:
            tag.decompose()

    # Canvas annotates anything pointing inside the course — links as well as
    # images — with its own data-api-* attributes.
    for tag in soup.find_all(True):
        for attr in ("data-api-endpoint", "data-api-returntype", "loading",
                     "data-decorative"):
            tag.attrs.pop(attr, None)

    for img in soup.find_all("img"):
        for attr in ("width", "height"):
            img.attrs.pop(attr, None)
        # The verifier token rotates, so the same file compares unequal to
        # itself a day later. Keep the path, drop the query.
        if img.get("src"):
            img["src"] = img["src"].split("?")[0]

    # Canvas appends the same rotating ?verifier= to plain links to course
    # files, not only to images. Missing this reported the week pages as
    # edited-in-Canvas every time a slides link was on them, which is noise
    # that trains you to ignore the warning.
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if "verifier=" in href:
            a["href"] = href.split("?")[0]

    text = str(soup)
    # Internal links are authored relative and Canvas hands them back absolute,
    # so /courses/217294/x and https://canvas.example.edu/courses/217294/x are the
    # same link written two ways. Compare them as one.
    text = re.sub(r"https?://[^/\"'\s]+/courses/", "/courses/", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def key(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def _base_path(kind: str, name: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:60]
    return BASE_DIR / f"{kind}--{slug}--{digest(key(kind, name))[:6]}.html"


def base_body(kind: str, name: str) -> str | None:
    """The live body as it stood after our last push or pull, if we kept it."""
    entry = _load().get(key(kind, name))
    path = _base_path(kind, name)
    if not entry or not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # A copy that no longer matches the recorded hash is from an older push.
    return text if digest(normalise(text)) == entry["pushed_hash"] else None


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")


def keep_base(kind: str, name: str, body: str) -> None:
    """Store a merge base. It must match the recorded hash to be used."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    _base_path(kind, name).write_text(body, encoding="utf-8")


def record(kind: str, name: str, *, source: Path | None, pushed_body: str,
           settings: dict | None = None) -> None:
    """Remember what we just pushed, and what it was rendered from.

    `settings`, for an assignment, is {"requested": {...}, "live": {...}}: the
    values this push asked for and the ones Canvas holds afterwards.
    """
    repo = STATE.parent.parent
    rel = src_hash = None
    if source is not None:
        # The commands are run with relative paths, so resolve before asking
        # where this sits. A source from outside the repo is recorded by its
        # absolute path rather than refused.
        full = source.resolve()
        rel = str(full.relative_to(repo)) if full.is_relative_to(repo) else str(full)
        src_hash = digest(full.read_text(encoding="utf-8"))

    state = _load()
    entry = {
        "source": rel,
        "source_hash": src_hash,
        "pushed_hash": digest(normalise(pushed_body)),
    }
    old = state.get(key(kind, name), {})
    if settings is not None:
        requested = dict(old.get("settings", {}).get("requested", {}))
        requested.update(settings.get("requested", {}))
        entry["settings"] = {"requested": requested,
                             "live": settings.get("live", {})}
    elif "settings" in old:
        entry["settings"] = old["settings"]
    state[key(kind, name)] = entry
    _save(state)
    keep_base(kind, name, pushed_body)


def remember_live(kind: str, name: str, live_body: str,
                  live_settings: dict | None = None) -> None:
    """Mark the live version as seen: the result of a pull, or a baseline.

    Moves the tracking hash and the merge base forward without touching the
    source record, so `status` still reports the source as changed when a
    merge put Canvas's edit into it and it has not been pushed yet.
    """
    state = _load()
    entry = state.setdefault(key(kind, name),
                             {"source": None, "source_hash": None})
    entry["pushed_hash"] = digest(normalise(live_body))
    if live_settings is not None:
        s = entry.setdefault("settings", {})
        s["live"] = live_settings
        s.setdefault("requested", dict(live_settings))
    _save(state)
    keep_base(kind, name, live_body)


def settings(kind: str, name: str) -> dict | None:
    return _load().get(key(kind, name), {}).get("settings")


def _same(x, y) -> bool:
    if isinstance(x, (list, tuple)) or isinstance(y, (list, tuple)):
        return sorted(x or []) == sorted(y or [])
    if isinstance(x, (int, float)) or isinstance(y, (int, float)):
        try:
            return float(x) == float(y)
        except (TypeError, ValueError):
            return False
    return (x or None) == (y or None)


def merge_settings(requested: dict, live: dict, tracked: dict | None):
    """Decide, field by field, what a push may send. Like a three-way merge.

    A field is sent only if this push asks for something different from what
    the last push asked for. Asking for the same thing again is not a change,
    so whatever Canvas holds now stays, which is what keeps a due date moved
    in the browser from being moved back by a re-run of an old command. If
    both sides changed a field to different values, that is a conflict.

    Returns (send, kept, conflicts): the fields to send; the Canvas-side edits
    left alone; and {field: (asked, live)} for the conflicts.
    """
    if not tracked:
        return dict(requested), {}, {}  # no record: the old, send-all behaviour
    last_asked = tracked.get("requested", {})
    last_live = tracked.get("live", {})
    send, kept, conflicts = {}, {}, {}
    for field, want in requested.items():
        now = live.get(field)
        canvas_changed = field in last_live and not _same(now, last_live[field])
        if field in last_asked and _same(want, last_asked[field]):
            if canvas_changed:
                kept[field] = now
            continue
        if canvas_changed and not _same(want, now):
            conflicts[field] = (want, now)
            continue
        send[field] = want
    return send, kept, conflicts


def check(kind: str, name: str, live_body: str | None) -> str | None:
    """Return a warning if pushing would overwrite something we did not write.

    FAILS CLOSED. An earlier version returned None whenever there was no
    record, which reads as "safe to push" but actually means "no idea what is
    there". Those are not the same thing, and the difference is exactly the
    case that loses work: a page created or retitled in the Canvas UI has no
    record under its current name, so the one item most likely to hold an edit
    was the one item the guard waved through.

    A missing record is only safe when the item does not exist on Canvas yet,
    which is an ordinary create.
    """
    entry = _load().get(key(kind, name))
    if not entry:
        if not (live_body or "").strip():
            return None  # nothing there yet: this is a create
        return (
            f"{name!r} exists in Canvas but this repo has no record of pushing "
            f"it. It may have been created or retitled in the browser, and "
            f"pushing now overwrites whatever is there.\n"
            f"    see it:    ./scripts/canvas_sync.py diff {kind} {name!r}\n"
            f"    keep it:   ./scripts/canvas_sync.py adopt {kind} {name!r}\n"
            f"    discard:   push again with --force"
        )
    if digest(normalise(live_body)) != entry["pushed_hash"]:
        return (
            f"{name!r} has been edited in Canvas since this repo last pushed "
            f"or pulled it. Pushing now would overwrite that edit.\n"
            f"    merge it:  ./scripts/canvas_sync.py pull {kind} {name!r}\n"
            f"               then check the source and push again\n"
            f"    see it:    ./scripts/canvas_sync.py diff {kind} {name!r}\n"
            f"    discard:   push again with --force"
        )
    return None


def entries() -> dict:
    return _load()
