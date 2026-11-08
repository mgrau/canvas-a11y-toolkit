#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Make a course workspace for the toolkit.

    ./scripts/new_course.py ~/teaching/phys101/spring2027 \\
        --canvas-url https://canvas.example.edu --course-id 123456 \\
        --source 98765 --name "PHYS 101 Spring 2027"

Creates the folder (or fills in an existing one without overwriting any
file) with:

    course.toml       settings (edit it: Panorama tool id, library proxy)
    .env              CANVAS_TOKEN= (fill in; gitignored)
    .gitignore        keeps secrets, source/, manuals/ and _notes/ out of git
    _quarto.yml       Quarto project with the toolkit's filters
    tools -> <toolkit>/quarto        the filters, linked, not copied
    _assets/handout.tex              PDF template for guides
    modules.yaml      example module list for scripts/modules.py
    AGENTS.md         points an agent at the toolkit's AGENTS.md
    guides/ manuals/ canvas/ source/ _notes/

and runs `git init` if the folder is not already in a repository.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parent.parent
T = TOOLKIT / "templates"

WORKSPACE_AGENTS = """# @NAME@ — course workspace

This folder is a course workspace for the Canvas accessibility toolkit at
`@TOOLKIT@`.

**Before doing anything, read `@TOOLKIT@/AGENTS.md`.** It has the rules
(never publish, never write to a source course, keep copyrighted material
out of git) and the step-by-step skills.

Run the toolkit's scripts from inside this folder:

    @TOOLKIT@/scripts/canvas.py whoami

## Course notes

Decisions and facts specific to this course go here (the instructor's
choices, what has been converted, what is left). Keep it current.
"""


def write(path: Path, text: str) -> None:
    if path.exists():
        print(f"  keep   {path.name} (exists)")
        return
    path.write_text(text)
    print(f"  write  {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--canvas-url", default="https://canvas.example.edu")
    ap.add_argument("--course-id", default="0")
    ap.add_argument("--source", action="append", default=[],
                    help="a source course id to export from (read only); repeatable")
    ap.add_argument("--name", help="course name for messages")
    ap.add_argument("--proxy", default="", help="library EZproxy prefix for DOI links")
    args = ap.parse_args()

    ws = args.folder.expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)
    print(f"Workspace {ws}")
    name = args.name or ws.name
    host = args.canvas_url.split("//")[-1].rstrip("/")

    toml = (T / "course.toml").read_text()
    toml = (toml.replace('name = "PHYS 101 Spring 2027"', f'name = "{name}"')
                .replace('canvas_url = "https://canvas.example.edu"',
                         f'canvas_url = "{args.canvas_url.rstrip("/")}"')
                .replace("course_id = 0", f"course_id = {args.course_id}")
                .replace("source_course_ids = []",
                         f"source_course_ids = [{', '.join(args.source)}]")
                .replace('own_hosts = ["canvas.example.edu"]', f'own_hosts = ["{host}"]'))
    if args.proxy:
        toml = toml.replace('proxy_prefix = ""', f'proxy_prefix = "{args.proxy}"', 1)
    write(ws / "course.toml", toml)
    write(ws / ".env", (T / "env.example").read_text())
    write(ws / ".env.example", (T / "env.example").read_text())
    write(ws / ".gitignore", (T / "gitignore").read_text())
    write(ws / "_quarto.yml", (T / "_quarto.yml").read_text().replace("@PROXY@", args.proxy))
    write(ws / "modules.yaml", (T / "modules.yaml").read_text())
    write(ws / "AGENTS.md", WORKSPACE_AGENTS.replace("@NAME@", name)
          .replace("@TOOLKIT@", str(TOOLKIT)))
    for alias in ("CLAUDE.md", "QWEN.md"):
        if not (ws / alias).exists():
            (ws / alias).symlink_to("AGENTS.md")
            print(f"  link   {alias} -> AGENTS.md")
    (ws / "_assets").mkdir(exist_ok=True)
    if not (ws / "_assets" / "handout.tex").exists():
        shutil.copy(T / "handout.tex", ws / "_assets" / "handout.tex")
        print("  write  _assets/handout.tex")
    if not (ws / "tools").exists():
        (ws / "tools").symlink_to(os.path.relpath(TOOLKIT / "quarto", ws))
        print("  link   tools -> toolkit quarto/")
    for d in ("guides", "manuals", "canvas", "source", "_notes"):
        (ws / d).mkdir(exist_ok=True)
    inside = subprocess.run(["git", "-C", str(ws), "rev-parse"], capture_output=True)
    if inside.returncode:
        subprocess.run(["git", "init", "-q", str(ws)])
        print("  git init")
    print("\nNext: put the Canvas token in .env, check course.toml, then\n"
          f"  cd {ws} && {TOOLKIT}/scripts/canvas.py whoami")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
