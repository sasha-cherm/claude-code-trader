#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/cctrd/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
DIR="/home/cctrd/cc-trader-agent"
mkdir -p "$DIR/logs"
LOG="$DIR/logs/session_$(date +%Y%m%d_%H%M%S).log"

git -C "$DIR" pull --ff-only 2>/dev/null || true

claude -p "Check the file RULES.md" --dangerously-skip-permissions --model opus --effort high 2>&1 | tee -a "$LOG"
