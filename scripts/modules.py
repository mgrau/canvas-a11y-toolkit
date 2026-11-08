#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "beautifulsoup4", "pyyaml"]
# ///
"""Build the course's modules from modules.yaml in the workspace.

    ./scripts/modules.py --dry-run     # always look first
    ./scripts/modules.py --yes

modules.yaml lists the modules in order, and each module's items in order
(templates/modules.yaml is a commented example). Item kinds:

    - page: "Lab 1 Guide"             # a page already on Canvas, by title
      html: guides/lab_1/lab_1.html   #   optional: the rendered source, so a
                                      #   long page brings its parts along
    - manual: manuals/hall/hall.qmd   # a converted manual: its page (and
                                      #   parts) once pushed. With
      pdf_until_pushed: true          #   this, its source PDF until then
    - file: handouts/data.xlsx        # uploaded locked
    - link: "Smith (2014), Am. J. Phys."
      url: https://doi.org/10.1119/1.4901236   # DOIs go through the library
                                      #   proxy in course.toml, if one is set
    - header: "Manuals and references"
    - discussion: "Introduce Yourself"

A module may also have `retire: ["Old Instructions.pdf", ...]`: item titles
to take out of the module, for the PDFs a converted page replaces. With
--delete-files the retired files are deleted from course files too (the
originals stay in source/).

Re-running only adds what is missing, at its place in the list. It never
reorders, renames or publishes, and deletes only what `retire` names. A page
that is not on Canvas yet is skipped with a note, so push pages first.
Modules are created unpublished.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from canvas import _fix_table_a11y, _fix_text_a11y, extract_body, upload_draft  # noqa: E402
from canvas_api import Canvas, CanvasError, confirm  # noqa: E402


def part_titles(html: Path, title: str, named: bool = False) -> list[str]:
    """The pages `canvas.py push page` makes of a rendered page: just
    `title`, or its parts when it is long (scripts/page_parts.py)."""
    if not html.exists():
        return [title]
    from page_parts import titles

    # The same body prepare_html pushes: table captions add words, and one
    # caption more or less can change the number of parts.
    main = extract_body(html.read_text())
    _fix_table_a11y(main)
    _fix_text_a11y(main)
    return titles(main.decode_contents(), title, named)


def front_matter(qmd: Path) -> dict:
    text = qmd.read_text()
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def library_link(url: str, prefix: str) -> str:
    if prefix and url.startswith("https://doi.org/") and not url.startswith(prefix):
        return prefix + url
    return url


def plan(module: dict, root: Path, pages: dict[str, str], cfg) -> list[tuple]:
    """(kind, title, ref, indent) for every item the module should hold now."""
    out: list[tuple] = []
    for item in module.get("items", []):
        indent = int(item.get("indent", 0 if "header" in item else 1))
        if "header" in item:
            out.append(("SubHeader", item["header"], None, 0))
        elif "page" in item:
            html = root / item["html"] if item.get("html") else None
            titles = (part_titles(html, item["page"], bool(item.get("named")))
                      if html else [item["page"]])
            for t in titles:
                if t in pages:
                    out.append(("Page", t, pages[t], indent))
                else:
                    print(f"    (not on Canvas yet, skipped: page {t!r})")
        elif "manual" in item:
            qmd = root / item["manual"]
            meta = front_matter(qmd)
            title = meta.get("canvas-title") or meta.get("title") or qmd.stem
            titles = part_titles(qmd.with_suffix(".html"), title, named=True)
            if all(t in pages for t in titles):
                out += [("Page", t, pages[t], indent) for t in titles]
            elif meta.get("source-pdf") and item.get("pdf_until_pushed", False):
                pdf = root / meta["source-pdf"]
                out.append(("File", item.get("title", title), pdf, indent))
            else:
                print(f"    (manual not pushed yet, skipped: {title!r})")
        elif "file" in item:
            path = root / item["file"]
            if not path.exists():
                raise SystemExit(f"modules.yaml: no file {path}")
            out.append(("File", item.get("title", path.name), path, indent))
        elif "link" in item:
            out.append(("ExternalUrl", item["link"],
                        library_link(item["url"], cfg.proxy_prefix), indent))
        elif "discussion" in item:
            out.append(("Discussion", item["discussion"], None, indent))
        else:
            raise SystemExit(f"modules.yaml: unknown item {item!r}")
    return out


def ensure(canvas: Canvas, name: str, items: list[tuple], retire: list[str],
           folder: str, dry: bool, delete_files: bool) -> None:
    module = next((m for m in canvas.modules() if m["name"] == name), None)
    existing = canvas.module_items(module["id"]) if module else []
    base = f"courses/{canvas.course_id}/modules/{module['id']}/items" if module else ""

    for it in existing:
        if it["title"] in retire:
            print(f"    retire      {it['title']}")
            if not dry:
                canvas.request("DELETE", f"{base}/{it['id']}")
                if delete_files and it["type"] == "File":
                    canvas.request("DELETE", f"files/{it['content_id']}")
    have = {it["title"]: it for it in existing if it["title"] not in retire}
    # A link already in the module keeps its place but follows a changed URL.
    for kind, title, ref, _ in items:
        it = have.get(title)
        if kind == "ExternalUrl" and it and it.get("external_url") != ref:
            print(f"    relink      {title}")
            if not dry:
                canvas.put(f"{base}/{it['id']}", data={"module_item[external_url]": ref})
    todo = [i for i in items if i[1] not in have]
    print(f"{'new ' if module is None else ''}module {name}: {len(todo)} item(s) to add")
    for kind, title, *_ in todo:
        print(f"    {kind:11} {title}")
    if dry or (not todo and module):
        return
    if module is None:
        module = canvas.upsert_module(name)
        if module.get("published"):
            raise SystemExit(f"{name} came back published; stopping. Unpublish it in Canvas.")
        base = f"courses/{canvas.course_id}/modules/{module['id']}/items"
    order = [i[1] for i in items]

    def position(title: str) -> int:
        """Right after the planned item before it, so an item added later
        (a page split into more parts) lands next to its siblings."""
        now = {i["title"]: i["position"] for i in canvas.module_items(module["id"])}
        before = [t for t in order[:order.index(title)] if t in now]
        return now[before[-1]] + 1 if before else 1

    discussions = None
    for kind, title, ref, indent in todo:
        data = {"module_item[type]": kind, "module_item[title]": title,
                "module_item[indent]": indent,
                "module_item[position]": position(title)}
        if kind == "Page":
            data["module_item[page_url]"] = ref
        elif kind == "ExternalUrl":
            data["module_item[external_url]"] = ref
            data["module_item[new_tab]"] = "true"
        elif kind == "File":
            f = upload_draft(canvas, ref, folder)
            data["module_item[content_id]"] = f["id"]
        elif kind == "Discussion":
            if discussions is None:
                discussions = {d["title"]: d["id"] for d in canvas.discussions()}
            if title not in discussions:
                print(f"    (no discussion {title!r} on Canvas yet, skipped)")
                continue
            data["module_item[content_id]"] = discussions[title]
        canvas.post(base, data=data)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--delete-files", action="store_true",
                    help="also delete retired File items from course files")
    ap.add_argument("--only", help="build just the module with this name")
    args = ap.parse_args()

    cfg = config.settings()
    spec_path = cfg.root / "modules.yaml"
    if not spec_path.exists():
        raise SystemExit(f"no {spec_path}: copy templates/modules.yaml and fill it in")
    spec = yaml.safe_load(spec_path.read_text()) or {}
    canvas = Canvas.from_env()
    pages = {p["title"]: p["url"] for p in canvas.pages()}
    modules = [m for m in spec.get("modules", []) if not args.only or m["name"] == args.only]
    if args.only and not modules:
        raise SystemExit(f"no module {args.only!r} in modules.yaml")
    if not args.dry_run and not confirm(
            f"Add missing items to {len(modules)} module(s) in course {canvas.course_id}?",
            args.yes):
        print("cancelled")
        return 1
    try:
        for m in modules:
            items = plan(m, cfg.root, pages, cfg)
            folder = "course files/" + m.get("folder", m["name"].lower().replace(" ", "-")
                                              .replace(":", "").replace("/", "-"))
            ensure(canvas, m["name"], items, m.get("retire", []), folder,
                   args.dry_run, args.delete_files)
    except CanvasError as e:
        print(f"\nCanvas error: {e}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
