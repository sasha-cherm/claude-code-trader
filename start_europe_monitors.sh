#!/bin/bash
cd /home/cctrd/cc-trader-agent

# Wait until 18:00 UTC
TARGET=$(date -u -d "2026-03-16 18:00:00" +%s)
NOW=$(date -u +%s)
WAIT=$((TARGET - NOW))
if [ $WAIT -gt 0 ]; then
    echo "Sleeping $WAIT seconds until 18:00 UTC..."
    sleep $WAIT
fi

echo "Starting Europe + South monitors at $(date -u)"
python3 -u near_res_sunday.py > logs/near_res_europe_$(date -u +%Y%m%d_%H%M).log 2>&1 &
echo "Europe PID: $!"
python3 -u near_res_sunday.py --south > logs/near_res_south_$(date -u +%Y%m%d_%H%M).log 2>&1 &
echo "South PID: $!"
