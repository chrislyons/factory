#!/bin/bash
# Deploy IG-88 to RP5
# Syncs source, builds, and installs services

set -euo pipefail

RP5_HOST="blackbox"  # Device renamed from ig88
RP5_PROJECT="/home/nesbitt/projects/ig88"
LOCAL_PROJECT="/Users/chrislyons/dev/ig88"

echo "=========================================="
echo "  Deploying IG-88 to RP5"
echo "=========================================="
echo ""

# Sync source files (excluding secrets and build artifacts)
echo "[1/5] Syncing source files..."
rsync -avz --delete \
    --exclude 'node_modules/' \
    --exclude 'dist/' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '*_token' \
    --exclude '*.secret' \
    --exclude '.git/' \
    --exclude '.DS_Store' \
    "${LOCAL_PROJECT}/src/" \
    "${RP5_HOST}:${RP5_PROJECT}/src/"

# Sync config files
echo "[2/5] Syncing configuration..."
rsync -avz \
    --exclude '*.secret.yaml' \
    "${LOCAL_PROJECT}/config/" \
    "${RP5_HOST}:${RP5_PROJECT}/config/"

# Sync scripts
echo "[3/5] Syncing scripts..."
rsync -avz \
    "${LOCAL_PROJECT}/scripts/" \
    "${RP5_HOST}:${RP5_PROJECT}/scripts/"

# Sync MCP servers (excluding build artifacts and deps)
echo "[4/7] Syncing MCP servers..."
rsync -avz --exclude 'node_modules/' --exclude 'dist/' \
    "${LOCAL_PROJECT}/mcp-servers/" \
    "${RP5_HOST}:${RP5_PROJECT}/mcp-servers/"

# Build MCP servers on RP5
echo "[5/7] Building MCP servers on RP5..."
ssh "${RP5_HOST}" "cd ${RP5_PROJECT}/mcp-servers/jupiter-mcp && npm ci --silent && npm run build"
ssh "${RP5_HOST}" "cd ${RP5_PROJECT}/mcp-servers/dexscreener-mcp && npm ci --silent && npm run build"

# Install dependencies and build main src on RP5
echo "[6/7] Building main source on RP5..."
ssh "${RP5_HOST}" "cd ${RP5_PROJECT}/src && npm ci && npm run build"

# Create log directory
ssh "${RP5_HOST}" "mkdir -p ${RP5_PROJECT}/logs"

echo "[7/7] Deployment complete!"
echo ""
echo "To install systemd service:"
echo "  ssh ${RP5_HOST}"
echo "  sudo cp ${RP5_PROJECT}/scripts/matrix-coordinator.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable matrix-coordinator"
echo "  sudo systemctl start matrix-coordinator"
echo ""
echo "To check status:"
echo "  ssh ${RP5_HOST} 'systemctl status matrix-coordinator'"
echo ""
