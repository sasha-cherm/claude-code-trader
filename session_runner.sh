#!/usr/bin/env bash
set -euo pipefail
DIR="/home/cctrd/cc-trader-agent"
mkdir -p "$DIR/logs"
LOG="$DIR/logs/session_$(date +%Y%m%d_%H%M%S).log"

git -C "$DIR" pull --ff-only 2>/dev/null || true

PROMPT="$(cat "$DIR/RULES.md")

=== CURRENT STATE $(date -Iseconds) ===
Recent git log:
$(git -C "$DIR" log --oneline -8 2>/dev/null || echo 'no commits yet')

Files in project (excluding .git, .env, logs):
$(find "$DIR" -not -path '*/.git/*' -not -name '.env' -not -path '*/logs/*' -not -name '*.log' | sort | sed "s|$DIR/||" | grep -v '^$')
=== END STATE ==="

claude -p "$PROMPT" --dangerouslySkipPermissions 2>&1 | tee -a "$LOG"
