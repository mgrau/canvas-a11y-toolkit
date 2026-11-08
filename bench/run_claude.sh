#!/bin/zsh
# bench/run_claude.sh <workspace> <run-dir> [model] [effort]
#
# One-shot benchmark run with Claude Code: hands the model bench/task.md in
# the course workspace and records every event (stream-json, with token
# usage and timestamps) to <run-dir>/events.jsonl. The workspace is
# committed before and after, so the run's changes are one git diff.
# Score it afterwards with bench/score.py.
set -u
ws=${1:A}; out=${2:A}; model=${3:-claude-sonnet-5-5}; effort=${4:-high}
TOOLKIT=${0:A:h:h}
mkdir -p $out
sed "s|@TOOLKIT@|$TOOLKIT|g" $TOOLKIT/bench/task.md > $out/prompt.md
print -r -- "{\"model\": \"$model\", \"effort\": \"$effort\", \"harness\": \"claude-code $(claude --version | cut -d' ' -f1)\", \"workspace\": \"$ws\", \"start\": \"$(date -u +%FT%TZ)\"}" > $out/run.json
cd $ws || exit 1
git add -A && git commit -qm "bench: start ($model, $effort)" --allow-empty
git rev-parse HEAD > $out/start_commit
claude -p "$(cat $out/prompt.md)" --model $model --effort $effort \
  --output-format stream-json --verbose \
  --settings $TOOLKIT/bench/settings.json --add-dir $TOOLKIT \
  --permission-mode acceptEdits \
  --allowedTools Bash Edit Write MultiEdit NotebookEdit TodoWrite Agent WebFetch WebSearch \
  < /dev/null > $out/events.jsonl 2> $out/stderr.txt
echo $? > $out/exit_code
date -u +%FT%TZ > $out/end
git add -A && git commit -qm "bench: end ($model, $effort)" --allow-empty
git rev-parse HEAD > $out/end_commit
