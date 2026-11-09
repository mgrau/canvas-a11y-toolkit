#!/bin/zsh
# bench/resume_claude.sh <run-dir> [session-id]
#
# Continues a benchmark run that stopped early (a usage limit, a crash) in
# the same Claude Code session, logging to the next events.<n>.jsonl so
# each segment keeps its own timing. The session id defaults to the one in
# the last segment's result event. Model, effort and workspace come from
# run.json. score.py and progress.py read every segment in order.
set -u
out=${1:A}
TOOLKIT=${0:A:h:h}
read_json() { python3 -c "import json,sys; print(json.load(open('$out/run.json'))['$1'])"; }
ws=$(read_json workspace); model=$(read_json model); effort=$(read_json effort)
n=2; while [[ -e $out/events.$n.jsonl ]]; do n=$((n+1)); done
last=$out/events.jsonl; [[ $n -gt 2 ]] && last=$out/events.$((n-1)).jsonl
sid=${2:-$(grep '"type":"result"' $last | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)['session_id'])")}
msg="You were stopped partway through by a usage limit. Continue the task from where you left off and finish everything it asks for."
print -r -- "{\"segment\": $n, \"session\": \"$sid\", \"start\": \"$(date -u +%FT%TZ)\", \"prompt\": \"$msg\"}" > $out/segment.$n.json
rm -f $out/exit_code $out/end
cd $ws || exit 1
git add -A && git commit -qm "bench: resume segment $n" --allow-empty
claude -p "$msg" --resume $sid --model $model --effort $effort \
  --output-format stream-json --verbose \
  --settings $TOOLKIT/bench/settings.json --add-dir $TOOLKIT \
  --permission-mode acceptEdits \
  --allowedTools Bash Edit Write MultiEdit NotebookEdit TodoWrite Agent WebFetch WebSearch \
  < /dev/null > $out/events.$n.jsonl 2> $out/stderr.$n.txt
echo $? > $out/exit_code
date -u +%FT%TZ > $out/end
git add -A && git commit -qm "bench: end segment $n ($model, $effort)" --allow-empty
git rev-parse HEAD > $out/end_commit
