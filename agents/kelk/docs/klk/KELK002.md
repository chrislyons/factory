# Matrix Multi-Agent Coordinator Plan

## Current Status

**Completed:**
- ✅ Matrix accounts: @sir.kelk:matrix.org, @boot.industries:matrix.org, @ig88bot:matrix.org
- ✅ Tokens saved to ig88: ~/.config/ig88/matrix_token_{kelk,boot,ig88}
- ✅ Spaces created: Boot, Kelk, Trading
- ✅ Existing rooms in Boot space: Claudezilla, Hotbox, Listmaker, Ondina, Orpheus SDK, OSD Events
- ✅ Existing rooms in IG88 space: System Alerts, Trade Alerts
- ✅ Coordinator code: ~/projects/ig88/src/matrix-coordinator.ts
- ✅ Systemd service configured
- ✅ SSH from ig88 → cloudkicker working (via keychain)
- ✅ Tmux sessions on cloudkicker: orpheus, carbon, hotbox, wordbird, helm

**Remaining: E2EE Support**

## Problem: Encrypted Rooms + Bots

Matrix E2EE requires client-side encryption. Simple HTTP API calls can't read encrypted messages.

**Solution: [Pantalaimon](https://github.com/matrix-org/pantalaimon)**

Pantalaimon is an E2EE-aware reverse proxy. It handles encryption transparently:
- Bots talk to Pantalaimon (localhost:8009) instead of matrix.org
- Pantalaimon decrypts incoming messages, encrypts outgoing
- Stores encryption keys in a local database

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Coordinator │ ──▶ │ Pantalaimon  │ ──▶ │  matrix.org │
│  (HTTP)     │     │ (E2EE proxy) │     │  (E2EE)     │
└─────────────┘     └──────────────┘     └─────────────┘
```

## Phase 1: Pantalaimon Setup on ig88

### 1.1 Install Dependencies

```bash
# On ig88
sudo apt install libolm-dev python3-pip
pip install pantalaimon
```

### 1.2 Configure Pantalaimon

Create `~/.config/pantalaimon/pantalaimon.conf`:

```ini
[Default]
LogLevel = Warning
SSL = True

[matrix-org]
Homeserver = https://matrix.org
ListenAddress = 127.0.0.1
ListenPort = 8009
SSL = False
IgnoreVerification = True
UseKeyring = False
```

`IgnoreVerification = True` auto-trusts devices (simpler for bots).

### 1.3 Run Pantalaimon as Service

Create `~/.config/systemd/user/pantalaimon.service`:

```ini
[Unit]
Description=Pantalaimon E2EE Proxy
Before=matrix-coordinator.service

[Service]
Type=simple
ExecStart=/home/nesbitt/.local/bin/pantalaimon
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

### 1.4 First Login (per bot)

Each bot must login through Pantalaimon once to establish encryption keys:

```bash
# Start pantalaimon
pantalaimon --log-level debug &

# Login each bot (creates encryption session)
curl -X POST "http://localhost:8009/_matrix/client/r0/login" \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"sir.kelk","password":"PASSWORD"}'
```

## Phase 2: Create ONE Test Encrypted Room

1. Create room "E2EE-Test" in Boot space via Element (encryption ON)
2. Invite @boot.industries:matrix.org
3. Accept invite via Pantalaimon
4. Send test message, verify bot can read it

## Phase 3: Update Coordinator

Modify `matrix-coordinator.ts` to use Pantalaimon:

```typescript
// Change Matrix API base URL
const MATRIX_API = process.env.PANTALAIMON_URL || 'http://localhost:8009';

// All existing API calls work unchanged - Pantalaimon handles E2EE
```

## Phase 4: Update Config with Real Room IDs

Space IDs:
- Boot: `!rstFeKHMUrUXwBKLbE:matrix.org`
- Kelk: `!XSZjbPXZWiYDutvgfe:matrix.org`
- Trading: `!LVABaHbGWXVuWCeAch:matrix.org`

Room IDs (update agent-config.yaml):
- Orpheus SDK: `!DdGujpFMkFtSImKhTr:matrix.org`
- Hotbox: `!DLmhpBBnzlislEmdWC:matrix.org`
- (add others as needed)

## Verification

1. Send encrypted message in E2EE-Test room
2. Check Pantalaimon logs for decryption
3. Coordinator responds successfully
4. Verify message appears encrypted in Element

## Files to Modify

- `ig88:~/.config/pantalaimon/pantalaimon.conf` - New config
- `ig88:~/.config/systemd/user/pantalaimon.service` - New service
- `ig88:~/projects/ig88/src/matrix-coordinator.ts` - Use localhost:8009
- `ig88:~/projects/ig88/config/agent-config.yaml` - Real room IDs

---

## Sources

- [Pantalaimon GitHub](https://github.com/matrix-org/pantalaimon) - Official E2EE proxy
- [Pantalaimon README](https://github.com/matrix-org/pantalaimon/blob/master/README.md) - Installation & config
