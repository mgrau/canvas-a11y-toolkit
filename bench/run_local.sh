#!/bin/zsh
# bench/run_local.sh <workspace> <run-dir> <model-name> [effort] [port]
#
# One-shot benchmark run with Claude Code driving a local llama-server (its
# Anthropic-style /v1/messages endpoint) instead of Anthropic's API, so only
# the model differs from run_claude.sh: same harness, prompt, tools and
# event log. Differences, recorded in run.json:
#   - pushes go through push_queue.py; a worker runs alongside the agent
#     and drains the queue after it stops (bench/task_queue.md);
#   - Panorama findings are copied into _notes/yuja/ by bench/yuja_watch.py
#     running on the instructor's computer;
#   - Claude Code gets an empty config dir (no user skills, plugins or
#     memory) and may not read anything under ~/Library/CloudStorage.
# Run it on the model's machine, in tmux. The server's API key is read from
# ~/local-ai/etc/llm-api-key.txt.
set -u
# effort only labels the run: a local model's thinking level is set on the
# server (Qwen: chat-template reasoning_effort, default xhigh).
ws=${1:A}; out=${2:A}; model=$3; effort=${4:-default}; port=${5:-8091}
TOOLKIT=${0:A:h:h}
mkdir -p $out/claude-config
{ sed '/^## Rules/,$d' $TOOLKIT/bench/task.md; cat $TOOLKIT/bench/task_queue.md
  sed -n '/^## Rules/,$p' $TOOLKIT/bench/task.md; } | sed "s|@TOOLKIT@|$TOOLKIT|g" > $out/prompt.md
python3 - $TOOLKIT/bench/settings.json $out/settings.json <<'EOF'
import json, sys
s = json.load(open(sys.argv[1]))
s["permissions"]["deny"] += [f"{tool}(//Users/mgrau/Library/CloudStorage/**)" for tool in ("Read", "Grep", "Glob", "Edit", "Write")]
json.dump(s, open(sys.argv[2], "w"), indent=2)
EOF
export ANTHROPIC_BASE_URL=http://127.0.0.1:$port
export ANTHROPIC_API_KEY=$(cat ~/local-ai/etc/llm-api-key.txt)
export ANTHROPIC_MODEL=$model ANTHROPIC_SMALL_FAST_MODEL=$model CLAUDE_CODE_SUBAGENT_MODEL=$model
export ANTHROPIC_DEFAULT_OPUS_MODEL=$model ANTHROPIC_DEFAULT_SONNET_MODEL=$model ANTHROPIC_DEFAULT_HAIKU_MODEL=$model
export CLAUDE_CONFIG_DIR=$out/claude-config
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1
# Wait for background subagents however long they take; by default a
# headless run stops them 10 minutes after the main agent's last turn.
# Let a request wait up to an hour: subagents queue for the server's slots.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 API_TIMEOUT_MS=3600000
export PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH
props=$(curl -s -H "Authorization: Bearer $ANTHROPIC_API_KEY" http://127.0.0.1:$port/props)
print -r -- "{\"model\": \"$model\", \"effort\": \"$effort\", \"harness\": \"claude-code $(claude --version | cut -d' ' -f1)\", \"server\": \"llama-server on $(hostname -s):$port\", \"toolkit_commit\": \"$(git -C $TOOLKIT rev-parse --short HEAD)\", \"pushes\": \"push_queue.py worker\", \"panorama\": \"yuja_watch.sh into _notes/yuja/\", \"workspace\": \"$ws\", \"start\": \"$(date -u +%FT%TZ)\"}" > $out/run.json
print -r -- "$props" > $out/server_props.json
cd $ws || exit 1
git add -A && git commit -qm "bench: start ($model)" --allow-empty
git rev-parse HEAD > $out/start_commit
$TOOLKIT/scripts/push_queue.py run > $out/push_worker.log 2>&1 &
worker=$!
claude -p "$(cat $out/prompt.md)" --model $model \
  --output-format stream-json --verbose \
  --settings $out/settings.json --add-dir $TOOLKIT \
  --permission-mode acceptEdits \
  --allowedTools Bash Edit Write MultiEdit NotebookEdit TodoWrite Agent WebFetch WebSearch \
  < /dev/null > $out/events.jsonl 2> $out/stderr.txt
echo $? > $out/exit_code
date -u +%FT%TZ > $out/end
# Finish what the agent queued, then stop the worker.
kill $worker; wait $worker 2>/dev/null
$TOOLKIT/scripts/push_queue.py run --once >> $out/push_worker.log 2>&1
date -u +%FT%TZ > $out/queue_drained
git add -A && git commit -qm "bench: end ($model)" --allow-empty
git rev-parse HEAD > $out/end_commit
