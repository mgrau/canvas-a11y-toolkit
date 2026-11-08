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
