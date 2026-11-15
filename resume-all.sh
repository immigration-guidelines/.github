#!/usr/bin/env bash
# Re-run every download script after an interruption. Each script skips files
# it already has, so this only fetches what is missing. Logs go to logs/.
#
#   ./resume-all.sh            # run them one after another (gentle on a slow link)
#   ./resume-all.sh --parallel # run them all at once
#
# Sweden is left out on purpose: its script would walk the Migration Agency's
# database for 8-10 hours. Run "python3 download_se.py" yourself if you want that.

cd "$(dirname "$0")"
mkdir -p logs
jobs_list=("download.py uk")
for s in download_*.py; do
  [ "$s" = "download_se.py" ] && continue
  jobs_list+=("$s")
done

run() {
  local name="${1// /_}"
  echo "$(date +%H:%M) start  $1"
  python3 $1 > "logs/${name%.py}.log" 2>&1
  echo "$(date +%H:%M) done   $1 (exit $?)"
}

if [ "${1:-}" = "--parallel" ]; then
  for j in "${jobs_list[@]}"; do run "$j" & done
  wait
else
  for j in "${jobs_list[@]}"; do run "$j"; done
fi
du -sh */ */coi/ 2>/dev/null
