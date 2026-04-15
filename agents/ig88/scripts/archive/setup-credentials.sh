#!/usr/bin/env bash
# Setup secure credentials for Matrix agents
# Usage: ./setup-credentials.sh

set -euo pipefail

CREDENTIALS_DIR="/etc/ig88/credentials"
SYSTEMD_OVERRIDE_DIR="/etc/systemd/system/matrix-coordinator.service.d"
OVERRIDE_FILE="${SYSTEMD_OVERRIDE_DIR}/credentials.conf"

echo "==================================================="
echo "  IG-88 Secure Credential Setup"
echo "==================================================="
echo ""

# Check if running with sudo
if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run with sudo"
   echo "Usage: sudo ./setup-credentials.sh"
   exit 1
fi

echo "Step 1: Creating credentials directory..."
mkdir -p "${CREDENTIALS_DIR}"
chmod 700 "${CREDENTIALS_DIR}"
echo "  ✓ Created ${CREDENTIALS_DIR} (mode 700)"
echo ""

# Prompt for agent passwords
declare -A PASSWORDS

echo "Step 2: Enter passwords for each agent"
echo "  (Passwords will not be echoed to the screen)"
echo ""

for agent in boot kelk ig88; do
  read -sp "  Password for ${agent}: " password
  echo ""

  if [[ -z "$password" ]]; then
    echo "Error: Password cannot be empty"
    exit 1
  fi

  PASSWORDS[$agent]=$password
done

echo ""
echo "Step 3: Writing credential files..."

for agent in "${!PASSWORDS[@]}"; do
  credential_file="${CREDENTIALS_DIR}/${agent}_password"
  echo -n "${PASSWORDS[$agent]}" > "$credential_file"
  chmod 600 "$credential_file"
  echo "  ✓ Wrote ${credential_file} (mode 600)"
done

echo ""
echo "Step 4: Creating systemd service override..."

mkdir -p "${SYSTEMD_OVERRIDE_DIR}"

cat > "${OVERRIDE_FILE}" <<EOF
[Service]
LoadCredential=boot_password:${CREDENTIALS_DIR}/boot_password
LoadCredential=kelk_password:${CREDENTIALS_DIR}/kelk_password
LoadCredential=ig88_password:${CREDENTIALS_DIR}/ig88_password
EOF

chmod 644 "${OVERRIDE_FILE}"
echo "  ✓ Created ${OVERRIDE_FILE}"
echo ""

echo "Step 5: Reloading systemd daemon..."
systemctl daemon-reload
echo "  ✓ Systemd daemon reloaded"
echo ""

echo "==================================================="
echo "  Setup Complete!"
echo "==================================================="
echo ""
echo "Credentials stored in: ${CREDENTIALS_DIR}"
echo "Systemd override: ${OVERRIDE_FILE}"
echo ""
echo "Next steps:"
echo "  1. Restart the matrix-coordinator service:"
echo "     sudo systemctl restart matrix-coordinator"
echo ""
echo "  2. Check service status:"
echo "     sudo systemctl status matrix-coordinator"
echo ""
echo "  3. Monitor logs for token refresh:"
echo "     sudo journalctl -u matrix-coordinator -f"
echo ""
echo "Security notes:"
echo "  - Credential files are owned by root with 600 permissions"
echo "  - Only the matrix-coordinator service can access credentials"
echo "  - Credentials are injected at runtime via systemd LoadCredential"
echo ""
