# FCT042 Stream 2 Infrastructure Sprint — Port Allocation and Matrix MCP Deployment

Infrastructure sprint following FCT041 (paper trading readiness). Focus: deploying Matrix MCP servers on Whitebox and rationalizing the 844x MCP port block into a clean, consistent allocation.

**Predecessor:** FCT041 | **References:** FCT033 S8, FCT035, FCT036

---

## 1. Matrix MCP Deployment (Whitebox)

Two matrix-mcp instances deployed on Whitebox using the existing source at `/Users/nesbitt/projects/matrix-mcp/`. The `dist/` directory was already built; `npm install` completed with no issues.

### Configuration

Both instances share the same connection pattern:

- **Auth mode:** Pan access tokens from BWS (non-OAuth — uses `MATRIX_ACCESS_TOKEN` env var fallback path)
- **Homeserver:** Pantalaimon on `localhost:8009` via `MATRIX_HOMESERVER_URL`
- **Binding:** `0.0.0.0` (`LISTEN_HOST`) to allow Tailscale access from Cloudkicker
- **Management:** launchd plists with KeepAlive

### Instance Details

| Instance | Identity | Port | Plist Label |
|----------|----------|------|-------------|
| Coord | @coord:matrix.org | :8440 | `com.bootindustries.matrix-mcp-coord` |
| Boot | @boot.industries:matrix.org | :8448 | `com.bootindustries.matrix-mcp-boot` |

Both plists created and loaded on Whitebox. Servers start, bind their ports, and accept TCP connections.

### Known Issues

**MCP handshake hang.** `curl` POST to `/mcp` on both instances times out. The servers listen and accept connections but do not complete the MCP initialize handshake. Likely cause: Matrix sync blocking on the first request before the MCP protocol layer gets a chance to respond. Needs debugging — may require an async initialization path or a pre-warmed sync state.

**DM room access limitation.** Neither Boot nor Coord can read the IG-88 DM room (`!ReiEgMIHlHqCVZwfTY:matrix.org`). DM rooms on Matrix are scoped to the two participants (Chris and the agent), so a matrix-mcp instance logged in as Boot or Coord has no membership. Resolving this requires either:

- A matrix-mcp instance logged in as Chris or IG-88
- Inviting a third identity to the DM room (changes room semantics)
- Using a shared "operations" room instead of DMs for tool-mediated communication

---

## 2. Port Allocation Reshuffle

The 844x MCP port block was inconsistent — Qdrant MCP sat on 8446, Research MCP on 8447, with gaps. This sprint consolidated all MCP services into a clean sequential block.

### Before / After

| Port | Before | After |
|------|--------|-------|
| 8440 | (unassigned) | Matrix MCP Coord (new) |
| 8442 | (unassigned) | Qdrant MCP (moved from 8446) |
| 8443 | (unassigned) | Research MCP (moved from 8447) |
| 8444 | Graphiti MCP | Graphiti MCP (unchanged) |
| 8448 | (unassigned) | Matrix MCP Boot (new) |

Pantalaimon remains on `:8009`. Moving it would cascade through coordinator-rs YAML config, all agent identity files, and every matrix-mcp plist — high blast radius for no functional gain.

### Files Updated

- **Whitebox launchd plists:** `com.bootindustries.qdrant-mcp` and `com.bootindustries.research-mcp` updated to new ports; both matrix-mcp plists created fresh
- **`~/.mcp.json` (Cloudkicker global):** All four MCP server URLs updated to Whitebox IP with new port numbers
- **`~/dev/research-vault/.mcp.json`:** URL updated to Whitebox IP + new port (8443)
- **Factory `CLAUDE.md` port table:** Already reflected the new allocation prior to this doc

---

## 3. Master Port Table

Created `infra/ports.csv` as the single source of truth for all Whitebox service port allocations. The CSV contains 19 entries spanning:

| Range | Services |
|-------|----------|
| 6333-6334 | Qdrant (HTTP + gRPC) |
| 8009 | Pantalaimon (E2EE proxy) |
| 8440-8448 | MCP servers (Matrix, Qdrant, Research, Graphiti) |
| 41910 | Portal Caddy |
| 41911 | GSD sidecar |
| 41914 | Auth sidecar |
| 41920-41939 | Preview slots (reserved) |
| 41940-41949 | Development (reserved) |
| 41950-41959 | Coordinator HTTP API (planned) |
| 41960-41963 | MLX-LM inference (4 model slots) |

Any future port allocation should be recorded in `infra/ports.csv` before deployment.

---

## 4. Outstanding: First Paper Trade Cycle (Step 3c)

This is a manual step requiring Chris to DM IG-88 via Matrix:

1. Ask IG-88 to run a full **Regime -> Scanner -> Narrative -> Governor** cycle
2. Log output to `cycles/C002.md`
3. If cycle produces a `TRADE` signal, log to `trades.csv` as T001 with `dryRun:true`
4. `NO_TRADE` is a valid outcome — document with full reasoning chain

This is the final gate before beginning the 100-trade validation sprint defined in FCT033 S8.

---

## 5. Next Steps

1. **Debug Matrix MCP handshake hang** — investigate Pan token sync blocking, test with pre-warmed sync token
2. **Decide Matrix MCP identity strategy** for IG-88 DM room access (Chris instance vs. shared room)
3. **Scope Pantalaimon port move** (8009 -> 8010) as a separate, isolated change if ever needed
4. **Execute first paper trade cycle** (manual, Chris-initiated)
5. **Begin 100-trade validation sprint** (FCT033 S8) once cycle 1 completes successfully

---

**Created:** 2026-03-23 | **Status:** Sprint complete, two blockers open (handshake hang, DM room access)
