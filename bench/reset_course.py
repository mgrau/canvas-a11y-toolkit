#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Empty the benchmark course back to how it was before last year's import.

    bench/reset_course.py <course id> <cutoff>          # list what would go
    bench/reset_course.py <course id> <cutoff> --yes    # delete it

Run inside the course workspace. Deletes every module, quiz, assignment and
discussion, every page except the front page, and every file created at or
after <cutoff> (ISO time, UTC: when the instructor started the import, e.g.
2026-11-08T21:00:00Z). The instructor then imports the source course again,
so each benchmark run starts from the same Canvas. Folders stay: the API
client refuses to delete them (only course-scoped writes and files/<id>),
so a run's draft folders are left empty and locked, and the next run's
pushes reuse them.

The course id must match course.toml: a guard against wiping the wrong
course. Canvas keeps deleted items at /courses/<id>/undelete for a while.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from canvas_api import Canvas  # noqa: E402

if len(sys.argv) < 3:
    sys.exit(__doc__)
course, cutoff, yes = sys.argv[1], sys.argv[2], "--yes" in sys.argv
c = Canvas.from_env()
cid = c.course_id
if cid != course:
    sys.exit(f"refusing: course.toml names {cid}, not {course}")

modules = c.modules()
pages = [p for p in c.paginate(f"courses/{cid}/pages", per_page=100) if not p.get("front_page")]
quizzes = list(c.paginate(f"courses/{cid}/quizzes", per_page=100))
assignments = c.assignments()
discussions = c.discussions()
files = [f for f in c.paginate(f"courses/{cid}/files", per_page=100) if f["created_at"] >= cutoff]
front = [p["title"] for p in c.paginate(f"courses/{cid}/pages", per_page=100) if p.get("front_page")]
print(f"course {cid}: delete {len(modules)} modules, {len(pages)} pages (keeping front page {front}), "
      f"{len(quizzes)} quizzes, {len(assignments)} assignments, {len(discussions)} discussions, "
      f"{len(files)} files made since {cutoff}")
if not yes:
    print("dry run: nothing deleted (pass --yes)")
    raise SystemExit(0)


def delete(paths, what):
    with ThreadPoolExecutor(4) as pool:
        failed = [p for p, ok in zip(paths, pool.map(lambda p: _delete(p), paths)) if not ok]
    print(f"{what}: {len(paths) - len(failed)} deleted" + (f", {len(failed)} failed: {failed[:5]}" if failed else ""))


def _delete(path):
    try:
        c.request("DELETE", path)
        return True
    except Exception as e:
        return "404" in str(e)  # already gone


delete([f"courses/{cid}/modules/{m['id']}" for m in modules], "modules")
delete([f"courses/{cid}/quizzes/{q['id']}" for q in quizzes], "quizzes")
left = {a["id"] for a in c.assignments()}
delete([f"courses/{cid}/assignments/{a}" for a in left], "assignments")
delete([f"courses/{cid}/discussion_topics/{d['id']}" for d in c.discussions()], "discussions")
delete([f"courses/{cid}/pages/{p['url']}" for p in pages], "pages")
delete([f"files/{f['id']}" for f in files], "files")
print(f"left: {len(c.modules())} modules, "
      f"{len(list(c.paginate(f'courses/{cid}/pages', per_page=100)))} pages, "
      f"{len(list(c.paginate(f'courses/{cid}/files', per_page=100)))} files, "
      f"{len(c.assignments())} assignments, {len(c.discussions())} discussions")
