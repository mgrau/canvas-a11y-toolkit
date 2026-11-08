---
name: handoff
description: Write REVIEW.md, the instructor's checklist of what to check and publish by hand. Use when a batch of pages is on Canvas, or at the end of a conversion.
---

# Hand off to the instructor

The instructor reviews and publishes everything. Write `REVIEW.md` in the
workspace so that is quick and nothing is missed. Keep it current; add to
it each time you push new pages.

## What goes in REVIEW.md

1. **To publish, in this order:** for each module, its pages (all parts),
   then the module itself. Remind them that publishing a module does not
   publish its pages.
2. **Folders to unlock:** every `course files/...` folder holding images
   or files a published page uses (`$T/canvas.py list files` shows
   locked files). Until it is unlocked, students see broken images.
3. **The front page:** if a new welcome page should be the front page, say
   which: Canvas → Pages → the page's menu → "Use as Front Page" (it must be
   published first).
4. **To check by a person**, from every `guides/*/NOTES.md`: each CHECK
   item, and each change from the source. List them per guide.
5. **From the manual reviews:** figures that could not be checked, and
   anything that looked wrong or unsafe in a manual. Describe it, but
   don't quote the manual's text.
6. **Decisions waiting:** undecided `triage.csv` rows, a syllabus too long
   for Panorama, anything you stopped on.
7. **Panorama:** the current score (`yuja.sh list`) and the items under 100.

Write it plainly, as a checklist (`- [ ]`). Commit it.

## Done when

REVIEW.md lists everything above, and you have told the instructor it is
ready.
