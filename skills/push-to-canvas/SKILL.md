---
name: push-to-canvas
description: Push finished guides, manual pages and site pages to Canvas as unpublished drafts, then build the modules from modules.yaml. Use once a page passes its gate.
---

# Push pages and build modules

Everything goes up **unpublished**, and images are uploaded **locked**
into a folder that mirrors the source's folder (`guides/hall_effect/` ->
`course files/guides/hall-effect`). There is no publish option.

## Push a page

    quarto render guides/<id>/<id>.qmd
    $T/canvas.py --dry-run push page guides/<id>/<id>.html --title "<Title>"
    $T/canvas.py --yes push page guides/<id>/<id>.html --title "<Title>"

- Read the dry run's `accessibility:` lines. Any finding means: fix the
  source, re-render, dry-run again. Push only when there are none.
- **Long pages split automatically** (over about 2,400 words) into
  "<Title>", "<Title> (Part 2 of n)", ... with a contents box and
  Previous / Next links. Pages under `manuals/` are named
  "<Title> (Part k of n): <chapter>" on every part.
- If the push prints `stale part from an earlier split, delete it: '...'`,
  the page now has fewer or renamed parts. Delete exactly those pages:
  `$T/canvas.py --yes delete page "<stale title>"`.
- `REFUSING TO PUSH: ... edited in Canvas` means someone changed the page
  in Canvas. Don't use `--force`. Follow `canvas-sync`.

A finished manual: `$T/pdf2qmd.py --push manuals/<slug>/<slug>.qmd` runs the
gate, renders and pushes it with the right title.

## Many pages: queue them

When a push worker is running (`$T/push_queue.py run`, started by the
instructor), don't push guides and manuals yourself. Queue each one as it
passes its gate and go on to the next document:

    $T/push_queue.py add manuals/<slug>/<slug>.qmd
    $T/push_queue.py add guides/<id>/<id>.qmd --title "<Title>"
    $T/push_queue.py status

The worker re-runs the gate, then pushes. `failed` in `status` means the
gate or the push stopped it: read `_notes/push-queue/<key>.log`, fix the
source, and `add` it again. Build the modules once the pages show `pushed`.

Hand-written site pages (welcome, instructor, policies) are HTML in
`canvas/`, with inline styles only (`docs/canvas-html.md`):
`$T/canvas.py --yes push page canvas/welcome.html --title "Welcome"`.

The syllabus goes to the Syllabus tab:
`$T/canvas.py --yes push syllabus syllabus/syllabus.html`. It cannot be
split, so a ContentLength finding there means moving sections onto their
own pages. That is the instructor's decision: report it.

## Build the modules

1. Edit `modules.yaml` (example and item kinds in `$T/modules.py --help`):
   one module per unit, its pages in order, manuals, DOI `link:` items
   for papers, and `retire:` for the old PDFs the new pages replace.
2. Preview: `$T/modules.py --dry-run`. Check every line. A
   `(not on Canvas yet, skipped ...)` note means that page still needs
   pushing.
3. Apply: `$T/modules.py --yes`. Add `--delete-files` only if the
   instructor agreed that the retired PDFs should leave course files.
4. Run the dry run again: it should report `0 item(s) to add` for every
   module.

## Done when

Every finished page is on Canvas (`$T/canvas.py list pages`), unpublished
unless the instructor published it, and `modules.py --dry-run` has nothing
to add.
