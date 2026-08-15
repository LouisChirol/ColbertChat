# Full flow: download -> update -> keep only *-latest
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python "$SCRIPT_DIR/run_update.py" --cleanup-old-dumps

# Toy test
# python "$SCRIPT_DIR/tests/test_update.py"

# # Skip download, just update current dumps
# python "$SCRIPT_DIR/run_update.py" --skip-download

# # Custom data directories
# python "$SCRIPT_DIR/run_update.py" --data-dirs data/service-public/vosdroits-latest data/service-public/entreprendre-latest

# # Do not cleanup vectors/tracking for files removed from dataset
# python "$SCRIPT_DIR/run_update.py" --no-cleanup-removed