---
name: export-and-triage
description: Export the old Canvas course (read only) and decide what to do with each document. Use after setup-course, before any conversion.
---

# Export the source course and triage it

1. **Export** (read only; it cannot change the old course):

       $T/export_course.py

   Files land in `source/modules/NN <module>/`, pages in `source/pages/`,
   with `source/manifest.json` listing every module item. `source/` is
   gitignored: it is someone else's material. Re-running skips files
   already downloaded.
2. **Measure:**

       $T/triage.py

   This writes `triage.csv`: pages, words per page, whether the PDF is
   tagged or scanned, and a `suggested` action guessed from the file name.
3. **Decide each row.** Fill the `decision` column (edit the CSV) with one of:

   | decision | when | next step |
   | -------- | ---- | --------- |
   | `guide`  | instructions written for this course (lab sheets, handouts) | `transcribe-guide` |
   | `manual` | vendor manual, datasheet, reference document | `review-manual` |
   | `doi`    | a published journal paper | a `link:` item in `modules.yaml` with its DOI |
   | `drop`   | template boilerplate, duplicates, outdated copies | leave it out |
   | `keep`   | already accessible, or not for students | nothing |

   To tell them apart, look at the first page: `pdftotext -l 2 "<file>" - | head -60`.
   A paper has a journal name, volume and DOI near the top. A scanned
   document (`scanned` = yes) has no text layer, so read its page images.
   Put anything you are unsure of in `notes` and leave `decision` empty
   for the instructor.
4. **Check the old pages** in `source/pages/`. Template pages (the school's
   standard "Getting started", "Technical support" pages) are usually
   `drop`. Course-specific ones become hand-written pages in `canvas/`.
5. Show the instructor the rows you could not decide, and the counts of
   each decision. Commit `triage.csv` (it holds only file names, no text).

## Done when

Every row of `triage.csv` has a `decision`, and the instructor has seen
the list.
