#!/bin/bash
# factory-status.sh — Show current status of all Factory services
#
# Usage: factory-status.sh

echo "=== Factory Service Status ==="
echo ""

# FCT091/FCT092: tri-server topology — Boot/Kelk on E4B-SABER (:41961/:41962),
# Coord aux tier on E2B-SABER (:41963). All via mlx_lm wrapper. :41966 deprecated.
for slot in "41961:E4B-SABER Boot (mlx_lm wrapper)" "41962:E4B-SABER Kelk (mlx_lm wrapper)" "41963:E2B-SABER Coord aux (mlx_lm wrapper)"; do
  port="${slot%%:*}"
  label="${slot#*:}"
  echo "Model server :${port} — ${label}:"
  if curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    # mlx_lm wrapper exposes nanoLLaVA placeholder as data[0]; actual loaded model is the local path entry
    MODEL=$(curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" | python3 -c "import sys,json; d=json.load(sys.stdin); ids=[m['id'] for m in d['data']]; local=[i for i in ids if i.startswith('/')]; print(local[0] if local else ids[0])" 2>/dev/null || echo "unknown")
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
