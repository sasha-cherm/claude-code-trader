#!/bin/bash
# Launch CL near-res monitors for March 17, 2026
# Run this at 18:00 UTC (or earlier) — it starts both CL scripts
cd /home/cctrd/cc-trader-agent

echo "=== Launching CL monitors at $(date -u) ==="

# CL Early: Sporting vs Bodo/Glimt (17:45 kickoff, near-res 19:00-19:30)
python3 -u near_res_cl_mar17.py --early > logs/cl_early_$(date -u +%Y%m%d_%H%M).log 2>&1 &
echo "CL Early PID: $!"

# CL Main: Man City vs RM + Chelsea vs PSG + Arsenal vs Leverkusen (20:00 kickoff)
# Starting now captures true pre-game prices before 20:00 kickoff
python3 -u near_res_cl_mar17.py > logs/cl_main_$(date -u +%Y%m%d_%H%M).log 2>&1 &
echo "CL Main PID: $!"

echo "Both CL monitors launched."
