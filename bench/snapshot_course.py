#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Snapshot the course a benchmark run starts from (read only).

    bench/snapshot_course.py <out.json>

Run inside the course workspace once the instructor has imported the
source course: modules with their items, pages, files, discussions,
assignments, quizzes, and what is published. Prints the counts, to compare
with an earlier run's snapshot (_notes/baseline/canvas-after-import.json).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from canvas_api import Canvas  # noqa: E402

c = Canvas.from_env(dry_run=True)
cid = c.course_id
mods = list(c.paginate(f"courses/{cid}/modules", include=["items"], per_page=100))
pages, files, disc = c.pages(), c.files(), c.discussions()
assign = list(c.paginate(f"courses/{cid}/assignments", per_page=100))
quiz = list(c.paginate(f"courses/{cid}/quizzes", per_page=100))
pub = {"modules": [m["name"] for m in mods if m.get("published")],
       "pages": [p["title"] for p in pages if p.get("published")],
       "discussions": [d["title"] for d in disc if d.get("published")],
       "assignments": [a["name"] for a in assign if a.get("published")],
       "quizzes": [q["title"] for q in quiz if q.get("published")]}
items = sum(len(m.get("items") or []) for m in mods)
print(f"modules {len(mods)}, module items {items}, pages {len(pages)}, files {len(files)}, "
      f"discussions {len(disc)}, assignments {len(assign)}, quizzes {len(quiz)}")
for k, v in pub.items():
    print(f"published {k}: {len(v)}", v[:12])
Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
json.dump({"modules": mods, "pages": pages,
           "files": [{k: f.get(k) for k in ("id", "display_name", "folder_id", "locked", "hidden", "size")}
                     for f in files],
           "discussions": disc, "assignments": assign, "quizzes": quiz, "published": pub},
          open(sys.argv[1], "w"), indent=1, default=str)
