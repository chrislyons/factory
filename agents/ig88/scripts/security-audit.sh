#!/bin/bash
# Security Audit for IG-88 on RP5
# Checks for common security issues

set -euo pipefail

RP5_HOST="${1:-ig88}"
ERRORS=0

echo "=========================================="
echo "  IG-88 Security Audit"
echo "=========================================="
echo ""

# Check for 0.0.0.0 bindings
echo "[1/6] Checking for dangerous network bindings..."
BINDINGS=$(ssh "$RP5_HOST" "ss -tlnp 2>/dev/null | grep -E '0\.0\.0\.0:|:::' | grep -v 'LISTEN.*127\.' || true")
if [ -n "$BINDINGS" ]; then
    echo "  [WARN] Found services bound to all interfaces:"
    echo "$BINDINGS"
    ((ERRORS++))
else
    echo "  [OK] No services bound to 0.0.0.0"
fi

# Check file permissions
echo ""
echo "[2/6] Checking secret file permissions..."
ssh "$RP5_HOST" '
BAD_PERMS=$(find ~/.config/ig88 ~/projects/graphiti -name ".env" -o -name "*_token" -o -name "*.secret" 2>/dev/null | while read f; do
    if [ -f "$f" ]; then
        perms=$(stat -c %a "$f" 2>/dev/null || stat -f %Lp "$f" 2>/dev/null)
        if [ "$perms" != "600" ]; then
            echo "$f ($perms)"
        fi
    fi
done)
if [ -n "$BAD_PERMS" ]; then
    echo "  [WARN] Files with wrong permissions:"
    echo "$BAD_PERMS"
    exit 1
else
    echo "  [OK] All secret files have 600 permissions"
fi
' || ((ERRORS++))

# Check directory permissions
echo ""
echo "[3/6] Checking config directory permissions..."
ssh "$RP5_HOST" '
DIR_PERMS=$(stat -c %a ~/.config/ig88 2>/dev/null || stat -f %Lp ~/.config/ig88 2>/dev/null)
if [ "$DIR_PERMS" != "700" ]; then
    echo "  [WARN] ~/.config/ig88 has permissions $DIR_PERMS (should be 700)"
    exit 1
else
    echo "  [OK] ~/.config/ig88 has 700 permissions"
fi
' || ((ERRORS++))

# Check for exposed secrets in git
echo ""
echo "[4/6] Checking for secrets in git..."
SECRETS_IN_GIT=$(ssh "$RP5_HOST" "cd ~/projects/ig88 && git ls-files | xargs -I {} sh -c 'grep -l \"API_KEY\|TOKEN\|SECRET\|PASSWORD\" \"{}\" 2>/dev/null || true' | head -5")
if [ -n "$SECRETS_IN_GIT" ]; then
    echo "  [WARN] Potential secrets found in git-tracked files:"
    echo "$SECRETS_IN_GIT"
    ((ERRORS++))
else
    echo "  [OK] No obvious secrets in git-tracked files"
fi

# Check Docker security
echo ""
echo "[5/6] Checking Docker container security..."
ssh "$RP5_HOST" '
if docker ps -q 2>/dev/null | head -1 | grep -q .; then
    # Check for privileged containers
    PRIV=$(docker ps --format "{{.Names}}" | xargs -I {} docker inspect {} --format "{{.Name}}: privileged={{.HostConfig.Privileged}}" | grep "true" || true)
    if [ -n "$PRIV" ]; then
        echo "  [WARN] Privileged containers found:"
        echo "$PRIV"
        exit 1
    else
        echo "  [OK] No privileged containers"
    fi
else
    echo "  [INFO] No running containers to check"
fi
' || ((ERRORS++))

# Check auth tokens are set
echo ""
echo "[6/6] Checking authentication tokens..."
ssh "$RP5_HOST" '
if [ -f ~/projects/graphiti/.env ]; then
    if grep -q "^GRAPHITI_AUTH_TOKEN=.\+" ~/projects/graphiti/.env; then
        echo "  [OK] GRAPHITI_AUTH_TOKEN is set"
    else
        echo "  [WARN] GRAPHITI_AUTH_TOKEN is not set"
        exit 1
    fi
else
    echo "  [WARN] .env file not found"
    exit 1
fi
' || ((ERRORS++))

echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo "  AUDIT PASSED - No issues found"
else
    echo "  AUDIT FOUND $ERRORS ISSUE(S)"
fi
echo "=========================================="

exit $ERRORS
