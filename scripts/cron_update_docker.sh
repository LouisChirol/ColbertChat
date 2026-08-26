#!/usr/bin/env bash
set -euo pipefail

# Weekly Service-Public download + delta embed.
REPO="/home/ubuntu/turgot"
LOG_DIR="$REPO/logs"
LOCK_FILE="/tmp/turgot_db_update.lock"

mkdir -p "$LOG_DIR"
TS="$(date +%F_%H-%M-%S)"
LOGFILE="$LOG_DIR/db_update_$TS.log"

exec > >(tee -a "$LOGFILE") 2>&1

echo "==== DB updater start: $TS ===="
cd "$REPO"

if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

run_update_job() {
  set +e
  local exit_code=0

  docker compose --profile maintenance build db_updater
  docker compose stop backend || true
  for i in $(seq 1 30); do
    if [ -z "$(docker compose ps -q backend)" ] || \
       [ "$(docker inspect -f {{.State.Running}} $(docker compose ps -q backend) 2>/dev/null || echo false)" = "false" ]; then
      break
    fi
    sleep 1
  done

  docker compose --profile maintenance run --rm db_updater || exit_code=$?
  if [ "$exit_code" -eq 0 ]; then
    echo "Running retrieval evaluation set..."
    docker compose run --rm backend python scripts/run_retrieval_eval.py || exit_code=$?
  else
    echo "Skipping retrieval eval because db_updater failed (exit $exit_code)"
  fi

  docker compose up -d backend || exit_code=$?
  return "$exit_code"
}

if flock -n "$LOCK_FILE" bash -c "$(declare -f run_update_job); run_update_job"; then
  echo "==== DB updater done: $(date +%F_%H-%M-%S) ===="
else
  echo "==== DB updater failed or lock held: $(date +%F_%H-%M-%S) ===="
  # Ensure backend is up even if flock failed or inner job aborted early
  docker compose up -d backend || true
  exit 1
fi
