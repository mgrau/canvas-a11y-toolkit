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
import matplotlib.ticker  # noqa: E402

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


def markers(m: dict, ax, label_them: bool = False) -> None:
    """Dashed lines where a segment ended (a usage-limit stop) and where the
    toolkit changed mid-run."""
    t = 0.0
    segs = m["process"].get("segments") or []
    for seg in segs[:-1]:
        t += seg["active_s"]
        ax.axvline(t / 3600, color=INK2, linestyle="--", linewidth=1)
        if label_them:
            ax.annotate("usage limit: paused, resumed", (t / 3600, 0.5), xycoords=("data", "axes fraction"),
                        xytext=(3, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    for ch in m.get("toolkit_changes") or []:
        if ch.get("t_active") is not None:
            x = ch["t_active"] / 3600
            ax.axvline(x, color=SERIES[3], linestyle=":", linewidth=1.5)
            if label_them:
                ax.annotate("toolkit fix", (x, 0.5), xycoords=("data", "axes fraction"),
                            xytext=(3, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)


def progress(m: dict, out: Path) -> None:
    """Cumulative cost and output tokens against wall-clock hours: two
    panels, one measure each (no second y-axis)."""
    tl = [x for x in m["process"]["_timeline"] if x["t"] is not None]
    if not tl:
        return
    hours = [x["t"] / 3600 for x in tl]

    def cum(key, scale, who=None):
        v, out = 0.0, []
        for x in tl:
            if who is None or x["sub"] == who:
                v += x[key]
            out.append(v / scale)
        return out

    fig, axes = plt.subplots(3, 1, figsize=(8, 7.5), sharex=True)
    for i, (ax, key, scale, title, unit) in enumerate([
        (axes[0], "cost", 1, "Cumulative cost", "US dollars (API list price)"),
        (axes[1], "out", 1e3, "Cumulative output tokens", "thousands"),
        (axes[2], "read", 1e6, "Cumulative cache-read tokens", "millions"),
    ]):
        for j, (who, name) in enumerate([(None, "total"), (True, "subagents"), (False, "main agent")]):
            y = cum(key, scale, who)
            ax.plot(hours, y, color=SERIES[j], linewidth=2 if who is None else 1.5,
                    label=name if i == 0 else None)
            if who is not True:  # subagents run close to the total: label total and main only
                ax.annotate(f"{y[-1]:,.1f}" if y[-1] < 100 else f"{y[-1]:,.0f}", (hours[-1], y[-1]),
                            textcoords="offset points", xytext=(4, 0), va="center", color=INK,
                            fontsize=8)
        ax.set_title(title)
        ax.set_ylabel(unit)
        markers(m, ax, label_them=(i == 0))
    axes[0].legend(loc="upper left", frameon=False, fontsize=8, bbox_to_anchor=(0, 0.85))
    axes[-1].set_xlabel("active hours since start (the pause for the usage limit cut out)")
    fig.suptitle(f"Progress — {label(m)}", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "progress.png", dpi=150)
    plt.close(fig)


def kind_of(t: dict) -> str:
    c = t["cmd"]
    if t["name"] == "Bash":
        if ("canvas.py" in c and "push" in c) or ("pdf2qmd.py" in c and "--push" in c):
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
    markers(m, ax)
    ax.set_xlabel("active hours since start")
    ax.set_title(f"Activity: one dot per tool call, circled = error\n{label(m)}")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out / "activity.png", dpi=150)
    plt.close(fig)


def accuracy(m: dict, out: Path) -> None:
    """Per document: share of the source PDF's words kept (bars, colored by
    the gate), and share of the reference conversion's words present (dots).
    The reference guides were expanded during review, so a guide's dot sits
    well left of its bar by design."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    docs = m["quality"]["docs"]
    for kind in ("guide", "manual"):
        ds = sorted((d for d in docs if d["kind"] == kind),
                    key=lambda d: (d.get("source_recall") or d.get("recall") or -1), reverse=True)
        if not ds:
            continue
        fig, ax = plt.subplots(figsize=(9, 0.26 * len(ds) + 1.6))
        y = list(range(len(ds)))
        bars = [(d.get("source_recall") or 0) if d["done"] else 0 for d in ds]
        cols = [NEUTRAL if not d["done"] else (GOOD if d.get("gate") else CRITICAL) for d in ds]
        ax.barh(y, bars, color=cols, height=0.7)
        dots = [(i, d["recall"]) for i, d in enumerate(ds) if d["done"]]
        ax.scatter([r for _, r in dots], [i for i, _ in dots], s=22, color=INK, zorder=3,
                   edgecolors=SURFACE, linewidths=1)
        for i, d in enumerate(ds):
            if not d["done"]:
                txt = "not converted"
            elif d.get("source_recall") is None:
                txt = f"scanned: no text layer · ref {d['recall']:.2f}"
            else:
                txt = f"{d['source_recall']:.2f} · ref {d['recall']:.2f}"
            ax.text(1.01, i, txt, va="center", fontsize=7, color=INK2,
                    transform=ax.get_yaxis_transform())
        ax.set_yticks(y, [d["ref"] for d in ds], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, 1.0)
        ax.set_xlabel("share of words kept")
        ax.legend(handles=[Patch(color=GOOD, label="source PDF's words kept; passes the gate"),
                           Patch(color=CRITICAL, label="... fails the gate"),
                           Line2D([], [], marker="o", linestyle="", color=INK,
                                  label="reference conversion's words present")],
                  loc="upper left", bbox_to_anchor=(0, -0.9 / (0.26 * len(ds) + 1.6) - 0.02),
                  ncol=3, frameon=False, fontsize=7)
        ax.set_title(f"{kind.title()}s: words kept\n{label(m)}")
        ax.grid(axis="y", visible=False)
        fig.tight_layout()
        fig.savefig(out / f"accuracy-{kind}s.png", dpi=150, bbox_inches="tight")
        plt.close(fig)


def panorama(m: dict, out: Path) -> None:
    """Panorama's scores after a rescan, in bands: the run's own pages
    against what the course already held (imported PDFs, template pages)."""
    pa = m.get("panorama") or {}
    if "run_pages" not in pa:
        return
    bands = [("100", GOOD), ("90-99", SERIES[3]), ("50-89", SERIES[1]), ("under 50", CRITICAL)]
    groups = []
    for name, key in [("the run's pages", "run_pages"),
                      ("everything else\n(imported PDFs, templates)", "other")]:
        g = pa[key]
        groups.append((f"{name}\nmean {g['mean']:.1f}", [g["bands"][b] for b, _ in bands], g["items"]))
    fig, ax = plt.subplots(figsize=(9, 2.8))
    for i, (name, counts, n) in enumerate(groups):
        left = 0
        for (band, col), c in zip(bands, counts):
            if c:
                share = c / n
                ax.barh(i, share, left=left, color=col, height=0.6, edgecolor=SURFACE, linewidth=2)
                if share > 0.025:
                    ax.text(left + share / 2, i, str(c), ha="center", va="center", fontsize=8,
                            color="white" if col in (GOOD, CRITICAL) else INK)
                left += share
    ax.set_yticks(range(len(groups)), [g[0] for g in groups], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.margins(x=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("share of items, by Panorama score (the numbers are item counts)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=b) for b, c in bands], ncol=4, frameon=False,
              fontsize=8, loc="upper left", bbox_to_anchor=(0, -0.3))
    ax.set_title(f"Panorama after a full rescan\n{label(m)}")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out / "panorama.png", dpi=150, bbox_inches="tight")
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
        ("Source words kept, manuals", lambda m: get(m, ["quality", "manuals", "mean_source_recall"])),
        ("Source words kept, guides", lambda m: get(m, ["quality", "guides", "mean_source_recall"])),
        ("Panorama mean, the run's pages", lambda m: get(m, ["panorama", "run_pages", "mean"])),
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
        panorama(m, r)
        print(f"wrote plots in {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
