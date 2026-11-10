#!/bin/zsh
# bench/resume_local.sh <run-dir> [session-id] [port]
#
# resume_claude.sh for a run_local.sh run: continues the same Claude Code
# session against the local llama-server, with the run's own config dir and
# settings, a push worker alongside, and the next events.<n>.jsonl. The
# session id defaults to the one in the last segment's result event.
#
# Claude Code is told to wait for background subagents however long they
# take (CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0). Without it, a headless run
# stops them 10 minutes after the main agent's last turn: the Qwen run of
# 2026-11-09 ended that way, with 10 subagents mid-conversion.
#
# Requests may also wait up to an hour (API_TIMEOUT_MS): with many
# subagents sharing a few server slots, a request queues behind the others,
# and the default 10-minute timeout killed 12 subagents in that run.
set -u
out=${1:A}; port=${3:-8091}
TOOLKIT=${0:A:h:h}
read_json() { python3 -c "import json,sys; print(json.load(open('$out/run.json'))['$1'])"; }
ws=$(read_json workspace); model=$(read_json model)
n=2; while [[ -e $out/events.$n.jsonl ]]; do n=$((n+1)); done
last=$out/events.jsonl; [[ $n -gt 2 ]] && last=$out/events.$((n-1)).jsonl
sid=${2:-$(grep '"type":"result"' $last | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)['session_id'])")}
msg=${RESUME_MSG:-"You were stopped partway through, and your background subagents with you. Continue the task from where you left off and finish everything it asks for."}
export ANTHROPIC_BASE_URL=http://127.0.0.1:$port
export ANTHROPIC_API_KEY=$(cat ~/local-ai/etc/llm-api-key.txt)
export ANTHROPIC_MODEL=$model ANTHROPIC_SMALL_FAST_MODEL=$model CLAUDE_CODE_SUBAGENT_MODEL=$model
export ANTHROPIC_DEFAULT_OPUS_MODEL=$model ANTHROPIC_DEFAULT_SONNET_MODEL=$model ANTHROPIC_DEFAULT_HAIKU_MODEL=$model
export CLAUDE_CONFIG_DIR=$out/claude-config
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 API_TIMEOUT_MS=3600000
export PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH
print -r -- "{\"segment\": $n, \"session\": \"$sid\", \"start\": \"$(date -u +%FT%TZ)\", \"prompt\": \"$msg\", \"bg_wait\": \"unlimited\"}" > $out/segment.$n.json
rm -f $out/exit_code $out/end $out/queue_drained $out/end_commit
cd $ws || exit 1
git add -A && git commit -qm "bench: resume segment $n" --allow-empty
$TOOLKIT/scripts/push_queue.py run >> $out/push_worker.log 2>&1 &
worker=$!
claude -p "$msg" --resume $sid --model $model \
  --output-format stream-json --verbose \
  --settings $out/settings.json --add-dir $TOOLKIT \
  --permission-mode acceptEdits \
  --allowedTools Bash Edit Write MultiEdit NotebookEdit TodoWrite Agent WebFetch WebSearch \
  < /dev/null > $out/events.$n.jsonl 2> $out/stderr.$n.txt
echo $? > $out/exit_code
date -u +%FT%TZ > $out/end
kill $worker; wait $worker 2>/dev/null
$TOOLKIT/scripts/push_queue.py run --once >> $out/push_worker.log 2>&1
date -u +%FT%TZ > $out/queue_drained
git add -A && git commit -qm "bench: end segment $n ($model)" --allow-empty
git rev-parse HEAD > $out/end_commit
