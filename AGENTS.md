# Canvas accessibility toolkit: instructions for agents

You are helping an instructor convert a Canvas course into accessible HTML
pages that score 100 in YuJa Panorama (WCAG 2.1 AA). The scripts here do
the hard parts. Your job is to run them in the right order, do the careful
reading and writing they cannot do (transcribing, alt text, fixing
extraction damage), and check every result with the gate commands.

## Hard rules

These come first and have no exceptions. The scripts enforce most of them.
If a script stops with `Refused`, that is the rule working: do not edit
the script, retry with other flags or call the API another way. Tell the
instructor what you were trying to do.

1. **Never publish.** Everything goes to Canvas as an unpublished draft,
   and every file is uploaded locked. Never publish, unlock, show or hide
   anything, set the front page, or change course settings. The instructor
   does all of that by hand after reviewing.
2. **Write only to the course in `course.toml` (`course_id`).** Source
   courses (`source_course_ids`) are read only.
3. **Keep other people's material out of git.** `source/` (the exported
   old course) and `manuals/` (converted vendor manuals, which are
   copyrighted) are gitignored. Never `git add -f` them, never paste their
   text into a committed file, and never push them anywhere but Canvas.
4. **Never handle student data.** The toolkit has no roster, grade or
   submission commands, so don't add any.
5. **Never commit `.env`** (the Canvas token) or `_notes/` (Panorama dumps,
   which carry session tokens and the instructor's name).
6. **Panorama is read only.** Never click or script "Reprocess", "Sync
   Now" or anything else that changes Panorama. Reprocessing is the
   instructor's decision.
7. **Deleting:** delete only what the task names. Look at it first (`list`,
   `--dry-run`). Canvas keeps deleted items at `/courses/<id>/undelete`
   for a while, but don't count on it.
8. **Faithful, not creative.** Transcribe sources; don't summarise or
   invent apparatus details, values or citations. When unsure, keep the
   source's wording and note it for the instructor.

## How to run things

- Work inside the **course workspace**, the folder with `course.toml`. Run
  the toolkit's scripts from there by full path, for example
  `~/teaching/canvas-a11y-toolkit/scripts/canvas.py whoami`. Below, `$T`
  stands for the toolkit's `scripts/` folder.
- Global flags go **before** the subcommand: `$T/canvas.py --yes push page
  ...`, never `push page ... --yes`. Without `--yes`, a non-interactive run
  stops with "refusing to write to Canvas without confirmation".
- **Dry-run first, every time** you write to Canvas: `--dry-run`, read the
  output, then run it again with `--yes`.
- The scripts start with `#!/usr/bin/env -S uv run --script` and install
  their own Python packages. Run them directly; don't `pip install`.
- A command succeeded only if it exits 0 **and** its output says so ("1/1
  files pass", "0 page(s) fail"). Read the output; don't assume.

## The pipeline

Do the steps in order. Each has a skill (`skills/<name>/SKILL.md`) with
the exact commands and a "Done when" check. **Read the skill before
starting its step.**

| Step | Skill | What it produces | Done when |
| ---- | ----- | ---------------- | --------- |
| 1 | `setup-course` | workspace, token, `course.toml` | `canvas.py whoami` names the right course |
| 2 | `export-and-triage` | `source/`, `triage.csv` with a decision per document | no row without a decision |
| 3 | `transcribe-guide` | `guides/<id>/<id>.qmd` + `NOTES.md` per instruction sheet | `pdf2qmd.py --render --check` and `a11y_check.py` pass |
| 4 | `review-manual` | `manuals/<slug>/<slug>.qmd` per vendor manual | `pdf2qmd.py --diff --render --check` passes |
| 5 | `push-to-canvas` | unpublished pages, `modules.yaml`, modules | `modules.py --dry-run` shows nothing to add |
| 6 | `fix-yuja` | every item at 100 in Panorama | `yuja.sh list` shows no item under 100 |
| 7 | `handoff` | `REVIEW.md`: what the instructor must check and publish | the instructor has it |

Other skills: `canvas-sync` (someone edited a page in Canvas and a push
refuses to overwrite it).

## Working well

- **One document per task.** Do one guide or one manual at a time. Finish
  it and run its gate before starting the next.
- **Read in pieces.** For a long PDF, read 5 to 10 pages at a time
  (`pdftotext -layout -f N -l M file.pdf -`) and fix the matching part of
  the draft before moving on. Never load a whole long manual at once.
- **Fix the source, not Canvas.** Edit the `.qmd`, re-render, re-push.
  Never edit a page in the Canvas editor.
- **When a check fails**, read its message, fix that one thing and
  re-run. If the same check fails three times, stop and report it.
- **When you are blocked** (a missing file, a decision only the instructor
  can make, a `Refused`), stop and say so plainly. Don't guess.
- **Keep the workspace's `AGENTS.md` current**: what is done, what is left,
  and decisions the instructor made.

## Reference

- `docs/pipeline.md`: the whole process, why each step exists, and what it
  cost on the pilot course.
- `docs/panorama-issues.md`: how Panorama scans, every issue type, its fix,
  and the checklist rule that catches it.
- `docs/canvas-html.md`: what survives Canvas's HTML sanitizer.
- `docs/local-models.md`: running this with a smaller local model.
- `templates/`: the files `new_course.py` copies into a workspace, and a
  guide skeleton. `examples/pendulum/`: a finished example guide.
