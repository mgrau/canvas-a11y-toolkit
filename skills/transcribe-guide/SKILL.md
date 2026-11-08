---
name: transcribe-guide
description: Transcribe one locally written instruction sheet (a triage.csv "guide" row) into an accessible Quarto guide plus instructor notes. Use for lab instructions, handouts and worksheets written for the course.
---

# Transcribe an instruction sheet into a guide

One guide per task. Pick an id (`snake_case`, e.g. `hall_effect`).

## Files

- `guides/<id>/<id>.qmd`: the guide. Start from `$T/../templates/guide.qmd`
  and look at the finished example `$T/../examples/pendulum/pendulum.qmd`.
- `guides/<id>/NOTES.md`: instructor-only notes, from
  `$T/../templates/NOTES.md`. Never pushed.

Create or edit files only inside `guides/<id>/`. Don't push to Canvas in
this step.

## Read the source

- Text: `pdftotext -layout "<pdf>" - | sed -n '1,120p'` (then the next lines).
- Figures and layout: look at the page images if you can read images.
  Otherwise `pdfimages -list "<pdf>"` shows which pages have pictures;
  describe what the text says about them and add a CHECK item to NOTES.md
  asking the instructor to confirm the figure.
- A scanned PDF has no text: read the page images.

## Rules

1. **Transcribe faithfully.** Keep the source's content and order. Fix real
   errors (physics, arithmetic, units), and record **every** change in
   NOTES.md under "Changes from the source". Values that must be confirmed
   on the real equipment go under "CHECK".
2. **Sections, in this order:** Overview (ending with the goal in bold),
   Safety (limits in a table), The apparatus, How it works, Setup,
   Procedure (numbered), Analysis questions, Sources. Skip a section the
   source has nothing for.
3. **Headings start at `#`** and never skip a level (`#` then `##`, never
   `#` then `###`).
4. **Math** as `$...$` inline and `$$...$$` on its own line.
5. **Figures** are redrawn as `{.tikz}` or `{.circuitikz}` code blocks (the
   code goes inside `\begin{tikzpicture}...\end{tikzpicture}` or
   `\begin{circuitikz}...\end{circuitikz}`). Each needs:
   - `alt="..."`: at most **120 characters**. Count them.
   - `desc="..."`: the full description, printed under the figure. For a
     graph: the axes, their quantities and units, and the shape.
   If you cannot draw it, write the description as text and add a CHECK.
   Never paste a scanned image or a picture of text.
6. **Wiring photos become wiring tables** (`| From | To |`).
7. **Tables** are Markdown pipe tables with a header row. A blank table for
   students to fill gets `(your value)` in each cell, never empty cells.
8. **Links** have descriptive text: `[Thorlabs EDU-MINT2 manual](https://...)`,
   never a bare URL or "click here". Journal articles as
   `https://doi.org/...` links.
9. **No HTML comments** except the one-line NOTES.md pointer under the
   YAML header.
10. **Plain language**, addressed to the student as "you", in short
    paragraphs. Don't invent details the source doesn't give.
11. **Sources section:** cite the original (title, author, institution,
    year as best you can tell) and say the manuals are in the module.

## Verify

    quarto render guides/<id>/<id>.qmd
    $T/pdf2qmd.py --render --check guides/<id>/<id>.qmd
    $T/a11y_check.py guides/<id>/<id>.html

Fix each reported problem and re-run until the check prints `1/1 files
pass` and the checklist prints `0 page(s) fail`. If the PDF render fails
(LaTeX), fix it too: the guide also prints as a handout.

## Done when

Both checks pass, NOTES.md lists every change and CHECK item, and you have
reported: the files written, each figure with its alt text, and the
changes and CHECK items.
