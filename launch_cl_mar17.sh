#!/bin/bash
# Launch monitors for March 17, 2026
# Modes: early, main, nba, btc, all
# Schedule:
#   13:00 UTC: btc (BTC threshold near-res, 3h before 16:00 resolution)
#   15:00 UTC: early (Sporting/Bodo CL, 17:45 kickoff)
#   18:00 UTC: all (CL main + NBA + BTC if not running)
cd /home/cctrd/cc-trader-agent

echo "=== Launching monitors at $(date -u) ==="

MODE="${1:-all}"

if [ "$MODE" = "btc" ] || [ "$MODE" = "all" ]; then
    if ! pgrep -f "near_res_btc.py" > /dev/null; then
        python3 -u near_res_btc.py --monitor > logs/btc_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "BTC Monitor PID: $!"
    else
        echo "BTC Monitor already running, skipping."
    fi
fi

if [ "$MODE" = "early" ] || [ "$MODE" = "all" ]; then
    if ! pgrep -f "near_res_cl_mar17.py --early" > /dev/null; then
        python3 -u near_res_cl_mar17.py --early > logs/cl_early_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "CL Early PID: $!"
    else
        echo "CL Early already running, skipping."
    fi
fi

if [ "$MODE" = "main" ] || [ "$MODE" = "all" ]; then
    if ! pgrep -f "near_res_cl_mar17.py$" > /dev/null; then
        python3 -u near_res_cl_mar17.py > logs/cl_main_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "CL Main PID: $!"
    else
        echo "CL Main already running, skipping."
    fi
fi

if [ "$MODE" = "nba" ] || [ "$MODE" = "all" ]; then
    if ! pgrep -f "near_res_nba_mar17.py" > /dev/null; then
        python3 -u near_res_nba_mar17.py > logs/nba_mar17_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "NBA PID: $!"
    else
        echo "NBA already running, skipping."
    fi
fi

echo "Launch complete."
