# Matrix Multi-Agent Coordinator Plan

## Overview

Build a Matrix-based multi-agent system where four personas (You, Kelk, Boot, IG88) coordinate work across multiple machines via Claude workers.

## Architecture

```
@chrislyons (you) ─── Element/Matrix ───┐
                                        │
                    ┌───────────────────┴───────────────────┐
                    │                                       │
                    ▼                                       ▼
            ┌───────────────┐                       ┌───────────────┐
            │     KELK      │                       │     IG88      │
            │   (personal)  │                       │   (trading)   │
            │   PREFIX: KLK │                       │  PREFIX: IG88 │
            └───────┬───────┘                       └───────┬───────┘
                    │                                       │
                    ▼                                       ▼
            ┌───────────────┐                       ┌───────────────┐
            │     BOOT      │                       │   Scanner +   │
            │  (business)   │                       │   Claude      │
            │  dev projects │                       │  (Docker)     │
            └───────┬───────┘                       └───────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    Claude      Claude      Claude/OLMo
    (RP5)    (Cloudkicker)   (Mac/API)
```

## Matrix Accounts to Create

| Account | Purpose | Rooms |
|---------|---------|-------|
| @kelk:matrix.org | Personal assistant, coordinator | #kelk, #personal |
| @boot:matrix.org | Business ops, dev projects | #orpheus, #carbon, #hotbox, #wordbird, #helm, #boot |
| @ig88bot:matrix.org | Trading (exists) | #trading |

## Matrix Rooms to Create

All rooms: **Private, Encryption OFF, invite bots + @chrislyons**

| Room | Primary Agent | Worker Target |
|------|---------------|---------------|
| #kelk | @kelk | RP5 local |
| #personal | @kelk | RP5 local |
| #boot | @boot | RP5 local |
| #orpheus | @boot | Cloudkicker (tmux: orpheus) |
| #carbon | @boot | Cloudkicker (tmux: carbon) |
| #hotbox | @boot | Cloudkicker (tmux: hotbox) |
| #wordbird | @boot | Mac (tmux: wordbird) |
| #helm | @boot | Mac (tmux: helm) |
| #trading | @ig88bot | RP5 Docker |
| #general | @mention required | Any |

## Hybrid Session Mode

All dev work runs in tmux sessions:
- Matrix sends commands → tmux session
- User can attach via Blink/mosh to watch/intervene
- Response includes attach hint: `📺 mosh cloudkicker && tmux attach -t orpheus`

## Implementation Steps

### Phase 1: Matrix Setup (Manual in Element)

1. Create @kelk:matrix.org account
2. Create @boot:matrix.org account
3. Get access tokens via curl login
4. Save tokens to ig88:
   ```
   ~/.config/ig88/matrix_token_kelk
   ~/.config/ig88/matrix_token_boot
   ```
5. Create Matrix Space "Claude Agents"
6. Create rooms (encryption OFF)
7. Invite bots to respective rooms
8. Get room IDs (Settings → Advanced)

### Phase 2: Config Update

Update `~/projects/ig88/config/agent-config.yaml`:

1. Add `kelk` and `boot` agents
2. Update room IDs with real values
3. Add Mac as remote device
4. Set tmux_session for all dev rooms

### Phase 3: Coordinator Enhancement

Modify `~/projects/ig88/src/matrix-coordinator.ts`:

1. Add session attach hint to responses
2. Ensure all dev rooms use tmux mode
3. Add agent-to-agent delegation (Kelk → Boot, etc.)
4. Add explicit worker override parsing (`@boot use mac: ...`)

### Phase 4: Systemd Service

Create `~/.config/systemd/user/matrix-coordinator.service`:
```ini
[Unit]
Description=Matrix Multi-Agent Coordinator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/nesbitt/projects/ig88
ExecStart=/usr/bin/node dist/matrix-coordinator.js
Restart=always
RestartSec=10
Environment=NODE_ENV=production

[Install]
WantedBy=default.target
```

Enable: `systemctl --user enable --now matrix-coordinator`

### Phase 5: SSH Setup

Verify SSH access from ig88:
```bash
ssh cloudkicker "echo ok"  # Should work via Tailscale
ssh mac "echo ok"          # Need to set up
```

Add to `~/.ssh/config` on ig88 if needed.

### Phase 6: Tmux Sessions

Create persistent sessions on worker machines:
```bash
# On Cloudkicker
tmux new-session -d -s orpheus -c ~/dev/orpheus-sdk
tmux new-session -d -s carbon -c ~/dev/carbon-acx
tmux new-session -d -s hotbox -c ~/dev/hotbox

# On Mac
tmux new-session -d -s wordbird -c ~/dev/wordbird
tmux new-session -d -s helm -c ~/dev/helm
```

## Verification

1. Message #orpheus: "What files are in this repo?"
   - @boot should respond
   - Check tmux session received command

2. Attach to session: `mosh cloudkicker && tmux attach -t orpheus`
   - Should see command history

3. Test agent-to-agent: Message #kelk "What's Boot working on?"
   - Kelk should query Boot

4. Test failover: Stop Cloudkicker, message #orpheus
   - Should fallback to RP5 or report unavailable

## Files to Modify

- `ig88:~/projects/ig88/config/agent-config.yaml` - Add agents, real room IDs
- `ig88:~/projects/ig88/src/matrix-coordinator.ts` - Hybrid mode, cross-agent
- `ig88:~/.config/systemd/user/matrix-coordinator.service` - New file
- `ig88:~/.config/ig88/matrix_token_kelk` - New token file
- `ig88:~/.config/ig88/matrix_token_boot` - New token file

## Dependencies

- Matrix accounts created manually
- Room IDs obtained manually
- SSH keys set up between machines
- Tmux installed on all worker machines
- Claude Code installed on all worker machines
