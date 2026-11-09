#!/usr/bin/env python3
"""Copy Panorama's findings on a run's pages into the run's workspace.

    bench/yuja_watch.py <local workspace> <host>:<remote workspace> [--every 600] [--once]

For a benchmark whose agent works on another machine. The local workspace
has the course's course.toml and .env, so yuja.sh can read Panorama here.
Every interval it reads which pages the run has pushed (the remote
_notes/push-queue/), reads Panorama's scores (yuja.sh list) and, when one of
those pages is under 100, its issues (yuja.sh issues), and writes
_notes/yuja/summary.txt and issues.json into the remote workspace. Only the
run's pages are reported, not the imported content around them.

Read only, like yuja.sh: it never clicks Reprocess or changes Panorama.
Panorama's raw responses carry session tokens, so they stay in the local
workspace's _notes/yuja-watch/ and only the summary is copied.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def pushed_pages(host: str, ws: str) -> dict[str, str]:
    """Title -> when it was last pushed, for every page the run has pushed."""
    read = ("import glob, json\n"
            f"print(json.dumps([json.load(open(f)) for f in glob.glob('{ws}/_notes/push-queue/*.json')]))\n")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", host, "python3", "-"], input=read,
                       capture_output=True, text=True, timeout=60, check=True)
    items = json.loads(r.stdout)
    return {i["title"]: i.get("finished_at") or "" for i in items if i.get("pushes")}


def ours(name: str, titles: dict[str, str]) -> str | None:
    """The run's title a Panorama item belongs to (a page or one of its parts)."""
    for t in titles:
        if name == t or name.startswith(t + " (Part "):
            return t
    return None


def read_docs(dump: Path) -> list[dict]:
    docs = []
    for f in sorted(dump.glob("json-*.json")):
        j = json.loads(f.read_text())
        if "getPaginatedCourseDocuments" in j["url"]:
            docs += json.loads(j["body"]).get("documents", [])
    return docs


def yuja(mode: str, ws: Path, out: Path) -> bool:
    subprocess.run(["rm", "-rf", str(out)])
    r = subprocess.run([str(TOOLKIT / "scripts/yuja.sh"), mode, str(out)], cwd=ws,
                       capture_output=True, text=True, timeout=900)
    return r.returncode == 0


def cycle(ws: Path, host: str, rws: str) -> str:
    titles = pushed_pages(host, rws)
    if not titles:
        return "nothing pushed yet"
    base = ws / "_notes/yuja-watch"
    if not yuja("list", ws, base / "list"):
        return "yuja.sh list failed (kept the last summary)"
    docs = [d for d in read_docs(base / "list") if ours(d.get("displayName", ""), titles)]
    issues: dict[str, list] = {}
    if any(d.get("score", 100) < 100 and d.get("format") != "pdf" for d in docs):
        if yuja("issues", ws, base / "issues"):
            for p in json.loads((base / "issues/issues.json").read_text()):
                if ours(p["displayName"], titles):
                    issues[p["displayName"]] = p["issues"]
    lines = [f"Panorama, read {now()}. Scores for the pages this run pushed.",
             "A page scanned before its last push may already be fixed: check it with",
             "a11y_check.py before editing. Never use Reprocess.", ""]
    scanned = {ours(d["displayName"], titles) for d in docs}
    under = sorted((d for d in docs if d.get("score", 100) < 100), key=lambda d: d["score"])
    lines.append(f"{len(docs)} item(s) scanned, {len(under)} under 100. "
                 f"{len(titles) - len(scanned)} pushed page(s) not scanned yet.")
    for d in under:
        name = d["displayName"]
        stale = " (scanned before its last push)" if d.get("inserted", "") < titles[ours(name, titles)] else ""
        lines.append(f"\n{d['score']:>4}  {name}  scanned {d.get('inserted', '')[:16]}{stale}")
        by_type: dict[str, list] = {}
        for i in issues.get(name, []):
            by_type.setdefault(f"{i['issueTypeIdentifier']} [{i['severity']}]", []).append(i)
        for t, found in sorted(by_type.items()):
            sample = next((i["textElement"] for i in found if i.get("textElement")), "")
            lines.append(f"      {len(found):>3} x {t}: {sample[:100]!r}")
    waiting = sorted(set(titles) - scanned)
    if waiting:
        lines += ["", "Not scanned yet:"] + [f"  {t}" for t in waiting]
    summary = "\n".join(lines) + "\n"
    out = base / "summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.txt").write_text(summary)
    (out / "issues.json").write_text(json.dumps(issues, indent=1))
    subprocess.run(["ssh", "-o", "BatchMode=yes", host, f"mkdir -p {rws}/_notes/yuja"], check=True)
    subprocess.run(["scp", "-q", str(out / "summary.txt"), str(out / "issues.json"),
                    f"{host}:{rws}/_notes/yuja/"], check=True)
    return f"{len(docs)} scanned, {len(under)} under 100, {len(waiting)} waiting"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workspace", type=Path)
    ap.add_argument("remote", help="host:/path/to/remote/workspace")
    ap.add_argument("--every", type=float, default=600)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    host, rws = args.remote.split(":", 1)
    while True:
        try:
            print(f"{now()} {cycle(args.workspace.resolve(), host, rws)}", flush=True)
        except Exception as e:  # keep watching through a dropped connection
            print(f"{now()} error: {e}", flush=True)
        if args.once:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
