# Fixing YuJa Panorama issues

How Panorama scans, what each issue type means, how to fix it, and the
checklist rule (`scripts/a11y_check.py`) that catches it before a push.
Learned while taking the pilot course from 29.7% to 99.996% (Nov 2026).
The procedure is `skills/fix-yuja`.

## Our checklist

`scripts/a11y_check.py` has one rule per Panorama issue type, named after
Panorama's issue id. It runs:

- on rendered pages, checking exactly what a push would send (captions and
  font fixes applied, long pages split): `a11y_check.py guides/*/*.html`;
- on what Canvas stores: `a11y_check.py --canvas [titles]`;
- automatically on every `canvas.py push page` and `push syllabus`.

External links are tested only with `--links` (slow).

**Validation.** On 66 scored web pages, the checklist found the same issue
types as Panorama on 65. Two rules are deliberately stricter than
Panorama: alt over 120 characters (one school's Panorama allowed 240), and
a bare domain as link text. Re-run the comparison when Panorama's
behaviour seems to change:

    a11y_check.py --compare _notes/yuja/<list dump> _notes/yuja/issues/issues.json

It skips pages edited since Panorama scanned them.

Calibrations:

- Panorama counts words as `\w+(?:['’.]\w+)*` tokens: `CONF:VOLT:DC` is
  three words, `1.5` one. Its limit is 3,000; a page of 3,020 failed and
  2,997 passed. We warn and split at 2,900, measured on the finished page
  (contents box and footnotes included).
- Plain `<sub>` and `<sup>` pass the font rule; a `<sub>` inside an `<h5>`
  did not.
- A table fails only when all its data cells are empty.
- `alt=""` failed at the pilot school, whose Panorama has "Treat Empty Alt
  Tags as Decorative Images" turned off. The checklist flags it.

## How Panorama scans

Observed at one school, Nov 2026. Expect the same shape elsewhere.

- **New content is scanned in batches**, from minutes (new files) to
  hours apart (new pages).
- **An edited page is not rescanned promptly**; it often waits for a
  nightly batch.
- **There is no per-file rescan.** Removing and re-adding a module item did
  not trigger one. "Sync Now" did not start a scan.
- **Deleted content lingers** in the list with its old score, and still
  counts in the course average, until a Reprocess.
- **Reprocess** (Configuration > General Settings) deletes Panorama's
  stored documents and rescans the whole course. One run took six minutes,
  another six hours. It does not touch Canvas content. It is the
  instructor's decision, never a script's; the toolkit refuses to do it.
- **Unpublished and locked content is scanned** too.
- **Institution settings** come back in Panorama's `feature-flags`
  response (`altTextLimit`, `fontSizeMinimum`).
- `yuja.sh list` asks for 200 items sorted by score, so it shows the lowest
  200.

## Issue types and fixes

The first three fixes are automatic: `canvas.py push page` applies them to
every page.

| Issue (severity) | What triggers it | Fix |
| ---------------- | ---------------- | --- |
| `SmallFontSizeIssue` (major) | Text Panorama computes as under 10 pt with the browser's default styles: every `<code>`, `<pre>`, `<kbd>`, `<samp>`, and `<h5>`, `<h6>`. Canvas's stylesheet is not applied. | Automatic: `font-family: monospace, monospace` on code (bare `monospace` renders at 13 px whatever `font-size` says; naming it twice gives 16 px) and `font-size: 1em` on h5/h6. |
| `EmptyHyperlinkIssue` (severe) | Pandoc's empty line anchors in code blocks, `<a href="#cb1-1" aria-hidden="true"></a>`. | Automatic: removed at push. |
| `ContentLengthIssue` (minor, costs 1 point) | Over 3,000 words as Panorama counts them. | Automatic for pages: split into linked parts (`scripts/page_parts.py`) at chapters, then subsections, then paragraphs. The Syllabus tab cannot split: move sections to pages. |
| `MissingTableCaptionIssue` (severe) | A data table without `<caption>`. | Automatic: caption from the nearest heading. |
| `LongAlternativeTextIssue` (severe) | `alt` over the limit (help text says 120). One such image took a page from 100 to 29. | Alt at most 120 characters; the full description as visible text (`desc=` in tikz blocks, a `**Figure description.**` paragraph in manuals). `tikz.lua` and `pdf2qmd.py --check` refuse longer alt. |
| `MissingAlternativeTextIssue` (severe) | No alt, or `alt=""` where empty alt is not treated as decorative. | Write alt text; delete purely decorative images. |
| `DecorativeImageAsLinkIssue` (severe) | An image with empty alt inside a link. | Give it alt text that names the link's target. |
| `BrokenHyperlinkIssue` (severe) | A link that does not resolve, mostly dead vendor URLs printed in old manuals. | Relink if the page moved; otherwise keep the printed address as plain text and say it is no longer online. Some sites (`scanner_blocked` in course.toml, e.g. knowledge.ni.com) give Panorama a 404 for a live page: name the page in plain text instead of linking it. |
| `HyperlinkContextIssue` (severe) | Link text that is a bare URL or domain. | Descriptive link text ("Thorlabs EDU-MINT2 product page"). |
| `MissingTableContentIssue` (severe) | A table whose data cells are all empty (a blank table for students). | `(your value)` or a dash in each blank cell. |
| `MissingTableHeadersIssue` (severe) | A data table without header cells. | A header row in the Markdown table. (A table with no `<th>` at all is marked `role="presentation"` at push, as a layout table.) |
| `SkippedHeadingIssue` | A heading level skipped (h2 then h4). | Fix the levels in the source; `pdf2qmd.py --check` catches it. |
| PDF: untagged, scanned, no headings, tables without headers | Legacy PDFs | Replace each with an HTML page and retire the PDF. |

## Lessons from the pilot

- **Check the scan date before fixing.** Panorama reports its last scan,
  which can be hours old. Several "issues" were already fixed on Canvas.
- **Fix at the push step when you can.** Thousands of SmallFontSize issues
  came from one cause (code fonts) and one push-time fix cleared them all.
- **Every fix gets a checklist rule**, so the next page is caught before
  it is pushed rather than after a rescan.
- **Page names matter for long manuals.** "Manual (Part 7 of 18): Chapter 4
  Setup" is far easier to find in a module than "Manual (Part 7 of 18)".
- **Slugs are Canvas's choice.** Updating a page by a guessed slug created
  duplicates ("-2" pages); the client now finds pages by title.
- **Splitting needs the finished page.** A part under the limit can go over
  once its contents box is added; `split()` measures the assembled pages.
