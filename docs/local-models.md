# Running the toolkit with a smaller local model

The toolkit was built with a large model but is designed so a smaller one
(around 30B parameters, run locally) can do most of the work. The design
choices that make that possible:

- **The safety rules are in code, not only in prose.** `canvas_api.py`
  refuses to publish, unlock, change visibility or settings, or write to
  any course but the one in `course.toml`, and it has no student-data
  calls. `yuja_launch.mjs` refuses any Panorama action that changes
  anything. A model that ignores an instruction still cannot do these
  things; `tests/test_guard.py` proves it.
- **Every step has a gate**: a command with a pass/fail exit code and a
  plain message ("1/1 files pass"). The model does not have to judge
  whether it is done.
- **The skills are short, ordered checklists** with the exact commands.
- **Mechanical work is scripted**: export, triage measurements, PDF
  extraction and cleanup, HTML fixes, page splitting, module building.
- **Tasks are small**: one guide or one manual, read 5 to 10 pages at a
  time.

## Setting it up

Any agent harness that can run shell commands and edit files works (for
example Qwen Code, opencode, aider or Claude Code). Point it at the course
workspace. The workspace's `AGENTS.md` sends the model to the toolkit's
`AGENTS.md`; `CLAUDE.md` and `QWEN.md` are links to it, and
`.claude/skills` and `.qwen/skills` link to `skills/`. If your harness
doesn't load skills by itself, tell the model to read
`skills/<name>/SKILL.md` before each step (AGENTS.md says so too).

Give the model a context window of at least 32k tokens; 64k or more makes
manual reviews smoother. Start a fresh session for each manual.

## What still needs a person or a stronger model

Be honest with yourself about these:

- **Figures.** Writing accurate alt text and descriptions needs the model
  to see the image. If yours cannot read images, it should write alt text
  only from what the surrounding text says, and list every figure for a
  person to check (the review-manual skill says so). Wrong alt text is
  worse than a flagged TODO.
- **Equations.** Rewriting garbled equations as LaTeX from a page image
  needs vision too. Without it, the model can recover many from the text
  layer (`pdftotext -layout`), but should list any it is unsure of.
- **Physics errors in sources.** Spotting them takes subject knowledge;
  treat a small model's corrections with suspicion and check NOTES.md.
- **Two-column reading order** in a scanned manual is hard; spot-check.

A practical split: let the local model do triage, transcription drafts,
manual cleanup, pushes and module building, and have a person (or a
larger vision model, for a few cents a page) do the figure pass and the
final review using REVIEW.md.

## Trying it safely

Point `course.toml` at a sandbox course first (Canvas "sandbox" or a test
course the instructor owns). `tests/run.sh` checks the guards offline.
