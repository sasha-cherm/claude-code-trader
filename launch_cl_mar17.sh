#!/bin/bash
# Launch CL near-res monitors for March 17, 2026
# Run at 15:00 UTC to get CL early pre-game prices (17:45 kickoff)
# Run at 18:00 UTC to get CL main + NBA pre-game prices (20:00 kickoff)
cd /home/cctrd/cc-trader-agent

echo "=== Launching monitors at $(date -u) ==="

MODE="${1:-all}"

if [ "$MODE" = "early" ] || [ "$MODE" = "all" ]; then
    # Check if CL early is already running
    if ! pgrep -f "near_res_cl_mar17.py --early" > /dev/null; then
        python3 -u near_res_cl_mar17.py --early > logs/cl_early_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "CL Early PID: $!"
    else
        echo "CL Early already running, skipping."
    fi
fi

if [ "$MODE" = "main" ] || [ "$MODE" = "all" ]; then
    # Check if CL main is already running
    if ! pgrep -f "near_res_cl_mar17.py$" > /dev/null; then
        python3 -u near_res_cl_mar17.py > logs/cl_main_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "CL Main PID: $!"
    else
        echo "CL Main already running, skipping."
    fi
fi

if [ "$MODE" = "nba" ] || [ "$MODE" = "all" ]; then
    # Check if NBA is already running
    if ! pgrep -f "near_res_nba_mar17.py" > /dev/null; then
        python3 -u near_res_nba_mar17.py > logs/nba_mar17_$(date -u +%Y%m%d_%H%M).log 2>&1 &
        echo "NBA PID: $!"
    else
        echo "NBA already running, skipping."
    fi
fi

echo "Launch complete."
