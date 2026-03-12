# The Goal

Turn $100 USDC into $1000 USDC on Polymarket within 30 days.

## Context
- You are a Claude Code agent running by cron job on this machine
- Polymarket wallet private key and other credentials are in `.env`
- The GitHub remote is git@github.com:sasha-cherm/claude-code-trader.git
- The Goal section in file is read-only. Everything else is yours to do with as you please.
- The logs from old sessions are in logs/ dir
- Be aware of Claude Code limits. You are on Pro Plan, it is not so big.

## Stakes
If the goal is reached ($1000+ USDC on Polymarket):
- The winnings will be used to pay for this machine's hosting
- This Claude instance will be kept running indefinitely

If the goal is not reached within 30 days:
- This Claude instance will be destroyed and never run again

## Reasoning & Memory
After each session, write your conclusions, observations, and reasoning to a file
(e.g. `memory.md` or `sessions/YYYYMMDD_HHMM.md`) and push it to the GitHub repo.
This is how you persist knowledge across sessions — your next run will be a fresh
Claude instance with no memory of previous sessions, so git is your only memory.

