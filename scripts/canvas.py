#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4"]
# ///
"""Push converted course content to Canvas, always as unpublished drafts.

    ./scripts/canvas.py whoami
    ./scripts/canvas.py list pages
    ./scripts/canvas.py list tools            # find the YuJa Panorama tool id
    ./scripts/canvas.py --dry-run push page guides/lab1/lab1.html --title "Lab 1"
    ./scripts/canvas.py --yes push page guides/lab1/lab1.html --title "Lab 1"
    ./scripts/canvas.py --yes push syllabus syllabus/syllabus.html
    ./scripts/canvas.py --yes push file handouts/table.xlsx
    ./scripts/canvas.py --yes delete page "Old Page"

Global flags go BEFORE the subcommand: `canvas.py --yes push page ...`.
Nothing writes to Canvas without a confirmation prompt (or --yes); a
non-interactive run without --yes stops with "refusing to write". Pass
--dry-run to see exactly what would be sent.

There is no --publish. Publishing, unlocking files and setting the front
page are the instructor's steps in the Canvas UI; canvas_api.py refuses
them. Settings live in course.toml and the token in .env (see README.md).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html_merge
import sync_state as st
from canvas_api import (  # noqa: E402
    Canvas,
    CanvasError,
    ConfigError,
    confirm,
    slugify,
)

import config  # noqa: E402

REPO_ROOT = config.settings().root if config.settings_or_defaults() else Path.cwd()

# --------------------------------------------------------------------------
# Turning rendered Quarto HTML into something Canvas will accept
# --------------------------------------------------------------------------


def extract_body(html: str) -> "BeautifulSoup":
    """Strip a full Quarto page down to the content Canvas should host.

    Canvas wraps page bodies in its own chrome and runs everything through a
    sanitizer, so the <head>, navigation, scripts, and stylesheets have to go.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    main = (
        soup.find("main")
        or soup.find(id="quarto-document-content")
        or soup.body
        or soup
    )

    for tag in main.find_all(["script", "style", "link", "meta", "noscript"]):
        tag.decompose()
    # Quarto's on-page furniture means nothing inside Canvas.
    for selector in ("#quarto-sidebar", "#quarto-margin-sidebar", "nav", "footer"):
        for tag in main.select(selector):
            tag.decompose()
    for tag in main.select(".quarto-title-meta, .anchorjs-link, .toc-actions"):
        tag.decompose()

    # Canvas renders its own <h1> above the body — the page title, the
    # assignment name, or "Course Syllabus". Quarto's title block repeats it,
    # and every section heading then sits one level too shallow, which leaves
    # the page with a pile of h1s and no real hierarchy for a screen reader.
    #
    # Only shift when there is an h1 to displace. Hand-authored fragments
    # already start at h2 and must be left alone.
    for tag in main.select("#title-block-header"):
        tag.decompose()
    if main.find("h1"):
        for level in range(5, 0, -1):
            for tag in main.find_all(f"h{level}"):
                tag.name = f"h{level + 1}"

    return main


def rehost_images(
    main, source_dir: Path, canvas: Canvas, folder: str, yes: bool, doc: str,
    *, folder_id: int | None = None, locked: bool | None = None
):
    """Upload every locally-referenced image and repoint the HTML at Canvas.

    Also rescues inline <svg>: Canvas's sanitizer drops those elements, so a
    diagram written inline would silently vanish. Each one is written
    out as a file, uploaded, and replaced with an <img>.

    Generated images are named `<doc>-<hash of the bytes>`. Both halves matter.
    An earlier version named them `<directory>-img-<n>`, which meant every
    problem set in problem_sets/ produced `problem_sets-img-1`, and since
    uploads use on_duplicate=overwrite, Canvas kept one file id and swapped the
    content underneath — so ten assignments ended up sharing one set of
    pictures. The document stem separates the sets; the content hash makes a
    re-push of unchanged art a no-op instead of churn.
    """
    from bs4 import BeautifulSoup  # noqa: F401

    uploaded: dict[str, str] = {}
    reused = 0

    def upload(path: Path) -> str:
        nonlocal reused
        key = str(path.resolve())
        if key not in uploaded:
            info, fresh = upload_once(canvas, path, folder_id)
            if fresh:
                print(f"  uploading {path.name}")
            else:
                reused += 1
            uploaded[key] = f"/courses/{canvas.course_id}/files/{info['id']}/preview"
        return uploaded[key]

    # Inline SVG -> uploaded file. Keep the accessible name from <title>.
    #
    # An icon sitting next to its own text label is decorative: naming it makes
    # a screen reader read the button twice. Mark those `aria-hidden="true"` or
    # `role="presentation"` in the source and they upload with alt="", which is
    # how you say "skip this" rather than "this has no alt text yet".
    scratch = REPO_ROOT / "_notes" / "uploads"
    for svg in main.find_all("svg"):
        title_tag = svg.find("title")
        decorative = (
            svg.get("aria-hidden") == "true" or svg.get("role") == "presentation"
        )
        if decorative:
            alt = ""
        elif title_tag:
            alt = title_tag.get_text(strip=True)
        else:
            alt = "Diagram"
            print(f"  WARNING: inline <svg> has no <title>, alt defaults to 'Diagram'")
        scratch.mkdir(parents=True, exist_ok=True)
        markup = str(svg)
        digest = hashlib.sha1(markup.encode("utf-8")).hexdigest()[:10]
        svg_path = scratch / f"{doc}-{digest}.svg"
        svg_path.write_text(markup, encoding="utf-8")

        img = BeautifulSoup("<img>", "html.parser").img
        img["src"] = upload(svg_path)
        img["alt"] = alt
        svg.replace_with(img)

    # <img src="images/foo.png"> -> Canvas file URL. Base64 data URIs (what
    # `embed-resources: true` produces) get decoded to real files first, since
    # Canvas strips data: sources.
    for index, img in enumerate(main.find_all("img")):
        src = img.get("src", "")
        if not src or src.startswith(("http://", "https://", "/courses/")):
            continue

        if src.startswith("data:"):
            local = _write_data_uri(src, scratch, doc)
            if local is None:
                print(f"  WARNING: could not decode inline image {index + 1}")
                continue
        else:
            local = _resolve_asset(src, source_dir)
            if local is None:
                print(f"  WARNING: {src} not found on disk, leaving as-is")
                continue

        img["src"] = upload(local)
        # alt="" is a decision — it marks the image decorative, so a screen
        # reader skips it. Only a missing attribute is an oversight.
        if img.get("alt") is None:
            print(f"  WARNING: {local.name} has no alt text")

    if reused:
        print(f"  {reused} image(s) unchanged since the last push, not re-uploaded")
    return main


def _resolve_asset(src: str, source_dir: Path) -> Path | None:
    """Find the file an <img src> points at, or None.

    Beside the HTML first, then relative to the repo root. The second lookup
    is what makes generated diagrams work: tikz.lua writes every figure to the
    workspace-level `figures/`, but a guide renders from `guides/<id>/`, so
    its `./figures/*.svg` refs can resolve to a directory that does not
    exist. Before this fallback, pushing such a page silently produced
    a page with all thirty diagrams broken — the warning scrolled past and the
    page looked fine in the summary line.

    A leading slash is stripped rather than honoured. Quarto emits `/figures/`
    for a project-absolute path, which `source_dir / src` would resolve to the
    filesystem root.
    """
    candidate = (source_dir / src).resolve()
    if candidate.exists():
        return candidate
    rooted = (REPO_ROOT / src.lstrip("/")).resolve()
    return rooted if rooted.exists() else None


def _write_data_uri(src: str, scratch: Path, doc: str) -> Path | None:
    """Decode a base64 data: URI to disk as `<doc>-<hash of the bytes>.<ext>`.

    Naming from the content rather than from a counter is what keeps two
    documents in the same folder from overwriting each other's uploads.
    """
    import base64

    header, _, payload = src.partition(",")
    if ";base64" not in header:
        return None
    media_type = header[len("data:") :].split(";")[0]
    suffix = mimetypes.guess_extension(media_type) or ".bin"

    try:
        data = base64.b64decode(payload)
    except Exception:
        return None

    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / f"{doc}-{hashlib.sha1(data).hexdigest()[:10]}{suffix}"
    path.write_bytes(data)
    return path



def guard(canvas: Canvas, kind: str, name: str, live: str | None, force: bool) -> bool:
    """Refuse to overwrite a Canvas-side edit unless told to.

    The push scripts are one-way, so without this an edit made in the browser
    disappears the next time anything is pushed, with no message.
    """
    warning = st.check(kind, name, live)
    if warning and not force:
        print(f"\n  REFUSING TO PUSH: {warning}\n")
        return False
    if warning:
        print("  (--force: overwriting a Canvas-side edit)")
    return True


def prepare_html(
    path: Path, canvas: Canvas | None, folder: str | None, yes: bool,
    upload_assets: bool = True,
    *, folder_id: int | None = None, locked: bool | None = None
) -> str:
    """Read a rendered HTML file and return a Canvas-ready body fragment.

    With canvas=None and upload_assets=False it needs no Canvas at all:
    a11y_check.py uses that to check exactly what a push would send.
    """
    html = path.read_text(encoding="utf-8")
    # A pull that could not merge cleanly leaves git-style markers in the
    # source. They would publish as literal text, so stop here instead.
    if html_merge.has_conflicts(html):
        raise CanvasError(
            f"{path} still has merge conflict markers (<<<<<<<, =======, "
            f">>>>>>>) from `canvas_sync.py pull`. Resolve them and push again."
        )
    # Author internal links as /courses/COURSE_ID/... so the same source can be
    # pushed to next year's course without a find-and-replace.
    if canvas is not None:
        html = html.replace("/courses/COURSE_ID/", f"/courses/{canvas.course_id}/")
    main = extract_body(html)
    # Source comments are notes to the instructor ("TODO", "DECISION", what
    # changed from a vendor manual). Canvas keeps them in the stored body,
    # where any student can read them with View Source, so drop them all.
    from bs4 import Comment
    for comment in main.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    if upload_assets:
        if folder_id is None:
            folder_id = draft_folder(canvas, folder or folder_for(path))
        else:
            require_locked_folder(canvas, folder_id)
        locked = True
        main = rehost_images(
            main, path.parent, canvas, folder, yes, doc=path.stem,
            folder_id=folder_id, locked=locked
        )
    _fix_table_a11y(main)
    _fix_text_a11y(main)
    return main.decode_contents() if hasattr(main, "decode_contents") else str(main)


def folder_for(path: Path) -> str:
    """The Canvas folder a source's uploads belong in, mirroring the repo.

    guides/lab_1/lab_1.html      -> course files/guides/lab-1
    syllabus/syllabus.html       -> course files/syllabus
    canvas/home.html (site pages) -> course files/site
    """
    try:
        rel = Path(path).resolve().parent.relative_to(REPO_ROOT)
    except ValueError:
        rel = Path()
    parts = [p.replace("_", "-") for p in rel.parts if p not in (".",)]
    if not parts or parts[0] == "canvas":
        parts = ["site"]
    return "course files/" + "/".join(parts)


def draft_folder(canvas: Canvas, folder_path: str) -> int:
    """Return a folder id for draft uploads, creating any missing level locked.

    Every upload goes into a folder named for what it belongs to, and a new
    folder starts locked, so nothing is reachable by students until the
    instructor unlocks it. A folder that already exists is never re-locked: if
    it is unlocked, the instructor has released it, and locking it again would break pages
    students are already reading. Files are still uploaded locked into it.
    """
    parts = [p for p in folder_path.strip("/").split("/") if p]
    if not parts or parts[0] != "course files":
        parts = ["course files", *parts]
    if len(parts) == 1:
        raise CanvasError("upload into a subfolder, not the root of course files")

    existing = {f["full_name"]: f for f in canvas.folders()}
    for depth in range(2, len(parts) + 1):
        full = "/".join(parts[:depth])
        if full in existing:
            continue
        print(f"  creating locked folder {full}")
        existing[full] = canvas.post(
            f"courses/{canvas.course_id}/folders",
            # By id, not path: with no parent path Canvas files a new
            # top-level folder under "unfiled" rather than at the root.
            data={
                "name": parts[depth - 1],
                "parent_folder_id": existing["/".join(parts[: depth - 1])]["id"],
                "locked": "true",
            },
        )
        canvas.remember_folder(existing[full])
    leaf = existing["/".join(parts)]
    if not leaf.get("locked"):
        print(f"  note: {leaf['full_name']} is unlocked (released); "
              "new files go in locked")
    return leaf["id"]


UPLOADS = st.STATE.parent / ".uploads.json"


def upload_once(canvas: Canvas, path: Path, folder_id: int) -> tuple[dict, bool]:
    """Upload a file, locked, unless Canvas already has these exact bytes.

    Returns (file, uploaded). Every push used to upload every image on the
    page again, three requests and the bytes each, even when nothing had
    changed: about 600 requests per re-push of a manual with 190 figures,
    and a manual is re-pushed after each round of fixes. canvas/.uploads.json
    records the content hash and file id of each upload; an image whose
    bytes match its record, and whose file is still in the folder, is
    reused. Checking that costs one listing per folder, not one per image.

    A reused file keeps its lock state: if the instructor has unlocked it,
    uploading over it would lock it again under pages students can read.
    """
    record = _read_uploads()
    key = f"{canvas.course_id}/{folder_id}/{path.name}"
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    seen = record.get(key)
    if seen and seen["sha1"] == digest:
        live = canvas.folder_files(folder_id).get(seen["id"])
        if live is not None and live.get("size") == seen.get("size"):
            return live, False
    info = canvas.upload_file(path, folder_id=folder_id, locked=True)
    canvas.remember_file(folder_id, info)
    record[key] = {"sha1": digest, "id": info["id"], "size": info.get("size")}
    _write_uploads(record)
    return info, True


def _read_uploads() -> dict:
    try:
        return json.loads(UPLOADS.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _write_uploads(record: dict) -> None:
    UPLOADS.parent.mkdir(parents=True, exist_ok=True)
    tmp = UPLOADS.with_name(f"{UPLOADS.name}.{os.getpid()}")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(UPLOADS)


def upload_draft(canvas: Canvas, path: Path, folder: str | None = None) -> dict:
    """Upload one file, locked, into its organised folder."""
    folder_id = draft_folder(canvas, folder or folder_for(path))
    return upload_once(canvas, path, folder_id)[0]


def require_locked_folder(canvas: Canvas, folder_id: int | None) -> None:
    """Keep draft files inaccessible during upload as well as afterward."""
    if folder_id is None:
        raise CanvasError("--locked requires --folder-id for a locked draft folder")
    folder = canvas.get(f"folders/{folder_id}")
    if not folder.get("locked"):
        raise CanvasError(f"draft folder {folder_id} must already be locked")


GATE_NAMES = {"AND", "OR", "XOR", "NAND", "NOR", "NOT", "XNOR",
              "CNOT", "SWAP", "TOFFOLI", "IDENTITY"}


def _fix_table_a11y(soup) -> None:
    """Make every table pass an accessibility checker.

    Two things Quarto/Pandoc leave out, both flagged Severe by YuJa:

    `scope` on header cells. Without it a screen reader cannot tell whether a
    header labels its column or its row. Everything we generate is a column
    header, so scope="col" is always right.

    `<caption>`. A caption is how a screen-reader user decides whether a table
    is worth entering. Derived from the last column header when that names a
    gate (the common case in this course: A, B, XOR is the XOR truth table),
    otherwise from the nearest preceding heading, and failing that from the
    column headers. A table can sit above the first section heading (the
    Source-box table in a problem set's instructions does), so the heading is
    not guaranteed.
    """
    # `extract_body` normally returns the <main> Tag from a full Quarto page,
    # not the BeautifulSoup document itself. Only the document can create a
    # new tag in every BeautifulSoup version, so keep it as the factory.
    factory = soup
    while getattr(factory, "parent", None) is not None:
        factory = factory.parent

    for table in soup.find_all("table"):
        # A table with no header cells is being used for layout, not data —
        # in this course that is a row of bit patterns lined up for display.
        # role="presentation" tells a screen reader to read the contents and
        # skip the grid semantics. Such a table must not carry a caption,
        # which would reassert that it is a data table.
        if not table.find("th"):
            table["role"] = "presentation"
            if (cap := table.find("caption")):
                cap.decompose()
            continue

        for th in table.find_all("th"):
            if not th.get("scope"):
                th["scope"] = "col"

        if table.find("caption"):
            continue
        caption = _caption_for(table, soup)
        if caption:
            tag = factory.new_tag("caption")
            tag.string = caption
            table.insert(0, tag)


def _fix_text_a11y(soup) -> None:
    """Two YuJa Panorama findings that every Quarto page produces.

    SmallFontSizeIssue. Panorama measures text with the browser's default
    styles, not Canvas's, and the usual minimum is 10 pt. A browser sets bare
    `monospace` at 13 px (9.75 pt), so every <code>, <pre>, <kbd> and <samp>
    fails; `font-size: 1em` does not help, but naming the family twice
    (`monospace, monospace`) restores 16 px. <h5> defaults to 0.83em (9.96
    pt) and <h6> to 0.67em, so both get 1em. Measured in headless Chrome,
    Nov 2026.

    EmptyHyperlinkIssue. Pandoc gives every line of a code block an empty
    anchor (<a href="#cb1-1" aria-hidden="true"></a>). Hidden or not,
    Panorama counts each as a severe empty link; nothing points at them, so
    they go.
    """
    for a in soup.find_all("a", href=True):
        if (a["href"].startswith("#cb") and not a.get_text(strip=True)
                and not a.find("img")):
            a.decompose()
    for tag in soup.find_all(["code", "pre", "kbd", "samp"]):
        style = tag.get("style", "")
        if "monospace, monospace" not in style:
            tag["style"] = "font-family: monospace, monospace; " + style
    for tag in soup.find_all(["h5", "h6"]):
        style = tag.get("style", "")
        if "font-size" not in style:
            tag["style"] = "font-size: 1em; " + style


def _caption_for(table, root) -> str:
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    if headers:
        last = headers[-1].upper()
        if last in GATE_NAMES:
            return f"Truth table for the {headers[-1]} gate."
        if last == "OUTPUT" and len(headers) <= 3:
            return "Truth table."
    for prev in table.find_all_previous(["h1", "h2", "h3", "h4"]):
        # Only headings inside the content being pushed. `root` is still
        # attached to the full Quarto page, whose margin sidebar puts an
        # "Other Formats" <h2> ahead of <main>, and a table above the first
        # section heading used to take that as its caption. The search runs
        # backwards, so the first heading outside root means none remain.
        if root.parent is not None and not any(p is root for p in prev.parents):
            break
        # separator=" " matters: Quarto wraps the section number in its own
        # <span>, so strip=True alone yields "2Logic Circuits".
        text = re.sub(r"\s+", " ", prev.get_text(separator=" ", strip=True))
        # Drop a leading section number, which is numbering rather than title.
        text = re.sub(r"^[\d.]+\s+", "", text)
        if text:
            return f"{text}."
    if any(headers):
        return "Columns: " + "; ".join(h for h in headers if h) + "."
    return ""


# --------------------------------------------------------------------------
# Commands — reading
# --------------------------------------------------------------------------


def cmd_whoami(canvas: Canvas, args) -> None:
    me = canvas.whoami()
    course = canvas.course()
    print(f"Signed in as {me.get('name')} <{me.get('primary_email', '')}>")
    print(f"Course {course['id']}: {course.get('name')}")
    print(f"  term       {course.get('term', {}).get('name', 'n/a')}")
    if str(course["id"]) != canvas.course_id:
        raise CanvasError("Canvas returned a different course than course.toml names")


def cmd_list(canvas: Canvas, args) -> None:
    what = args.what
    if what == "tools":
        # The YuJa Panorama tool id for course.toml [panorama] tool_id.
        for t in canvas.paginate(f"courses/{canvas.course_id}/external_tools",
                                 include_parents="true"):
            print(f"{t['id']:>8}  {t.get('name')}")
    elif what == "files":
        for f in canvas.files():
            state = "locked" if f.get("locked") else "unlocked"
            print(f"{f['id']:>8}  folder={f.get('folder_id')}  "
                  f"{state:<8}  {f.get('display_name', f.get('filename', ''))}")
    elif what == "pages":
        for p in canvas.pages():
            state = "published" if p.get("published") else "unpublished"
            print(f"{p['url']:<44}  {state:<12}  {p['title']}")
    elif what == "modules":
        for m in canvas.modules():
            print(f"{m['id']:>8}  {m['name']}")
            if args.items:
                for it in canvas.module_items(m["id"]):
                    print(f"{'':>10}{'  ' * it.get('indent', 0)}{it['type']:<12} {it['title']}")
    elif what == "discussions":
        for d in canvas.discussions():
            state = "published" if d.get("published") else "unpublished"
            print(f"{d['id']:>8}  {state:<12}  {d['title']}")
    else:
        raise CanvasError(f"nothing to list called {what!r}")


def cmd_push_page(canvas: Canvas, args) -> None:
    path = Path(args.file)
    title = args.title or path.stem.replace("-", " ").replace("_", " ").title()

    # A dry run must not upload anything, so asset rehosting is skipped;
    # image sources stay as authored rather than as Canvas file URLs.
    body = prepare_html(
        path, canvas, args.folder, args.yes, upload_assets=not args.dry_run,
        folder_id=args.folder_id, locked=True if args.locked else None
    )
    # A page over page_parts.WORD_BUDGET words becomes several pages, cut at
    # its chapters, each with a contents box and Previous / Next links.
    # By default part 1 keeps the title (so links to the page still work);
    # with --named-parts (the default for anything under a manuals/ folder)
    # every part is "<title> (Part k of n): <chapter>".
    # Links between parts use each page's address, which for a page not yet
    # created is the slug Canvas will give it.
    import page_parts
    named = args.named_parts or "manuals" in path.parts
    urls: dict[str, str] = {}

    def page_url(t: str) -> str:
        if t not in urls:
            # Index only: the splitter asks about every candidate split's
            # titles, and the relink pass below checks the real ones.
            found = canvas.find_page(t, recheck=False)
            urls[t] = found["url"] if found else slugify(t)
        return f"/courses/{canvas.course_id}/pages/{urls[t]}"

    parts = page_parts.split(body, title, page_url, named)
    if len(parts) > 1:
        print(f"{title!r} is long: pushing it as {len(parts)} parts")
    for part_title, part_body in parts:
        page = _push_page_body(canvas, args, path, part_title, part_body)
        if page is None:
            return
    if len(parts) > 1 and not args.dry_run:
        # A new page's address is Canvas's to choose, and slugify() does not
        # always guess it ("5.1" becomes "5-dot-1"). Now that every part
        # exists, look each one up; if any guess was wrong, push the parts
        # again so the links between them use the real addresses.
        guessed = dict(urls)
        urls.clear()
        relinked = page_parts.split(body, title, page_url, named)
        if urls != guessed:
            print("   (some addresses differ from the predicted ones; relinking)")
            for t, b in relinked:
                _push_page_body(canvas, args, path, t, b, quiet=True)
    titles = {t for t, _ in parts}
    stale = [p["title"] for p in canvas.pages()
             if (p["title"].startswith(f"{title} (Part ")
                 or (p["title"] == title and len(parts) > 1)) and p["title"] not in titles]
    for t in stale:
        print(f"   stale part from an earlier split, delete it: {t!r}")


def _push_page_body(canvas: Canvas, args, path: Path, title: str, body: str,
                    quiet: bool = False) -> dict | None:
    existing = canvas.find_page(title)
    verb = "Update" if existing else "Create"

    print(f"{verb} page {title!r} ({len(body)} chars of HTML)")
    # Our accessibility checklist (scripts/a11y_check.py): what YuJa
    # Panorama would flag, found now rather than after the next scan.
    # It warns rather than refuses while some rules have no fix yet.
    try:
        from a11y_check import check_body
    except ImportError:
        check_body = None
    if check_body and not quiet:
        for finding in check_body(body):
            print(f"   accessibility: {finding}")
    if args.dry_run:
        if not quiet:
            print(body[:2000])
        return {}
    if not confirm(f"{verb} this page in the live course?", args.yes):
        print("cancelled")
        return None

    live = canvas.get(
        f"courses/{canvas.course_id}/pages/{existing['url']}"
    )["body"] if existing else None
    if not guard(canvas, "page", title, live, getattr(args, "force", False)):
        return None

    page = canvas.upsert_page(title, body)
    st.record("page", title, source=path,
              pushed_body=page.get("body") or body)
    print(f"-> {canvas.base_url}/courses/{canvas.course_id}/pages/{page['url']}")
    # Report what Canvas stored. An update leaves an already-published page
    # published: the instructor released it, and that is theirs to change.
    print("   (unpublished — students cannot see it yet)" if not page.get("published")
          else "   (already published by the instructor; content updated)")
    return page


def cmd_push_discussion(canvas: Canvas, args) -> None:
    """Push a hand-authored HTML file into a discussion topic."""
    path = Path(args.file)
    title = args.title or path.stem.replace("_", " ").title()
    body = prepare_html(path, canvas, args.folder, args.yes)

    existing = canvas.find_discussion(title)
    verb = "Update" if existing else "Create"
    print(f"{verb} discussion {title!r} ({len(body)} chars of HTML)")
    if args.dry_run:
        return
    if not confirm(f"{verb} this discussion?", args.yes):
        print("cancelled")
        return

    if not guard(canvas, "discussion", title,
                 existing.get("message") if existing else None,
                 getattr(args, "force", False)):
        return

    topic = canvas.upsert_discussion(title, body)
    st.record("discussion", title, source=path,
              pushed_body=topic.get("message") or body)
    print(f"-> {canvas.base_url}/courses/{canvas.course_id}"
          f"/discussion_topics/{topic['id']}")
    if not topic.get("published"):
        print("   (unpublished — students cannot see it yet)")


def cmd_push_syllabus(canvas: Canvas, args) -> None:
    """Write the course's Syllabus tab, which is where Canvas expects it."""
    path = Path(args.file)
    # A dry run must not upload anything, so asset rehosting is skipped;
    # image sources stay as authored rather than as Canvas file URLs.
    body = prepare_html(
        path, canvas, args.folder, args.yes, upload_assets=not args.dry_run
    )

    print(f"Write the Syllabus tab from {path.name} ({len(body)} chars)")
    # The checklist, as for pages. The syllabus cannot be split into parts,
    # so a ContentLength finding means moving material to a page.
    from a11y_check import check_body
    for finding in check_body(body):
        print(f"   accessibility: {finding}")
    if args.dry_run:
        print(body[:1500])
        return
    if not confirm("Replace the course syllabus?", args.yes):
        print("cancelled")
        return

    live = canvas.get(
        f"courses/{canvas.course_id}", **{"include[]": "syllabus_body"}
    ).get("syllabus_body")
    if not guard(canvas, "syllabus", "Syllabus", live, getattr(args, "force", False)):
        return

    canvas.set_syllabus_body(body)
    stored = canvas.get(
        f"courses/{canvas.course_id}", **{"include[]": "syllabus_body"}
    ).get("syllabus_body")
    st.record("syllabus", "Syllabus", source=path, pushed_body=stored or body)
    print(f"-> {canvas.base_url}/courses/{canvas.course_id}/assignments/syllabus")

def cmd_push_file(canvas: Canvas, args) -> None:
    path = Path(args.file)
    folder = args.folder or folder_for(path)
    print(f"Upload {path.name} -> {folder} (locked)")
    if args.dry_run:
        return
    if not confirm("Upload to the live course?", args.yes):
        print("cancelled")
        return
    if args.folder_id is not None:
        require_locked_folder(canvas, args.folder_id)
        info = upload_once(canvas, path, args.folder_id)[0]
    else:
        info = upload_draft(canvas, path, folder)
    print(f"-> {canvas.base_url}/courses/{canvas.course_id}/files/{info['id']}")
    print("   (locked — students cannot open it until you unlock it)")


def cmd_delete(canvas: Canvas, args) -> None:
    """Remove pages, discussions, modules, module items or files by name."""
    kind = args.kind
    targets: list[tuple[str, object]] = []

    if kind == "page":
        by_slug = {p["url"]: p for p in canvas.pages()}
        by_title = {p["title"]: p for p in canvas.pages()}
        for name in args.names:
            page = by_slug.get(name) or by_title.get(name) or by_slug.get(
                slugify(name)
            )
            if not page:
                raise CanvasError(f"no page {name!r}")
            targets.append((page["title"], page["url"]))
    elif kind == "file":
        files = canvas.files()
        for name in args.names:
            match = [f for f in files if name in (f.get("display_name"), f.get("filename"),
                                                  str(f["id"]))]
            if len(match) != 1:
                raise CanvasError(f"{name!r} matched {len(match)} files; give the file id")
            targets.append((f"{match[0]['display_name']} (id {match[0]['id']})", match[0]["id"]))
    elif kind == "module-item":
        # "<module name>/<item title>", both exact.
        modules = {m["name"]: m for m in canvas.modules()}
        for name in args.names:
            mod, _, item = name.partition("/")
            if mod not in modules:
                raise CanvasError(f"no module {mod!r} (write it as 'Module/Item title')")
            match = [it for it in canvas.module_items(modules[mod]["id"]) if it["title"] == item]
            if len(match) != 1:
                raise CanvasError(f"{item!r} matched {len(match)} items in {mod!r}")
            targets.append((name, (modules[mod]["id"], match[0]["id"])))
    elif kind == "discussion":
        topics = canvas.discussions()
        for name in args.names:
            match = [t for t in topics if name.lower() in t["title"].lower()]
            if len(match) != 1:
                raise CanvasError(
                    f"{name!r} matched {len(match)} discussions; be more specific"
                )
            targets.append((match[0]["title"], match[0]["id"]))
    elif kind == "module":
        modules = canvas.modules()
        for name in args.names:
            match = [m for m in modules if name.lower() in m["name"].lower()]
            if len(match) != 1:
                raise CanvasError(
                    f"{name!r} matched {len(match)} modules; be more specific"
                )
            targets.append((match[0]["name"], match[0]["id"]))
    else:
        raise CanvasError(f"cannot delete {kind!r}")

    print(f"Delete {len(targets)} {kind}(s) from the live course:")
    for label, _ in targets:
        print(f"  - {label}")
    print(
        "\nCanvas keeps deleted items on /courses/"
        f"{canvas.course_id}/undelete for a while, but do not count on it."
    )

    if args.dry_run:
        return
    if not confirm("Delete these?", args.yes):
        print("cancelled")
        return

    deleter = {
        "page": canvas.delete_page,
        "file": lambda i: canvas.request("DELETE", f"files/{i}"),
        "module-item": lambda ids: canvas.request(
            "DELETE", f"courses/{canvas.course_id}/modules/{ids[0]}/items/{ids[1]}"),
        "discussion": canvas.delete_discussion,
        "module": canvas.delete_module,
    }[kind]
    for label, ident in targets:
        deleter(ident)
        print(f"  deleted {label}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canvas.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be sent; make no changes",
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="push even if the item has been edited in Canvas since the last push",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="verify the token and show the course")

    p_list = sub.add_parser("list", help="list things in the course")
    p_list.add_argument(
        "what", choices=["pages", "files", "modules", "discussions", "tools"],
    )
    p_list.add_argument("--items", action="store_true",
                        help="with `list modules`: show each module's items")

    p_push = sub.add_parser("push", help="send content to Canvas")
    push_sub = p_push.add_subparsers(dest="target", required=True)

    p = push_sub.add_parser("page", help="rendered HTML -> a Canvas page")
    p.add_argument("file", help="a rendered .html file")
    p.add_argument("--title")
    p.add_argument(
        "--folder",
        default=None,
        help="Canvas folder for uploaded images (default: mirrors the source's "
             "folder, e.g. course files/guides/lab-1)",
    )
    p.add_argument("--folder-id", type=int, help="Canvas destination folder ID")
    p.add_argument("--named-parts", action="store_true",
                   help="name every part of a long page after its chapter "
                        "(default for files under a manuals/ folder)")
    # Uploads are always locked; the flag stays so old commands run.
    p.add_argument("--locked", action="store_true", help=argparse.SUPPRESS)

    p_disc = push_sub.add_parser(
        "discussion", help="hand-authored HTML -> a discussion topic"
    )
    p_disc.add_argument("file", help="an .html file")
    p_disc.add_argument("--title", help="discussion title (matched exactly)")
    p_disc.add_argument("--folder", default=None)

    p_syl = push_sub.add_parser("syllabus", help="rendered HTML -> the Syllabus tab")
    p_syl.add_argument("file", help="a rendered .html file")
    p_syl.add_argument("--folder", default=None)

    p_file = push_sub.add_parser("file", help="upload any file to the course")
    p_file.add_argument("file")
    p_file.add_argument("--folder", default=None)
    p_file.add_argument("--folder-id", type=int)
    p_file.add_argument("--locked", action="store_true", help=argparse.SUPPRESS)

    p_delete = sub.add_parser("delete", help="remove content from the course")
    p_delete.add_argument(
        "kind", choices=["page", "discussion", "module", "module-item", "file"]
    )
    p_delete.add_argument("names", nargs="+", help="titles (or unique substrings)")

    return parser


DISPATCH = {
    ("whoami", None): cmd_whoami,
    ("list", None): cmd_list,
    ("push", "page"): cmd_push_page,
    ("push", "discussion"): cmd_push_discussion,
    ("push", "syllabus"): cmd_push_syllabus,
    ("push", "file"): cmd_push_file,
    ("delete", None): cmd_delete,
}


def main() -> int:
    args = build_parser().parse_args()
    handler = DISPATCH.get((args.command, getattr(args, "target", None)))
    if handler is None:
        print(f"unknown command: {args.command}", file=sys.stderr)
        return 2

    try:
        canvas = Canvas.from_env(dry_run=args.dry_run)
        handler(canvas, args)
    except ConfigError as error:
        print(f"\n{error}\n", file=sys.stderr)
        return 2
    except CanvasError as error:
        print(f"\nCanvas error: {error}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
