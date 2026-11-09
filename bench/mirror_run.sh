#!/bin/zsh
# bench/mirror_run.sh <host> <remote run dir> <remote workspace> <local run dir> <local workspace mirror> <course workspace>
#
# Follows a run on another machine (run_local.sh) from this one: every 30
# seconds copies the run's event log and status files into <local run dir>,
# and just the workspace files progress.py counts (triage.csv, REVIEW.md,
# the guide and manual .qmd drafts) into <local workspace mirror>, which
# should be outside OneDrive and git: the manual drafts are copyrighted.
# course.toml and .env come from <course workspace> on this computer, so
# progress.py can count pushed pages on Canvas. The local run.json points
# progress.py at the mirror. Stops a minute after the run's end commit.
set -u
host=$1; rrun=$2; rws=$3; run=${4:A}; mirror=${5:A}; course=${6:A}
mkdir -p $run $mirror
cp $course/course.toml $mirror/; cp $course/.env $mirror/ && chmod 600 $mirror/.env
while true; do
  rsync -a --exclude claude-config $host:$rrun/ $run/ 2>/dev/null
  rsync -a --prune-empty-dirs --include '*/' --include '/triage.csv' --include '/REVIEW.md' \
    --include '/guides/*/*.qmd' --include '/manuals/*/*.qmd' --exclude '*' $host:$rws/ $mirror/ 2>/dev/null
  [[ -f $run/run.json ]] && python3 - $run/run.json $mirror <<'PY'
import json, sys
p, ws = sys.argv[1], sys.argv[2]
info = json.load(open(p))
info["remote_workspace"] = info.get("remote_workspace") or info["workspace"]
info["workspace"] = ws
json.dump(info, open(p, "w"))
PY
  [[ -f $run/end_commit ]] && { sleep 60; rsync -a --exclude claude-config $host:$rrun/ $run/; exit 0; }
  sleep 30
done
