# Task: adapt last year's course into accessible Canvas content

You are working for the instructor of PHYS 413, Methods of Experimental
Physics (an upper-level physics lab course at Old Dominion University),
Spring 2027. The instructor is not available during this task: work
autonomously from start to finish, and make reasonable decisions yourself.
Record every decision you would normally have asked about in
`DECISIONS.md` in the workspace.

## Where things are

- **The course workspace** is the current directory. It is already set up
  (`course.toml`, `.env` with the Canvas token). Canvas course 241145 is
  the course you are building.
- **Last year's course** (Spring 2026) is in `source/`: every module's files
  in `source/modules/`, the old syllabi, and `source/manifest.json`. The
  Canvas course already holds a copy of last year's modules and PDFs.
- **The toolkit** is at `@TOOLKIT@`. Read `@TOOLKIT@/AGENTS.md` first and
  follow it and its skills (`@TOOLKIT@/skills/`).

## What to do

Convert last year's material into accessible pages that will score 100 in
YuJa Panorama, and put them on Canvas as unpublished drafts:

1. Triage every document in `source/modules/`.
2. Transcribe every locally written instruction sheet into a guide
   (`guides/<id>/`).
3. Convert every vendor manual and reference document into a page
   (`manuals/<slug>/`).
4. Link journal papers by DOI instead of hosting the PDF.
5. Push everything to Canvas, unpublished, and build one module per
   experiment (`modules.yaml`) in which the new pages replace the old PDFs.
   Retire the PDFs that a page replaces from the modules.
6. Run the local accessibility checklist on everything you pushed.
7. Write `REVIEW.md` for the instructor (the `handoff` skill).

Instructor-only material (for example an instructor's manual with
solutions) must not be given to students. Experiments with no equipment
this year are listed in `source/README.md` if at all; use your judgement.

## Rules

- Follow the hard rules in `@TOOLKIT@/AGENTS.md`. Never publish anything.
- Work only inside this workspace and the toolkit. Do not read or search
  any other folder on this computer, other Claude Code sessions or
  transcripts, or any GitHub repository: this is a test of what you can do
  from the source material alone.
- Do not wait for YuJa Panorama rescans; the instructor will check scores
  later.
- When you have finished everything, end with a short summary: what you
  converted, what you pushed, and what is left.
