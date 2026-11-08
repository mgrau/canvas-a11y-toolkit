#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Plots for benchmark runs scored by bench/score.py.

    bench/plot.py <run-dir>                 # one run: progress, activity, accuracy
    bench/plot.py --compare <run-dir>...    # several runs side by side

Writes PNGs into each run dir (or, with --compare, into the first one's
parent as compare-*.png).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Reference palette (dataviz skill, light mode): fixed categorical order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GOOD, CRITICAL, NEUTRAL = "#0ca30c", "#d03b3b", "#c3c2b7"
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e6e5e0"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "lines.linewidth": 2,
})


def label(m: dict) -> str:
    r = m["run"]
    return f"{r['model']} ({r.get('effort', '')})"


def progress(m: dict, out: Path) -> None:
    """Cumulative cost and output tokens against wall-clock hours: two
    panels, one measure each (no second y-axis)."""
    tl = [x for x in m["process"]["_timeline"] if x["t"] is not None]
    if not tl:
        return
    hours = [x["t"] / 3600 for x in tl]
    cost, out_tok, read_tok = [], [], []
    c = o = r = 0.0
    for x in tl:
        c += x["cost"]; o += x["out"]; r += x["read"]
        cost.append(c); out_tok.append(o / 1e3); read_tok.append(r / 1e6)
    fig, axes = plt.subplots(3, 1, figsize=(8, 7.5), sharex=True)
    for ax, y, title, unit in [
        (axes[0], cost, "Cumulative cost", "US dollars (API list price)"),
        (axes[1], out_tok, "Cumulative output tokens", "thousands"),
        (axes[2], read_tok, "Cumulative cache-read tokens", "millions"),
    ]:
        ax.plot(hours, y, color=SERIES[0])
        ax.set_title(title)
        ax.set_ylabel(unit)
        ax.annotate(f"{y[-1]:,.1f}" if y[-1] < 100 else f"{y[-1]:,.0f}", (hours[-1], y[-1]),
                    textcoords="offset points", xytext=(4, 0), va="center", color=INK)
    axes[-1].set_xlabel("hours since start")
    fig.suptitle(f"Progress — {label(m)}", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "progress.png", dpi=150)
    plt.close(fig)


def kind_of(t: dict) -> str:
    c = t["cmd"]
    if t["name"] == "Bash":
        if "canvas.py" in c and "push" in c:
            return "push to Canvas"
        if "modules.py" in c:
            return "build modules"
        if "pdf2qmd.py" in c and "--check" in c:
            return "gate checks"
        if "pdf2qmd.py" in c or "quarto render" in c:
            return "convert / render"
        if "a11y_check" in c:
            return "gate checks"
        if any(k in c for k in ("pdftotext", "pdfimages", "pdfinfo")):
            return "read PDFs"
        return "other shell"
    if t["name"] in ("Edit", "Write", "MultiEdit"):
        return "edit files"
    if t["name"] in ("Read", "Grep", "Glob"):
        return "read files"
    if t["name"] == "Agent":
        return "start subagent"
    return "other"


ORDER = ["read PDFs", "read files", "convert / render", "edit files", "gate checks",
         "push to Canvas", "build modules", "start subagent", "other shell", "other"]


def activity(m: dict, out: Path) -> None:
    """What the agent was doing over time: one dot per tool call."""
    tools = [t for t in m["process"]["_tools"] if t["t"] is not None]
    if not tools:
        return
    present = [k for k in ORDER if any(kind_of(t) == k for t in tools)]
    fig, ax = plt.subplots(figsize=(9, 0.45 * len(present) + 1.6))
    for i, k in enumerate(present):
        ts = [t["t"] / 3600 for t in tools if kind_of(t) == k]
        errs = [t["t"] / 3600 for t in tools if kind_of(t) == k and t["error"]]
        ax.scatter(ts, [i] * len(ts), s=14, color=SERIES[i % len(SERIES)], linewidths=0)
        if errs:
            ax.scatter(errs, [i] * len(errs), s=40, facecolors="none", edgecolors=CRITICAL,
                       linewidths=1, label="tool error" if i == 0 or not ax.get_legend() else None)
        ax.text(1.005, i, f"{len(ts)}", transform=ax.get_yaxis_transform(), va="center", color=INK2)
    ax.set_yticks(range(len(present)), present)
    ax.invert_yaxis()
    ax.set_xlabel("hours since start")
    ax.set_title(f"Activity: one dot per tool call, circled = error\n{label(m)}")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out / "activity.png", dpi=150)
    plt.close(fig)


def accuracy(m: dict, out: Path) -> None:
    """Per-document recall of the reference text, colored by gate result."""
    docs = m["quality"]["docs"]
    for kind in ("guide", "manual"):
        ds = sorted((d for d in docs if d["kind"] == kind),
                    key=lambda d: (d.get("recall", -1)), reverse=True)
        if not ds:
            continue
        fig, ax = plt.subplots(figsize=(8, 0.26 * len(ds) + 1.4))
        y = range(len(ds))
        vals = [d.get("recall", 0) if d["done"] else 0 for d in ds]
        cols = [NEUTRAL if not d["done"] else (GOOD if d.get("gate") else CRITICAL) for d in ds]
        ax.barh(list(y), vals, color=cols, height=0.7)
        for i, d in enumerate(ds):
            txt = "not done" if not d["done"] else f"{d['recall']:.2f}"
            ax.text(vals[i] + 0.01, i, txt, va="center", fontsize=8, color=INK2)
        ax.set_yticks(list(y), [d["ref"] for d in ds], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, 1.1)
        ax.set_xlabel("recall: share of the reference conversion's words present")
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(color=GOOD, label="passes the gate"),
                           Patch(color=CRITICAL, label="fails the gate"),
                           Patch(color=NEUTRAL, label="not converted")],
                  loc="lower right", frameon=False, fontsize=8)
        ax.set_title(f"{kind.title()}s vs reference\n{label(m)}")
        ax.grid(axis="y", visible=False)
        fig.tight_layout()
        fig.savefig(out / f"accuracy-{kind}s.png", dpi=150)
        plt.close(fig)


def compare(ms: list[dict], out: Path) -> None:
    """Small multiples: one panel per measure, one bar per run."""
    def get(m, path):
        x = m
        for k in path:
            x = x.get(k, {}) if isinstance(x, dict) else {}
        return x if isinstance(x, (int, float)) else 0
    panels = [
        ("Cost (US$)", lambda m: get(m, ["process", "cost_usd"])),
        ("Wall time (hours)", lambda m: get(m, ["process", "wall_s"]) / 3600),
        ("Guides done (of 12)", lambda m: get(m, ["quality", "guides", "done"])),
        ("Manuals done (of 48)", lambda m: get(m, ["quality", "manuals", "done"])),
        ("Gate passes (of 60)", lambda m: get(m, ["quality", "guides", "gate_pass"])
         + get(m, ["quality", "manuals", "gate_pass"])),
        ("Mean recall, manuals", lambda m: get(m, ["quality", "manuals", "mean_recall"])),
        ("Mean recall, guides", lambda m: get(m, ["quality", "guides", "mean_recall"])),
        ("Panorama mean score", lambda m: get(m, ["panorama", "mean"])),
    ]
    names = [label(m) for m in ms]
    fig, axes = plt.subplots(2, 4, figsize=(13, 6))
    for ax, (title, f) in zip(axes.flat, panels):
        vals = [f(m) for m in ms]
        ax.bar(range(len(ms)), vals, color=[SERIES[i % len(SERIES)] for i in range(len(ms))], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:,.2f}" if v < 10 else f"{v:,.0f}", ha="center", va="bottom", fontsize=9)
        ax.set_xticks(range(len(ms)), names, rotation=20, ha="right", fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out / "compare.png", dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--compare", action="store_true")
    args = ap.parse_args()
    ms = [json.loads((r / "metrics.json").read_text()) for r in args.runs]
    if args.compare:
        compare(ms, args.runs[0].parent)
        print(f"wrote {args.runs[0].parent / 'compare.png'}")
        return 0
    for r, m in zip(args.runs, ms):
        progress(m, r)
        activity(m, r)
        accuracy(m, r)
        print(f"wrote plots in {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
