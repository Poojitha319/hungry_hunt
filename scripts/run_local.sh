#!/bin/zsh
# Runs the daily pipeline from this checkout (used by the launchd agent until the cloud run exists).
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "=== $(date '+%Y-%m-%d %H:%M %Z') run ===" >> ~/Library/Logs/hungry_hunt.log
.venv/bin/python -m hunt run >> ~/Library/Logs/hungry_hunt.log 2>&1
echo "exit $?" >> ~/Library/Logs/hungry_hunt.log
