# Converting a Canvas course to accessible content

How the toolkit's pipeline works and why, from its first use: an
upper-level physics lab course (Nov 2026) converted from an inherited set
of PDFs into accessible Canvas pages. The step-by-step commands are in
`skills/`; this is the background.

## Why

The DOJ's 2024 ADA Title II rule makes WCAG 2.1 Level AA the standard for a
public university's web content, including course content in an LMS. Many
schools check Canvas courses with **YuJa Panorama**, which scores every page
and file. The course score is about the mean of the item scores, so one
inaccessible PDF counts as much as one good page.

The target: every item a student is given scores 100 in Panorama, and a
person has checked what no automated checker can (that alt text is
accurate, reading order makes sense, the content is right).

## The pilot course

- One Canvas module per experiment (about 30), each a handful of PDFs: a
  locally written instruction sheet (often a scan) plus vendor manuals and
  journal papers.
- About 110 pages of the school's course template, none course-specific.
- **Baseline Panorama score 29.7%** (web pages 97%, PDFs 2.5%). Of 63 PDFs,
  49 scored 0: untagged, scanned, no headings, no alt text.
- After conversion: 249 items, **99.996%**. Every item at 100 except the
  syllabus (99, too long for one page).

## The steps

1. **Export the old course, read only** (`export_course.py`). It goes in
   `source/`, outside git, because it is someone else's material plus
   copyrighted manuals. The client cannot write to a source course.
2. **Triage** (`triage.py`, then a decision per document). `pdftotext` word
   counts separate text PDFs from scans: a page with no extractable words
   is a scan.

   | Kind | What to do |
   | ---- | ---------- |
   | Locally written instructions | Transcribe to a Quarto guide. The guide replaces the PDF. |
   | Vendor manual | Convert to an HTML page (automatic first pass, then review). Kept out of git. |
   | Journal paper | Link the DOI rather than host the PDF. The publisher's HTML is usually more accessible, and it avoids rehosting. |
   | Template boilerplate | Leave out. |

3. **Transcribe instruction sheets** into `guides/<id>/<id>.qmd`, with every
   change from the source recorded in `NOTES.md` (instructor-only).
   Diagrams are redrawn as TikZ with short alt text and a visible
   description; wiring photos become tables. Rendered to HTML for Canvas and
   PDF for print.
4. **Convert manuals** with `pdf2qmd.py`: pymupdf4llm extracts text and
   images, then a cleanup pass removes picture OCR, running headers and
   footers, page numbers and markup debris, restores hyphenated words, sets
   heading levels from section numbers, and marks every image `TODO-ALT`
   and every garbled equation `TODO-MATH`. The draft is then reviewed
   against the PDF. `pdf2qmd.py --diff --render --check` is the gate: it
   fails on missing or long alt text, leftover markers, HTML comments, bare
   URLs, skipped heading levels, tables without header cells, and a rendered
   page with fewer headings than its source (text like `<No Data Selected>`
   read as an HTML tag swallows the rest of the page). `--diff` lists PDF
   words the page never uses.
5. **Push, unpublished** (`canvas.py push page`). The push strips Quarto's
   page furniture and HTML comments, shifts headings below Canvas's own
   h1, adds table captions and `scope`, fixes code fonts and Pandoc's empty
   code-line links, uploads images locked, runs the checklist, and splits a
   long page into linked parts. It refuses to overwrite a page edited in
   Canvas (`canvas_sync.py pull` merges the edit back).
6. **Build the modules** from `modules.yaml` (`modules.py`), which adds only
   what is missing and retires the PDFs the new pages replace.
7. **Check with Panorama** (`yuja.sh`) and the local checklist
   (`a11y_check.py`), fix the sources, re-push, wait for the rescan.
8. **Hand off.** The instructor reviews, publishes, and unlocks the folders
   the published pages use.

## Library links

A plain `https://doi.org/...` link shows an off-campus student the
publisher's paywall. Through the library's EZproxy (prefix + the DOI link)
the student signs in with their campus login and gets the article on the
school's subscription. Write the plain DOI in sources; `quarto/library-proxy.lua`
adds the prefix when rendering and `modules.py` adds it to module links.
Set the prefix in `course.toml [library] proxy_prefix` (and `_quarto.yml`
`library-proxy:`).

## Cost on the pilot (Claude Opus, API list prices)

12 guides and 48 manuals (about 1,450 PDF pages) came to about $134, nearly
all of it from 38 agent runs:

- 13 guide transcriptions: $17 (about $0.65 to $2.50 each).
- 25 manual reviews: $103, roughly $0.07 a PDF page. Cost grows faster than
  page count, because every call re-reads the agent's growing context: a
  300-page manual cost $15, a 20-page one about $1. Reading a long manual in
  slices with a fresh context per slice keeps this down.

The automatic first pass costs nothing, but its drafts are not fit to
publish unreviewed.
