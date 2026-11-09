#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Queue finished pages for Canvas; one worker checks and pushes them.

    $T/push_queue.py add manuals/<slug>/<slug>.qmd
    $T/push_queue.py add guides/<id>/<id>.qmd --title "<Title>"
    $T/push_queue.py status
    $T/push_queue.py run              # the worker (keeps going; --once to drain)

`add` only writes a note in _notes/push-queue/ and returns at once, so the
agent goes on to the next document instead of waiting on Canvas. The worker
takes one page at a time, oldest first. For each it runs the page's gate
again (pdf2qmd.py --check --render, with --diff for a manual, then
a11y_check.py --links on the HTML) and pushes only if both pass, unpublished,
with the same command push-to-canvas uses. A page whose source changed in
the last 30 seconds waits, in case it is still being edited. `status`
shows each page's state and the last line of its push; the full output is
in _notes/push-queue/<key>.log.

Add a page again after fixing it (a gate failure, a Panorama issue). A
re-push uploads only the images that changed (canvas.py upload_once).

Only one worker runs per workspace (a lock file). The worker never
publishes: it runs canvas.py, and canvas_api.py refuses publishing.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
QUEUE = Path("_notes/push-queue")
SETTLE_S = 30


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key_for(qmd: Path) -> str:
    """manuals/afm-manual/afm-manual.qmd -> manuals-afm-manual."""
    return f"{qmd.parts[0]}-{qmd.stem}"


def load(key: str) -> dict | None:
    try:
        return json.loads((QUEUE / f"{key}.json").read_text())
    except FileNotFoundError:
        return None


def save(item: dict) -> None:
    path = QUEUE / f"{item['key']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(item, indent=1))
    tmp.replace(path)


def log_event(**event) -> None:
    with open(QUEUE / "events.jsonl", "a") as f:
        f.write(json.dumps({"at": now(), **event}) + "\n")


def front_title(qmd: Path) -> str | None:
    head = qmd.read_text(encoding="utf-8").split("\n---", 1)[0]
    m = re.search(r'^canvas-title:\s*["\']?(.+?)["\']?\s*$', head, re.M)
    return m.group(1) if m else None


def cmd_add(args) -> int:
    if args.title and len(args.qmd) > 1:
        print("--title names one page: queue the others separately")
        return 2
    QUEUE.mkdir(parents=True, exist_ok=True)
    bad = 0
    for qmd in args.qmd:
        qmd = Path(qmd)
        if qmd.is_absolute():
            qmd = qmd.relative_to(Path.cwd())
        if qmd.suffix != ".qmd" or not qmd.exists() or qmd.parts[0] not in ("guides", "manuals"):
            print(f"not queued: {qmd} (give guides/<id>/<id>.qmd or manuals/<slug>/<slug>.qmd)")
            bad += 1
            continue
        title = args.title or front_title(qmd)
        if not title:
            print(f"not queued: {qmd} has no canvas-title; pass --title")
            bad += 1
            continue
        key = key_for(qmd)
        item = load(key) or {"key": key, "qmd": str(qmd), "pushes": 0}
        item.update(title=title, queued_at=now(), state="queued")
        save(item)
        log_event(key=key, state="queued")
        print(f"queued {qmd} as '{title}' (check: push_queue.py status)")
    return 1 if bad else 0


def cmd_status(args) -> int:
    items = sorted((json.loads(p.read_text()) for p in QUEUE.glob("*.json")),
                   key=lambda i: i.get("queued_at", ""))
    if not items:
        print("queue is empty")
        return 0
    for i in items:
        when = i.get("finished_at") or i.get("started_at") or i.get("queued_at")
        print(f"{i['state']:<8} {when}  {i['qmd']}")
        if i["state"] in ("failed", "pushed") and i.get("last"):
            print(f"         {i['last']}")
    counts = {s: sum(i["state"] == s for i in items) for s in ("queued", "pushing", "pushed", "failed")}
    print(", ".join(f"{n} {s}" for s, n in counts.items()))
    return 0


def step(cmd: list[str], log) -> tuple[int, str]:
    log.write(f"$ {' '.join(cmd)}\n")
    log.flush()
    r = subprocess.run(cmd, capture_output=True, text=True)
    log.write(r.stdout + r.stderr + f"[exit {r.returncode}]\n\n")
    log.flush()
    out = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, out[-1] if out else ""


def work(item: dict) -> None:
    qmd = Path(item["qmd"])
    item.update(state="pushing", started_at=now(), finished_at=None)
    save(item)
    log_event(key=item["key"], state="pushing")
    manual = qmd.parts[0] == "manuals"
    with open(QUEUE / f"{item['key']}.log", "w") as log:
        gate = [str(SCRIPTS / "pdf2qmd.py"), "--check", str(qmd), "--render"]
        code, last = step(gate + (["--diff"] if manual else []), log)
        if code == 0:
            code, last = step([str(SCRIPTS / "a11y_check.py"), "--links",
                               str(qmd.with_suffix(".html"))], log)
            last = f"a11y_check: {last}" if code else last
        else:
            last = f"gate: {last}"
        if code == 0:
            push = [str(SCRIPTS / "canvas.py"), "--yes", "push", "page",
                    str(qmd.with_suffix(".html")), "--title", item["title"]]
            code, last = step(push + (["--named-parts"] if manual else []), log)
    # Re-queued while this push ran: the source changed again, go round once more.
    fresh = load(item["key"]) or item
    requeued = fresh.get("queued_at", "") > item["started_at"]
    item.update(finished_at=now(), last=last[:300],
                state="queued" if requeued else ("pushed" if code == 0 else "failed"),
                queued_at=fresh.get("queued_at"))
    item["pushes"] = item.get("pushes", 0) + (code == 0)
    if code == 0 and not item.get("first_pushed_at"):
        item["first_pushed_at"] = item["finished_at"]
    save(item)
    log_event(key=item["key"], state="pushed" if code == 0 else "failed", last=last[:300])
    print(f"{now()} {'pushed' if code == 0 else 'FAILED'} {item['qmd']}: {last[:200]}", flush=True)


def next_item() -> dict | None:
    waiting = [json.loads(p.read_text()) for p in QUEUE.glob("*.json")]
    waiting = [i for i in waiting if i["state"] == "queued"]
    for i in sorted(waiting, key=lambda i: i["queued_at"]):
        qmd = Path(i["qmd"])
        if not qmd.exists():
            i.update(state="failed", last=f"{qmd} no longer exists")
            save(i)
        elif time.time() - qmd.stat().st_mtime >= SETTLE_S:
            return i
    return None


def cmd_run(args) -> int:
    QUEUE.mkdir(parents=True, exist_ok=True)
    lock = open(QUEUE / ".worker.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("a worker is already running for this workspace")
        return 1
    # A worker that died mid-push leaves "pushing": try those again.
    for p in QUEUE.glob("*.json"):
        i = json.loads(p.read_text())
        if i["state"] == "pushing":
            i["state"] = "queued"
            save(i)
    print(f"{now()} push worker started in {Path.cwd()}", flush=True)
    while True:
        item = next_item()
        if item:
            work(item)
            continue
        if args.once and not any(json.loads(p.read_text())["state"] == "queued"
                                 for p in QUEUE.glob("*.json")):
            return 0
        time.sleep(args.interval)


def main() -> int:
    if not Path("course.toml").exists():
        sys.exit("run this inside a course workspace (the folder with course.toml)")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="queue finished pages")
    a.add_argument("qmd", nargs="+")
    a.add_argument("--title", help="page title (default: canvas-title in the front matter)")
    sub.add_parser("status", help="each queued page's state")
    r = sub.add_parser("run", help="the worker: check and push queued pages")
    r.add_argument("--once", action="store_true", help="stop when the queue is empty")
    r.add_argument("--interval", type=float, default=15, help="seconds between looks")
    args = ap.parse_args()
    return {"add": cmd_add, "status": cmd_status, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
