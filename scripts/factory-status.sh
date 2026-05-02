#!/bin/bash
# factory-status.sh — Show current status of all Factory services
#
# Usage: factory-status.sh

echo "=== Factory Service Status ==="
echo ""

# FCT091: dual-server topology — SABER on :41961 (mlx_lm wrapper),
# Nemostein on :41966 (vllm-mlx). Either or both may be active.
for slot in "41961:E4B-SABER (mlx_lm wrapper)" "41962:E4B-SABER alt (mlx_lm wrapper)" "41966:Nemostein (vllm-mlx)"; do
  port="${slot%%:*}"
  label="${slot#*:}"
  echo "Model server :${port} — ${label}:"
  if curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    MODEL=$(curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "unknown")
    echo "  Status: UP"
    echo "  Serving: $MODEL"
    # FCT091: scrape /metrics for prefix-cache hit rate (vllm-mlx only)
    METRICS=$(curl -sf --max-time 3 "http://127.0.0.1:${port}/metrics" 2>/dev/null)
    if [ -n "$METRICS" ]; then
      HIT=$(echo "$METRICS" | awk '/^vllm_mlx_cache_hit_rate / {print $2}')
      [ -n "$HIT" ] && echo "  Prefix cache hit rate: ${HIT}"
    fi
  else
    echo "  Status: DOWN"
  fi
  echo ""
done

# Hermes gateways
echo ""
echo "Hermes Gateways:"
for agent in boot kelk ig88; do
  if pgrep -f "hermes.*${agent}.*gateway" >/dev/null 2>&1; then
    echo "  hermes-${agent}: UP"
  else
    echo "  hermes-${agent}: DOWN"
  fi
done

# Memory
echo ""
echo "Memory:"
top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/^/  /'

# Disk
echo ""
echo "Disk (internal):"
df -h / | tail -1 | awk '{printf "  Used: %s / %s (%s free)\n", $3, $2, $4}'

# Model files
echo ""
echo "Models on disk:"
ls -d /Users/nesbitt/models/*/ 2>/dev/null | while read dir; do
  size=$(du -sh "$dir" 2>/dev/null | cut -f1)
  name=$(basename "$dir")
  echo "  $size  $name"
done

echo ""
echo "=== End ==="
