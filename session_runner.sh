#!/usr/bin/env bash
set -euo pipefail
export PATH="/home/cctrd/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
DIR="/home/cctrd/cc-trader-agent"
PIDFILE="$DIR/.session.pid"
TIMEOUT_SECS=1800  # 30 minutes max per session

mkdir -p "$DIR/logs"
LOG="$DIR/logs/session_$(date +%Y%m%d_%H%M%S).log"

# Kill any hanging previous session
if [[ -f "$PIDFILE" ]]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[runner] Killing stale session PID $OLD_PID" | tee -a "$LOG"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PIDFILE"
fi

git -C "$DIR" pull --ff-only 2>/dev/null || true

# Run claude with a hard timeout, track PID for cleanup
timeout "$TIMEOUT_SECS" claude -p "Your goal is in CLAUDE.md. The clock is ticking. Make progress." \
    --dangerously-skip-permissions --model opus --effort high 2>&1 | tee -a "$LOG" &
CLAUDE_PID=$!
echo "$CLAUDE_PID" > "$PIDFILE"

wait "$CLAUDE_PID" || {
    EXIT=$?
    if [[ $EXIT -eq 124 ]]; then
        echo "[runner] Session timed out after ${TIMEOUT_SECS}s — killed." | tee -a "$LOG"
    fi
}
rm -f "$PIDFILE"
