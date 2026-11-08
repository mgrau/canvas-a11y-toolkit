---
name: review-manual
description: Convert one vendor or reference PDF (a triage.csv "manual" row) into an accessible Quarto page with pdf2qmd.py, then review the draft against the PDF until it passes the gate. Use for equipment manuals, datasheets and other reference documents.
---

# Convert and review a manual

One manual per task. The converted page is a copy of copyrighted text:
it lives in `manuals/` (gitignored) and on Canvas, never in git. Don't
quote it in commits, NOTES or reports.

## 1. Make the draft

    $T/pdf2qmd.py "source/modules/<folder>/<file>.pdf" --out manuals

This writes `manuals/<slug>/<slug>.qmd` and `images/fig-NN.png`. Every
image is marked `TODO-ALT`, garbled equations `TODO-MATH`, and the file
starts with a `DRAFT` comment. The gate fails until all are resolved.

## 2. Review it against the PDF, a few pages at a time

The PDF is the truth; the draft is machine output. Work through the PDF
5 to 10 pages at a time:

    pdftotext -layout -f 1 -l 8 "<pdf>" -

then fix the matching part of the qmd before reading on. Never load the
whole draft or PDF at once.

Keep **all** the content, in the manual's order. Don't summarise. Fix:

- **Headings:** `#` for top-level sections, `##` below, never skip a
  level. Remove fake headings (equations, captions, running heads). The
  title block (vendor, model, part numbers) is a plain paragraph, not a
  heading.
- **Reading order:** two-column pages come out scrambled. Compare with the
  `-layout` text.
- **Math:** rewrite every `TODO-MATH` line as LaTeX (`$...$`, `$$...$$`),
  then delete the marker.
- **Tables:** pipe tables with a header row. With no header in the source,
  use `| Item | Value |` or short column names.
- **Lists:** real Markdown lists.
- **Clean up:** page numbers, running headers and footers, copyright and
  postal-address footers, the printed table of contents, hyphenation
  splits (`meas- urement`), run-together words, stray `**` or `_`.
- **Text in angle brackets** like `<No Data Selected>` must be escaped
  (`\<No Data Selected\>`), or the rest of the page vanishes.
- **Links:** descriptive text, never a bare URL.
- **No Source section** at the end, and no HTML comments.

## 3. Images

For each `images/fig-NN.png`:

- **Delete** logos, decorations, fragments, and symbols the text already
  explains. Delete the image file too.
- **Pictures of text or tables:** replace with the real text or table.
- **Informative figures:** keep, with `{fig-alt="..."}` of at most **120
  characters**. If more needs saying, add a paragraph right after it
  starting `**Figure description.**`. For graphs give axes, units, ranges
  and the trend, never estimated data values.
- A figure the draft missed: `pdfimages -png -f N -l N "<pdf>" manuals/<slug>/images/p`
  extracts it. Never screenshot a page.
- **If you cannot see images**, don't guess what they show. Write alt text
  only from what the surrounding text says the figure shows, and list
  every figure you could not check in your report for the instructor.

When done, delete the `<!-- DRAFT ... -->` line.

## 4. The gate

    $T/pdf2qmd.py --diff --render --check manuals/<slug>/<slug>.qmd

It must print `1/1 files pass`. The `--diff` list shows PDF words the page
never uses: footer and address words you removed are fine; anything else
means lost content, so find it and restore it.

## Done when

The gate passes, and you have reported: figures kept (with alt text) and
deleted (count), anything unresolved, figures you could not check, and
anything in the PDF that looks wrong or unsafe (for example a safety
limit) for the instructor.
