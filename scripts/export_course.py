#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Export an old (source) Canvas course into source/, read only.

    ./scripts/export_course.py              # the first of source_course_ids
    ./scripts/export_course.py 206330       # one of them by id

Writes, under the workspace's source/ folder (gitignored: it is someone
else's material and vendor manuals, so it never goes into git):

    source/modules/NN Module name/<files>   every file each module links
    source/pages/<slug>.html                every page body
    source/syllabus.html                    the Syllabus tab
    source/assignments/<name>.html          assignment descriptions
    source/manifest.json                    modules, items, file ids, links

It only reads. The client is read-only (canvas_api.Canvas.source), so this
cannot change the source course, and it reads no students, grades or
submissions. Re-running skips files already downloaded.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from canvas_api import Canvas, CanvasError  # noqa: E402


def safe(name: str) -> str:
    return re.sub(r'[/\\:*?"<>|]+', "-", name).strip()[:120] or "untitled"


def main() -> int:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    cfg = config.settings()
    try:
        src = Canvas.source(sys.argv[1] if len(sys.argv) > 1 else None)
        if src.course_id not in cfg.source_course_ids:
            raise SystemExit(f"{src.course_id} is not in source_course_ids in course.toml")
        course = src.course()
    except CanvasError as e:
        print(f"\n{e}\n", file=sys.stderr)
        return 1
    out = cfg.source_dir
    out.mkdir(parents=True, exist_ok=True)
    print(f"Exporting course {course['id']} ({course.get('name')}) -> {out}")
    manifest: dict = {"course": {"id": course["id"], "name": course.get("name"),
                                 "code": course.get("course_code")},
                      "modules": [], "pages": [], "assignments": []}

    for n, m in enumerate(src.modules(), 1):
        folder = out / "modules" / f"{n:02d} {safe(m['name'])}"
        entry = {"name": m["name"], "folder": str(folder.relative_to(cfg.root)), "items": []}
        for it in src.module_items(m["id"]):
            rec = {"type": it["type"], "title": it["title"], "indent": it.get("indent", 0)}
            if it["type"] == "File":
                f = src.get(f"courses/{src.course_id}/files/{it['content_id']}")
                rec["file_id"] = f["id"]
                rec["filename"] = f.get("display_name") or f.get("filename")
                dest = folder / safe(rec["filename"])
                rec["path"] = str(dest.relative_to(cfg.root))
                if not dest.exists():
                    folder.mkdir(parents=True, exist_ok=True)
                    r = src.session.get(f["url"], timeout=300)
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                    print(f"  {dest.relative_to(out)}")
            elif it["type"] == "Page":
                rec["page_url"] = it.get("page_url")
            elif it["type"] == "ExternalUrl":
                rec["url"] = it.get("external_url")
            entry["items"].append(rec)
        manifest["modules"].append(entry)

    pages_dir = out / "pages"
    pages_dir.mkdir(exist_ok=True)
    for p in src.pages():
        full = src.get(f"courses/{src.course_id}/pages/{p['url']}")
        (pages_dir / f"{p['url']}.html").write_text(full.get("body") or "")
        manifest["pages"].append({"title": p["title"], "url": p["url"],
                                  "published": p.get("published")})
    print(f"  {len(manifest['pages'])} pages")

    syl = src.get(f"courses/{src.course_id}", **{"include[]": "syllabus_body"})
    (out / "syllabus.html").write_text(syl.get("syllabus_body") or "")

    adir = out / "assignments"
    adir.mkdir(exist_ok=True)
    for a in src.assignments():
        (adir / f"{safe(a['name'])}.html").write_text(a.get("description") or "")
        manifest["assignments"].append({
            k: a.get(k) for k in ("name", "points_possible", "submission_types",
                                  "allowed_extensions", "due_at", "grading_type")})
    print(f"  {len(manifest['assignments'])} assignment descriptions")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"Wrote {out / 'manifest.json'}. Next: ./scripts/triage.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
