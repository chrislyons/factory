#!/usr/bin/env bash
# agent-add.sh — Provision a new factory agent end-to-end.
#
# Required: --name, --port, --model, --matrix-user
# Optional: --prefix (default: first 3 chars uppercased), --description
#
# Execution order (idempotent):
#   1. Validate (SSH, duplicates, port, ruamel.yaml)
#   2. Create local directory structure
#   3. Append to constants.ts (cross-signing)
#   4. Append to agent-config.yaml (via Python helper)
#   5. Write Hermes profile on Whitebox (SSH heredoc)
#   6. Sync config + reload coordinator
#   7. Print completion checklist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WHITEBOX="whitebox"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
NAME=""
PORT=""
MODEL=""
MATRIX_USER=""
PREFIX=""
DESCRIPTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)       NAME="$2"; shift 2 ;;
    --port)       PORT="$2"; shift 2 ;;
    --model)      MODEL="$2"; shift 2 ;;
    --matrix-user) MATRIX_USER="$2"; shift 2 ;;
    --prefix)     PREFIX="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1"; exit 1 ;;
  esac
done

# Lowercase name, uppercase prefix (portable — macOS ships bash 3.2)
NAME="$(echo "$NAME" | tr '[:upper:]' '[:lower:]')"
if [[ -z "$PREFIX" ]]; then
  PREFIX="$(echo "${NAME:0:3}" | tr '[:lower:]' '[:upper:]')"
else
  PREFIX="$(echo "$PREFIX" | tr '[:lower:]' '[:upper:]')"
fi
NAME_UPPER="$(echo "$NAME" | tr '[:lower:]' '[:upper:]')"
NAME_CAP="$(echo "${NAME:0:1}" | tr '[:lower:]' '[:upper:]')${NAME:1}"
DESCRIPTION="${DESCRIPTION:-$NAME_CAP agent}"
TOKEN_ENV="MATRIX_TOKEN_PAN_${NAME_UPPER}"

# Required args
for var in NAME PORT MODEL MATRIX_USER; do
  val="${!var}"
  if [[ -z "$val" ]]; then
    echo "ERROR: --$(echo "$var" | tr '[:upper:]' '[:lower:]') is required"
    exit 1
  fi
done

CONFIG_FILE="$REPO_ROOT/agents/ig88/config/agent-config.yaml"
CONSTANTS_FILE="$REPO_ROOT/scripts/matrix-cross-sign/utils/constants.ts"
PORTS_CSV="$REPO_ROOT/infra/ports.csv"
AGENT_DIR="$REPO_ROOT/agents/$NAME"

echo "=== Factory Agent Provisioning ==="
echo "  Name:        $NAME"
echo "  Prefix:      $PREFIX"
echo "  Port:        $PORT"
echo "  Model:       $MODEL"
echo "  Matrix user: $MATRIX_USER"
echo "  Token env:   $TOKEN_ENV"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Validate
# ---------------------------------------------------------------------------
echo "[1/7] Validating..."

# SSH to Whitebox
if ! ssh -o ConnectTimeout=5 "$WHITEBOX" 'exit 0' 2>/dev/null; then
  echo "ERROR: Cannot reach Whitebox via SSH. Aborting before any writes."
  exit 1
fi
echo "  SSH to Whitebox: OK"

# Agent not already in config
if grep -q "^  ${NAME}:" "$CONFIG_FILE" 2>/dev/null; then
  echo "ERROR: Agent '$NAME' already exists in $CONFIG_FILE"
  exit 1
fi
echo "  Agent not in config: OK"

# Port check in ports.csv
if [[ -f "$PORTS_CSV" ]]; then
  PORT_LINE=$(grep "^${PORT}," "$PORTS_CSV" 2>/dev/null || true)
  if [[ -n "$PORT_LINE" ]]; then
    PORT_STATUS=$(echo "$PORT_LINE" | cut -d',' -f5)
    if [[ "$PORT_STATUS" == "live" ]]; then
      echo "  WARNING: Port $PORT is already 'live' in ports.csv — proceeding anyway"
    else
      echo "  Port $PORT in ports.csv (status: $PORT_STATUS): OK"
    fi
  else
    echo "  WARNING: Port $PORT not found in ports.csv — proceeding anyway"
  fi
fi

# ruamel.yaml check
if ! python3 -c "import ruamel.yaml" 2>/dev/null; then
  echo "ERROR: ruamel.yaml not installed."
  echo "  Install with: pip3 install ruamel.yaml"
  exit 1
fi
echo "  ruamel.yaml: OK"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Local directory structure
# ---------------------------------------------------------------------------
echo "[2/7] Creating local directory structure..."

if [[ -d "$AGENT_DIR" ]]; then
  echo "  Directory already exists: $AGENT_DIR (skipping)"
else
  mkdir -p "$AGENT_DIR"/{docs/"$PREFIX",src,tests}

  # CLAUDE.md from template
  cat > "$AGENT_DIR/CLAUDE.md" <<CLAUDE_EOF
# $NAME_CAP — Identity & Operational Rules

**Agent:** $NAME_CAP | **Trust Level:** L2 | **PREFIX:** $PREFIX

---

## Soul

> Write this section manually — see agents/boot/CLAUDE.md for structure.

---

## Principles

> Write this section manually.

---

## Trust Level & Domain

**L2** (domain TBD)
- Read and analyze: auto-approved
- Write/Edit within worker_cwd: auto-approved
- Dangerous Bash commands: requires Matrix approval

---

## Tools

Inherits shared tools from agents/CLAUDE.md.

---

## Memory Filesystem

**Namespace:** ~/factory/agents/$NAME/memory/$NAME/

| File | Purpose |
|------|---------|
| scratchpad.md | Working notes for current session |
| episodic/YYYY-MM-DD-session-N.md | Session summaries |
| index.md | Navigation map |

---

## Repository Conventions

**Workspace:** Inherits conventions from ~/dev/CLAUDE.md
**Documentation PREFIX:** $PREFIX

### Naming Convention

**Pattern:** \`{${PREFIX}###} {Verbose Title}.md\`

### Project Structure

\`\`\`
$NAME/
├── CLAUDE.md
├── docs/$PREFIX/
├── src/
├── tests/
├── .claudeignore
└── .gitignore
\`\`\`
CLAUDE_EOF

  # Copy .gitignore and .claudeignore from boot
  BOOT_DIR="$REPO_ROOT/agents/boot"
  if [[ -f "$BOOT_DIR/.gitignore" ]]; then
    cp "$BOOT_DIR/.gitignore" "$AGENT_DIR/.gitignore"
  fi
  if [[ -f "$BOOT_DIR/.claudeignore" ]]; then
    cp "$BOOT_DIR/.claudeignore" "$AGENT_DIR/.claudeignore"
  fi

  echo "  Created: $AGENT_DIR/"
  echo "  NOTE: soul.md, principles.md, agents.md are NOT created — write these manually"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 3: Update constants.ts
# ---------------------------------------------------------------------------
echo "[3/7] Updating constants.ts..."

if grep -q "\"$MATRIX_USER\"" "$CONSTANTS_FILE" 2>/dev/null; then
  echo "  $MATRIX_USER already in BOT_USERS (skipping)"
else
  # Append to BOT_USERS array (before closing ] as const;)
  sed -i '' "s|] as const;|  \"$MATRIX_USER\",\n] as const;|" "$CONSTANTS_FILE"

  # Append to BOT_AGENT_NAMES record (before closing };)
  # Find the last }; in the file (the one closing BOT_AGENT_NAMES)
  sed -i '' "/^};$/i\\
\\  \"$MATRIX_USER\": \"$NAME\",
" "$CONSTANTS_FILE"

  echo "  Added $MATRIX_USER to BOT_USERS and BOT_AGENT_NAMES"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 4: Update agent-config.yaml
# ---------------------------------------------------------------------------
echo "[4/7] Updating agent-config.yaml..."

python3 "$SCRIPT_DIR/agent-add-config.py" \
  --name "$NAME" \
  --matrix-user "$MATRIX_USER" \
  --port "$PORT" \
  --model "$MODEL" \
  --description "$DESCRIPTION" \
  --config "$CONFIG_FILE"
echo ""

# ---------------------------------------------------------------------------
# Step 5: Write Hermes profile on Whitebox
# ---------------------------------------------------------------------------
echo "[5/7] Writing Hermes profile on Whitebox..."

ssh "$WHITEBOX" bash -s <<HERMES_EOF
mkdir -p ~/.hermes/profiles/$NAME
cat > ~/.hermes/profiles/$NAME/config.yaml <<'PROFILE_EOF'
# $NAME Hermes profile — local MLX-LM only (sovereign, TOS compliant)
# Port $PORT identified as $NAME agent slot (WHB008: slots are stable, models are mutable)
model: $MODEL
base_url: http://127.0.0.1:$PORT/v1
fallback_providers: []
toolsets: []
agent:
  max_turns: 90
  tool_use_enforcement: none
terminal:
  backend: local
  cwd: /Users/nesbitt/dev/factory/agents/$NAME
  persistent_shell: true
display:
  compact: true
  streaming: false
  show_cost: false
smart_model_routing:
  enabled: true
  max_simple_chars: 160
  max_simple_words: 28
  cheap_model:
    base_url: http://127.0.0.1:41963/v1
    model: /Users/nesbitt/models/LFM2.5-1.2B-Thinking-MLX-6bit
memory:
  memory_enabled: false
  user_profile_enabled: false
approvals:
  mode: auto
gateway: {}
auxiliary:
  compression:
    base_url: http://127.0.0.1:41963/v1
  approval:
    base_url: http://127.0.0.1:41963/v1
mcp_servers:
  qdrant-mcp:
    url: http://localhost:41460/mcp
  research-mcp:
    url: http://localhost:41470/mcp
  graphiti:
    url: http://localhost:41440/sse
    enabled: false
PROFILE_EOF
echo "  Wrote: ~/.hermes/profiles/$NAME/config.yaml"
HERMES_EOF
echo ""

# ---------------------------------------------------------------------------
# Step 6: Sync config + reload coordinator
# ---------------------------------------------------------------------------
echo "[6/7] Syncing config and reloading coordinator..."
cd "$REPO_ROOT"
make sync-config
make reload
echo ""

# ---------------------------------------------------------------------------
# Step 7: Completion checklist
# ---------------------------------------------------------------------------
echo "=== Provisioning Complete ==="
echo ""
echo "  agents/$NAME/           created"
echo "  Hermes profile           whitebox:~/.hermes/profiles/$NAME/config.yaml"
echo "  agent-config.yaml        updated and synced"
echo "  constants.ts             $MATRIX_USER added to BOT_USERS"
echo "  Coordinator              reloaded"
echo ""
echo "Manual steps remaining:"
echo "[ ] 1. Create Matrix account: https://app.element.io/#/register"
echo "        Username: $NAME  Homeserver: matrix.org"
echo "[ ] 2. Log in via Element -> point at http://127.0.0.1:41200 (Pantalaimon)"
echo "        One interactive login registers the account with Pan for E2EE"
echo "[ ] 3. Get access token -> add to BWS as $TOKEN_ENV"
echo "        Add BWS UUID to com.bootindustries.coordinator-rs.plist on Whitebox"
echo "[ ] 4. Run E2EE cross-signing:"
echo "        cd scripts/matrix-cross-sign"
echo "        npx tsx bot-trust.ts setup-bot --user \"$MATRIX_USER\""
echo "        npx tsx bot-trust.ts trust-users"
echo "[ ] 5. Write agents/$NAME/soul.md, principles.md, agents.md"
echo "[ ] 6. Create launchd plist: plists/com.bootindustries.mlx-lm-$PORT.plist"
echo "        Load on Whitebox: launchctl load ~/Library/LaunchAgents/...plist"
echo "[ ] 7. Verify model on Whitebox: $MODEL"
echo "[ ] 8. infra/ports.csv — change $PORT status: reserved -> live"
echo "[ ] 9. Create Matrix room in Element, add room entry to agent-config.yaml rooms:"
echo ""
