#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Helpers for yuja.sh.

    python3 scripts/yuja_table.py --launch   # "<course id> <one-time launch url>"
    python3 scripts/yuja_table.py <outdir>   # table of scores from a `list` dump
    python3 scripts/yuja_table.py --issues <outdir>   # replay getFileIssues (`issues`)
"""

import glob
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

def launch() -> None:
    """A one-time launch URL for Panorama, from course.toml [panorama] tool_id
    (find it with `canvas.py list tools`)."""
    import config
    from canvas_api import Canvas

    tool = config.settings().panorama_tool_id
    if not tool:
        sys.exit("set [panorama] tool_id in course.toml (canvas.py list tools shows it)")
    c = Canvas.from_env()
    url = c.get(f"courses/{c.course_id}/external_tools/sessionless_launch",
                id=tool, launch_type="course_navigation")["url"]
    print(c.course_id, url)


def table(outdir: str) -> None:
    docs = []  # one response per page of results
    for f in sorted(glob.glob(f"{outdir}/json-*.json")):
        j = json.load(open(f))
        if "getPaginatedCourseDocuments" in j["url"]:
            docs += json.loads(j["body"]).get("documents", [])
    for d in docs:
        print(f"{d.get('score')!s:>6}  {d.get('format', ''):<6} {d.get('displayName')}")
    print(len(docs), "items")


def issues(outdir: str) -> None:
    """Replay the captured getFileIssues request for each page and print
    its issues, grouped by type, with a sample of the text."""
    import urllib.request

    action = json.load(open(f"{outdir}/action.json"))
    if not isinstance(action, dict) or "pages" not in action:
        sys.exit(f"no pages in {outdir}/action.json: {action}")
    req = next((r for r in json.load(open(f"{outdir}/requests.json"))
                if "getFileIssues" in r["url"] and r.get("postData")), None)
    if req is None:
        sys.exit(f"no getFileIssues request captured (opening the report: {action.get('view')})")
    headers = {k: v for k, v in req["headers"].items() if not k.startswith(":")}
    counts: dict[str, int] = {}
    results = []
    for p in action["pages"]:
        body = json.loads(req["postData"])
        body["documentId"] = p["documentId"]
        r = urllib.request.Request(req["url"], data=json.dumps(body).encode(),
                                   headers=headers, method="POST")
        found = json.load(urllib.request.urlopen(r, timeout=60)).get("issuesJSON", [])
        results.append({**p, "issues": found})
        print(f"{p['score']:>4}  {p['displayName']}  (scanned {p['inserted'][:16]})")
        by_type: dict[str, list] = {}
        for i in found:
            by_type.setdefault(f"{i['issueTypeIdentifier']} [{i['severity']}]", []).append(i)
        for t, items in sorted(by_type.items()):
            counts[t] = counts.get(t, 0) + len(items)
            sample = next((i["textElement"] for i in items if i.get("textElement")), "") \
                or items[0].get("elementSelector", json.dumps(items[0]))[-70:]
            print(f"        {len(items):>3} x {t}: {sample[:80]!r}")
    json.dump(results, open(f"{outdir}/issues.json", "w"), indent=1)
    print("\nall pages:")
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {t}")
    print(f"\nfull list: {outdir}/issues.json")


if __name__ == "__main__":
    if sys.argv[1] == "--launch":
        launch()
    elif sys.argv[1] == "--issues":
        issues(sys.argv[2])
    else:
        table(sys.argv[1])
