#!/bin/zsh
# One daily run from this checkout. Used by the launchd agent (see com.hungryhunt.daily.plist.example)
# as a laptop fallback until the GitHub Actions schedule has its secrets.
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG="${HUNGRY_HUNT_LOG:-$HOME/Library/Logs/hungry_hunt.log}"
echo "=== $(date '+%Y-%m-%d %H:%M %Z') run ===" >> "$LOG"
.venv/bin/hunt run >> "$LOG" 2>&1
echo "exit $?" >> "$LOG"
