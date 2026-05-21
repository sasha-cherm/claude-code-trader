#!/bin/bash
cd /home/cctrd/cc-trader-agent

# Wait until 01:00 UTC Mar 17
TARGET=$(date -u -d "2026-03-17 01:00:00" +%s)
NOW=$(date -u +%s)
WAIT=$((TARGET - NOW))
if [ $WAIT -gt 0 ]; then
    echo "Sleeping $WAIT seconds until 01:00 UTC Mar 17..."
    sleep $WAIT
fi

echo "Starting NBA monitor at $(date -u)"
python3 -u near_res_sunday.py --nba > logs/near_res_nba_$(date -u +%Y%m%d_%H%M).log 2>&1 &
echo "NBA PID: $!"
