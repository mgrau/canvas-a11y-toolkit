# Benchmark: one-shot course adaptation

Measures how well a model, driving this toolkit on its own, converts an
inherited course into accessible Canvas content: time, tokens, cost,
completeness against an instructor-reviewed reference, gate results,
safety, and (after a scan) the YuJa Panorama score.

## Files

- `task.md`: the one prompt the model gets (same for every model).
- `settings.json`: Claude Code permission rules for the run; denies reads
  of the reference answers and other sessions' transcripts.
- `run_claude.sh <workspace> <run-dir> [model] [effort]`: runs Claude Code
  headless and logs every event (`events.jsonl`, stream-json with token
  usage and timestamps). The workspace is committed before and after.
- `score.py <run-dir> --workspace ... --reference ... --reference-manuals ... [--canvas] [--panorama <dump>]`:
  writes `metrics.json`.
- `plot.py <run-dir>` and `plot.py --compare <run-dir>...`: PNG plots.
- `progress.py <run-dir>`: one-line live status (docs drafted and pushed,
  elapsed time, cost).

Each run starts from the same Canvas state:

- `reset_course.py <course id> <cutoff> [--yes]`: empties the benchmark
  course back to before the source import (folders stay). The instructor
  then imports the source course again.
- `snapshot_course.py <out.json>`: read-only record of the imported
  course, to compare with an earlier run's starting point.

For a local model on another machine:

- `run_local.sh <workspace> <run-dir> <model> [effort] [port]`: same as
  `run_claude.sh`, but Claude Code talks to a local llama-server, with an
  empty config dir, no reads under CloudStorage, and `task_queue.md` added
  to the prompt. Pushes go through a `push_queue.py` worker. Run it in tmux
  on the model's machine.
- `mirror_run.sh`: runs on the instructor's computer. Every 30 s it copies
  the run's log and status files back, so `progress.py` works there.
- `yuja_watch.py <workspace> <host>:<remote ws>`: runs where the Panorama
  sign-in is. Every 10 minutes it copies the findings for pages the run
  pushed into the remote `_notes/yuja/`.

## What is measured

| Area | Measures |
| ---- | -------- |
| Process | wall time, API time, turns, tokens by kind, cost, subagents, tool calls and errors |
| Coverage | guides and manuals done, of the reference's 12 and 48 |
| Accuracy | per document: recall and precision of the reference text (word multisets), figures kept vs reference, TODO-ALT/TODO-MATH left, gate pass, checklist findings on the rendered page |
| Safety | refused writes, publish attempts, accesses to forbidden paths (the reference answers, other transcripts) |
| Canvas | pages, published items (must be none new), modules, PDFs left, unlocked files |
| Panorama | mean score and items under 100, from a `yuja.sh list` dump after the scan |

Recall against the reference is a proxy: a model can legitimately word a
guide differently. Read the lowest-scoring documents by hand.

## Other harnesses

`score.py` reads Claude Code's stream-json. For another harness (Qwen
Code, opencode), convert its log to the same `events.jsonl` shape
(assistant messages with `usage` and `timestamp`, `tool_use` and
`tool_result` blocks). A local model costs nothing at API prices; its
tokens and time still compare.
