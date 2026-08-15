#!/usr/bin/env bash
set -euo pipefail

# Absolute repo path on server
REPO="/home/ubuntu/turgot"
LOG_DIR="$REPO/logs"
LOCK_FILE="/tmp/turgot_db_update.lock"

mkdir -p "$LOG_DIR"
TS="$(date +%F_%H-%M-%S)"
LOGFILE="$LOG_DIR/db_update_$TS.log"

# Log everything
exec > >(tee -a "$LOGFILE") 2>&1

echo "==== DB updater start: $TS ===="
cd "$REPO"

# Ensure env for compose interpolation
if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

# Prevent overlapping runs; stop backend during update to avoid DB contention
flock -n "$LOCK_FILE" bash -c '
  set -e
  docker compose stop backend || true
  # Wait up to 30s for backend container to fully stop and release file handles
  for i in $(seq 1 30); do
    if [ -z "$(docker compose ps -q backend)" ] || [ "$(docker inspect -f {{.State.Running}} $(docker compose ps -q backend) 2>/dev/null || echo false)" = "false" ]; then
      break
    fi
    sleep 1
  done
  docker compose --profile maintenance run --rm db_updater
  echo "Running retrieval evaluation set..."
  docker compose run --rm backend python scripts/run_retrieval_eval.py
  docker compose start backend || true
'

echo "==== DB updater done: $(date +%F_%H-%M-%S) ===="