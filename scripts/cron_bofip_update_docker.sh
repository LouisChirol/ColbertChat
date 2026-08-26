#!/usr/bin/env bash
set -euo pipefail

# Monthly BOFiP download + delta embed (content-hash tracking in bofip_tracking.sqlite3).
REPO="/home/ubuntu/turgot"
LOG_DIR="$REPO/logs"
LOCK_FILE="/tmp/turgot_bofip_update.lock"
BOFIP_MAX_COST_USD="${BOFIP_MAX_COST_USD:-5.00}"

mkdir -p "$LOG_DIR"
TS="$(date +%F_%H-%M-%S)"
LOGFILE="$LOG_DIR/bofip_update_$TS.log"

exec > >(tee -a "$LOGFILE") 2>&1

echo "==== BOFiP updater start: $TS ===="
cd "$REPO"

if [ -f "$REPO/.env" ]; then
  set -a; source "$REPO/.env"; set +a
fi

run_bofip_job() {
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

  docker compose --profile maintenance run --rm db_updater \
    python -m sources.bofip.run_update --max-cost-usd "${BOFIP_MAX_COST_USD}" || exit_code=$?

  docker compose up -d backend || exit_code=$?
  return "$exit_code"
}

if flock -n "$LOCK_FILE" bash -c "$(declare -f run_bofip_job); BOFIP_MAX_COST_USD=${BOFIP_MAX_COST_USD}; run_bofip_job"; then
  echo "==== BOFiP updater done: $(date +%F_%H-%M-%S) ===="
else
  echo "==== BOFiP updater failed or lock held: $(date +%F_%H-%M-%S) ===="
  docker compose up -d backend || true
  exit 1
fi
