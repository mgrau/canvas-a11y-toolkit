---
name: fix-yuja
description: Read YuJa Panorama's accessibility scores and issues for the course and fix pages until every item scores 100. Use when asked about YuJa or Panorama scores, or after pushing pages.
---

# Fix YuJa Panorama issues

The playbook is `docs/panorama-issues.md` (issue types, fixes, how scans
behave). Read the row for each issue type you meet.

1. **Check locally first** (no waiting for a scan):

       $T/a11y_check.py --canvas

   It runs one rule per Panorama issue type on every page as Canvas stores
   it. Add `--links` to test external links (slow).
2. **Read Panorama** (read only):

       $T/yuja.sh list _notes/yuja/list          # every item and its score
       $T/yuja.sh issues _notes/yuja/issues      # issues on pages under 100

   The dumps go in `_notes/` (gitignored: they carry session tokens).
   `list` shows the lowest 200 items.
3. **Compare the scan time with the page.** Panorama reports its last scan
   (`scanned ...`). If the page changed after that, the issue may already
   be fixed. Check with `a11y_check.py --canvas "<title>"` before editing.
4. **Fix the source** (`.qmd`, `canvas/*.html`), never the Canvas page.
   Use the fix in the playbook's table. Re-render and push (`push-to-canvas`).
5. **Wait for the rescan.** Panorama scans new content within minutes to
   hours, and edited pages often only in a nightly batch. Don't poll in a
   tight loop; check back later. **Never use Reprocess**: it is the
   instructor's decision. If items are stuck, tell the instructor.
6. **A new issue type** the checklist missed: report it with the page and
   Panorama's message. Adding a rule to `scripts/a11y_check.py` is a change
   to the toolkit; propose it to the instructor rather than making it in
   the middle of a conversion, unless they asked you to.

## Done when

`yuja.sh list` shows every item at 100, or every item under 100 has a
reason the instructor has seen (for example a syllabus that needs
splitting).
