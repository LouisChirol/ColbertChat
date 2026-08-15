#!/usr/bin/env bash
# Run full BOFiP embed in a detached tmux session (resumable via content-hash tracking).
set -euo pipefail

SESSION_NAME="${BOFIP_TMUX_SESSION:-turgot-bofip}"
DATABASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="${BOFIP_INGEST_LOG:-/tmp/bofip_ingest.log}"
MAX_COST_USD="${BOFIP_MAX_COST_USD:-2.50}"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Session '$SESSION_NAME' already exists."
  echo "  Attach:  tmux attach -t $SESSION_NAME"
  echo "  Status:  tail -f $LOG_FILE"
  exit 0
fi

cd "$DATABASE_DIR"
tmux new-session -d -s "$SESSION_NAME" \
  "uv run python -m sources.bofip.ingest --max-cost-usd $MAX_COST_USD 2>&1 | tee -a $LOG_FILE; echo; echo '=== BOFiP ingest finished (exit \$?) ==='; read -p 'Press enter to close pane...' _"

echo "Started BOFiP ingest in tmux session: $SESSION_NAME"
echo "  Attach:  tmux attach -t $SESSION_NAME"
echo "  Detach:  Ctrl-b then d"
echo "  Log:     tail -f $LOG_FILE"
echo "  Kill:    tmux kill-session -t $SESSION_NAME"
