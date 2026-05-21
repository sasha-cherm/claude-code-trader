( nohup python3 -u btc_15m_mm_live.py \
      > logs/btc_15m_mm_live_$(date -u +%Y%m%d_%H%M).log 2>&1 < /dev/null & )
