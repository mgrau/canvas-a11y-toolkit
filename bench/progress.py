#!/usr/bin/env python3
"""Live progress of a benchmark run, from its events.jsonl and workspace.

    bench/progress.py <run-dir>              # one line of text
    bench/progress.py --latest <runs-dir>    # the newest run in a folder
    bench/progress.py --json ...             # for the progress band mod

Standard library only, so the system python3 runs it. Mid-run, the stream
records each message's output tokens as of the first streamed block, so
output (and so cost) is estimated from the text written; score.py takes
the exact totals from the final result event.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PRICES = {  # $ per million tokens, as in score.py
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "w5m": 2.5, "w1h": 4.0, "read": 0.2},
    "claude-opus-5-5": {"in": 5.0, "out": 25.0, "w5m": 6.25, "w1h": 10.0, "read": 0.5},
}
# Share of the bar each stage is worth.
WEIGHTS = {"triage": 5, "drafts": 50, "pushed": 30, "modules": 5, "checks": 5, "review": 5}
PUSHED = re.compile(r"^(?:Create|Update) page '(.+?)' \(", re.M)
STALL_S = 600


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def segments(run: Path) -> list[Path]:
    """events.jsonl, then events.2.jsonl, events.3.jsonl... (resumed runs)."""
    more = sorted(run.glob("events.*.jsonl"), key=lambda p: int(p.name.split(".")[1]))
    return [p for p in [run / "events.jsonl", *more] if p.exists()]


def events(run: Path) -> dict:
    msgs: dict[str, dict] = {}
    tools: dict[str, dict] = {}
    pushed: set[str] = set()
    out = {"result": None, "limit": None, "last_t": None, "subagents": set()}
    out["segments"] = []  # (first, last) event time of each segment
    out["results"] = []  # each segment's result event, if it got one
    lines = []
    for path in segments(run):
        seg = [l for l in path.read_text(errors="replace").splitlines() if l.strip()]
        lines += [None] + seg  # None marks a segment start
    for line in lines:
        if line is None:
            out["segments"].append([None, None])
            out["results"].append(None)
            out["limit"] = None  # a new segment starts with a fresh limit reading
            out["result"] = None  # only the last segment's result counts
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue  # a line still being written
        kind = e.get("type")
        if e.get("timestamp"):
            out["last_t"] = ts(e["timestamp"])
            seg = out["segments"][-1]
            seg[0] = seg[0] or out["last_t"]
            seg[1] = out["last_t"]
        if kind == "assistant":
            m = e["message"]
            rec = msgs.setdefault(m["id"], {"model": m.get("model"), "usage": m.get("usage") or {},
                                            "chars": 0, "seg": len(out["segments"]) - 1})
            if e.get("parent_tool_use_id"):
                out["subagents"].add(e["parent_tool_use_id"])
            for c in m.get("content", []):
                rec["chars"] += len(c.get("text") or c.get("thinking") or "")
                if c.get("type") == "tool_use":
                    rec["chars"] += len(json.dumps(c.get("input")))
                    i = c.get("input") or {}
                    what = i.get("command") or i.get("file_path") or i.get("prompt") or ""
                    label = i.get("description") or i.get("file_path") or what
                    tools[c["id"]] = {"name": c["name"], "what": what, "label": label,
                                      "t": out["last_t"], "ok": None}
        elif kind == "user":
            for c in (e.get("message", {}).get("content") or []):
                if not (isinstance(c, dict) and c.get("type") == "tool_result"):
                    continue
                t = tools.get(c.get("tool_use_id"))
                if t is None:
                    continue
                content = c.get("content")
                text = content if isinstance(content, str) else " ".join(
                    x.get("text", "") for x in (content or []) if isinstance(x, dict))
                t["ok"] = not c.get("is_error")
                cmd = t["what"]
                if t["name"] == "Bash" and "canvas.py" in cmd and "--yes" in cmd and "--dry-run" not in cmd:
                    pushed.update(PUSHED.findall(text))
                if t["name"] == "Bash" and "modules.py" in cmd and "--yes" in cmd and t["ok"]:
                    out["modules"] = True
                if t["name"] == "Bash" and "a11y_check" in cmd and t["ok"]:
                    out["checks_t"] = t["t"]
        elif kind == "rate_limit_event":
            out["limit"] = e.get("rate_limit_info")
        elif kind == "result":
            out["result"] = out["results"][-1] = e
    return {**out, "msgs": msgs, "tools": tools, "pushed": pushed}


def cost(msgs: dict) -> tuple[float, int]:
    usd, out_tok = 0.0, 0
    for m in msgs.values():
        p = PRICES.get(m["model"] or "", {})
        u = m["usage"]
        cc = u.get("cache_creation") or {}
        est_out = max(u.get("output_tokens", 0), m["chars"] // 4)
        out_tok += est_out
        usd += (u.get("input_tokens", 0) * p.get("in", 0) + est_out * p.get("out", 0)
                + u.get("cache_read_input_tokens", 0) * p.get("read", 0)
                + cc.get("ephemeral_5m_input_tokens", 0) * p.get("w5m", 0)
                + cc.get("ephemeral_1h_input_tokens", u.get("cache_creation_input_tokens", 0))
                * p.get("w1h", 0)) / 1e6
    return usd, out_tok


def canvas_pushed(run: Path, ws: Path, since: float) -> int | None:
    """Pages in the course changed since the run started, read from Canvas
    at most once a minute (cached in the run dir). None if unreachable."""
    cache = run / ".pushed_cache.json"
    try:
        c = json.loads(cache.read_text())
        if time.time() - c["t"] < 60:
            return c["n"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        toml = (ws / "course.toml").read_text()
        url = re.search(r'^canvas_url\s*=\s*"([^"]+)"', toml, re.M).group(1).rstrip("/")
        cid = re.search(r'^course_id\s*=\s*"?(\d+)', toml, re.M).group(1)
        token = re.search(r"^CANVAS_TOKEN\s*=\s*['\"]?([^'\"\s]+)", (ws / ".env").read_text(), re.M).group(1)
        n, nxt = 0, f"{url}/api/v1/courses/{cid}/pages?sort=updated_at&order=desc&per_page=100"
        while nxt:
            req = urllib.request.Request(nxt, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                pages = json.load(r)
                m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
            fresh = [x for x in pages if ts(x["updated_at"]) >= since]
            n += len(fresh)
            nxt = m.group(1) if m and len(fresh) == len(pages) else None
    except Exception:
        return None
    cache.write_text(json.dumps({"t": time.time(), "n": n}))
    return n


def workspace(ws: Path) -> dict:
    total = decided = rows = 0
    tri = ws / "triage.csv"
    if tri.exists():
        with open(tri, newline="") as fh:
            for r in csv.DictReader(fh):
                rows += 1
                d = (r.get("decision") or "").strip()
                decided += bool(d)
                total += d in ("guide", "manual")
    drafts = sum(1 for d in ("guides", "manuals") for p in (ws / d).glob("*/*.qmd")
                 if p.stem == p.parent.name)
    return {"rows": rows, "decided": decided, "total": total, "drafts": drafts,
            "review": (ws / "REVIEW.md").exists()}


def progress(run: Path) -> dict:
    info = json.loads((run / "run.json").read_text())
    ev = events(run)
    w = workspace(Path(info["workspace"]))
    # A result event only means the model paused (it may be waiting on a
    # background job or a wakeup); the run is over when the script exits.
    finished = (run / "exit_code").exists()
    now = time.time()
    # Active time: each segment from its first event to its last, the
    # running one to now. Gaps between segments (waiting out a usage
    # limit) don't count.
    segs = ev["segments"]
    active = sum(b - a for a, b in segs[:-1] if a)
    if segs and segs[-1][0]:
        active += (segs[-1][1] if finished else now) - segs[-1][0]
    total = w["total"] or None
    on_canvas = canvas_pushed(run, Path(info["workspace"]), ts(info["start"]))
    pushed = on_canvas if on_canvas is not None else len(ev["pushed"])
    frac = {
        "triage": 1.0 if w["rows"] and w["decided"] == w["rows"] else 0.0,
        "drafts": min(1.0, w["drafts"] / total) if total else 0.0,
        "pushed": min(1.0, pushed / total) if total else 0.0,
        "modules": 1.0 if ev.get("modules") else 0.0,
        "checks": 1.0 if ev.get("checks_t") and pushed and ev["checks_t"] >= max(
            (t["t"] or 0) for t in ev["tools"].values() if "canvas.py" in t["what"]) else 0.0,
        "review": 1.0 if w["review"] else 0.0,
    }
    pct = sum(WEIGHTS[k] * frac[k] for k in WEIGHTS)
    stage = next((k for k in WEIGHTS if frac[k] < 1), "done")
    # A resumed session's result reports the session's running total, so
    # the cost is the last result's total plus estimates for the segments
    # after it.
    usd, out_tok = 0.0, 0
    for i, r in enumerate(ev["results"]):
        est, o = cost({k: m for k, m in ev["msgs"].items() if m["seg"] == i})
        usd = r["total_cost_usd"] if r and "total_cost_usd" in r else usd + est
        out_tok += o
    last = max((t for t in ev["tools"].values() if t["t"]), key=lambda t: t["t"], default=None)
    lim = ev["limit"] or {}
    windows = lim.get("unifiedWindows") or {}
    idle = now - ev["last_t"] if ev["last_t"] else None
    if finished:
        r = ev["result"] or {}
        state = "finished" if r.get("subtype") == "success" and not r.get("is_error") else \
            "stopped: usage limit" if "limit" in str(r.get("result", "")) else "stopped"
    elif lim.get("status") not in (None, "allowed", "allowed_warning"):
        state = "rate limited"
    elif last and last["name"] == "ScheduleWakeup" and idle is not None and idle > 60:
        state = "waiting: wakeup set"
    elif idle is not None and idle > STALL_S:
        state = "stalled"
    else:
        state = "running"
    return {
        "model": info.get("model"), "effort": info.get("effort"), "run": run.name,
        "state": state, "pct": round(pct, 1), "stage": stage,
        "elapsed_s": round(active), "segments": len(segs), "idle_s": round(idle) if idle is not None else None,
        "triage": {"rows": w["rows"], "decided": w["decided"]},
        "total": w["total"], "drafts": w["drafts"], "pushed": pushed,
        "modules": bool(ev.get("modules")), "review": w["review"],
        "cost_usd": round(usd, 2), "cost_exact": all(ev["results"]),
        "output_tokens": out_tok, "messages": len(ev["msgs"]), "tool_calls": len(ev["tools"]),
        "tool_errors": sum(t["ok"] is False for t in ev["tools"].values()),
        "subagents": len(ev["subagents"]),
        "limit_5h": (windows.get("five_hour") or {}).get("utilization"),
        "limit_7d": (windows.get("seven_day") or {}).get("utilization"),
        "last_tool": {"name": last["name"], "what": (last["label"].splitlines() or [""])[0][:120],
                      "ago_s": round(now - last["t"])} if last else None,
    }


def hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def text(p: dict, width: int = 30) -> str:
    fill = round(width * p["pct"] / 100)
    bar = "█" * fill + "░" * (width - fill)
    tot = p["total"] or "?"
    lim = f" · 5h limit {p['limit_5h']:.0%}" if p["limit_5h"] is not None else ""
    return (f"{p['model']} ({p['effort']}) {p['state']}  {bar} {p['pct']:.0f}%  "
            f"drafts {p['drafts']}/{tot} · pushed {p['pushed']}/{tot} · {hms(p['elapsed_s'])} · "
            f"{'' if p['cost_exact'] else '≈'}${p['cost_usd']:.2f}{lim}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path, nargs="?")
    ap.add_argument("--latest", type=Path, help="pick the newest run in this folder")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    run = args.run
    if args.latest:
        runs = sorted((d for d in args.latest.iterdir() if (d / "run.json").exists()),
                      key=lambda d: (d / "run.json").stat().st_mtime)
        if not runs:
            print(json.dumps({"state": "none"}) if args.json else "no runs")
            return 1
        run = runs[-1]
    if run is None:
        ap.error("give a run dir or --latest <folder>")
    p = progress(run)
    print(json.dumps(p) if args.json else text(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
