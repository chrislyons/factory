#!/bin/bash
# factory-status.sh — Show current status of all Factory services
#
# Usage: factory-status.sh

echo "=== Factory Service Status ==="
echo ""

# Model server
echo "Model Server (:41961):"
if curl -sf --max-time 3 "http://127.0.0.1:41961/v1/models" >/dev/null 2>&1; then
  MODEL=$(curl -sf --max-time 3 "http://127.0.0.1:41961/v1/models" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "unknown")
  echo "  Status: UP"
  echo "  Model:  $MODEL"
else
  echo "  Status: DOWN"
fi

# Flash-moe (legacy)
echo ""
echo "Flash-MoE (:41966):"
if curl -sf --max-time 3 "http://127.0.0.1:41966/v1/models" >/dev/null 2>&1; then
  echo "  Status: UP (should be decommissioned)"
else
  echo "  Status: DOWN (expected)"
fi

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
