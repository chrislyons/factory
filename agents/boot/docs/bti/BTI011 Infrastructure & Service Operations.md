# BTI011 Infrastructure & Service Operations

**Curriculum:** BKX057 Operations Executive (Boot) | **Module:** 4 of 6
**Status:** DRAFT for gate review
**Version:** 1.0 | **Date:** 2026-02-17

---

## Executive Summary

Infrastructure operations for a multi-agent system on Raspberry Pi 5 requires grounding in three operational layers:

1. **Service Architecture** — Which services run where, and what degrades when one fails
2. **Resource Management** — Graceful degradation bands, thermal constraints, RAM thresholds
3. **Reliability Patterns** — Health checking, failover chains, incident response

This module codifies the operational reality of Blackbox (RP5, 8GB RAM, ARM64) and the coordination infrastructure that maintains Boot, IG-88, and Kelk across service degradation.

**Key Insight:** Infrastructure isn't about uptime—it's about **predictable degradation**. The system is designed to gracefully shed capability rather than crash. This module defines how.

---

## I. Service Architecture — Blackbox (RP5)

### A. Running Services

The Blackbox system (100.87.53.109, Raspberry Pi 5) runs two classes of services:

**Systemd Services (always-on, crash-restarts automatically):**
- **matrix-coordinator** — Routes agent messages, manages Claude sessions, enforces approvals, manages delegation to Cloudkicker
- **ollama** — Local LLM inference (fallback: OLMo 7B, OLMo 3.1 32B for testing)
- **pantalaimon** — Matrix E2EE proxy (localhost-bound, port 41200)
- **heartbeat** — System health monitor (sends metrics to Matrix #system-status room)

**Docker Services (healthchecks built-in, can be manually restarted):**
- **qdrant** (port 41450) — Vector database for semantic search (vault collection, 896+ docs)
- **falkordb** (port 41430) — Graph database backend for Graphiti knowledge graph
- **graphiti** (port 41440) — Knowledge graph MCP server (Tailscale-bound, requires auth)
- **[reverse proxy]** — Assumed running (inferred from agent-config.yaml port mappings)

### B. Service Dependencies

```
matrix-coordinator
├─ Graphiti MCP (http://100.88.222.111:41440/sse)
│  └─ FalkorDB (localhost:41430, internal Docker)
├─ Ollama (localhost:11434, fallback inference)
├─ Pantalaimon (localhost:41200, E2EE relay)
├─ Cloudkicker SSH (100.107.139.115, delegate target)
└─ Claude Code (local child processes, 1-5 concurrent)

Agents (Boot, IG-88, Kelk)
├─ Health Checks
│  ├─ Anthropic API (https://api.anthropic.com/v1/messages)
│  ├─ OpenRouter API (https://openrouter.ai/api/v1/models)
│  └─ Greybox Ollama (http://100.108.183.68:11434/api/tags, every 60s)
└─ Graphiti Search (temporal facts, node search)
```

### C. Network Topology

| Host | IP | Role | Services |
|------|----|----|----------|
| **Blackbox** | 100.87.53.109 | Backbone | Coordinator, Ollama, Pantalaimon, Docker services, agents |
| **Cloudkicker** | 100.107.139.115 | Delegate worker | SSH relay for Opus/Sonnet reasoning (Cloudflare, delegation target) |
| **Greybox** | 100.108.183.68 | LLM fallback | Ollama (OLMo 7B) for local inference when APIs unavailable |
| **r2d2** | 100.108.1.30 | Client | iPhone, Element + Blink SSH |

All on Tailscale mesh. SSH keys pre-shared (blackbox ↔ cloudkicker mutual trust).

---

## II. Resource Constraints — RP5 Graceful Degradation

### A. Memory Management — Four Operational Bands

RP5 has **8GB physical RAM, no swap**. The system operates in four predictable degradation bands:

| Band | Available RAM | State | Agent Behavior | Decision |
|------|---|---|---|---|
| **Healthy** | >4GB | Normal ops | All tools available, Sonnet/Opus in rotation | Capability-first allocation |
| **Constrained** | 2.4–4GB | Moderate load | Haiku preferred, Sonnet gated, 3 concurrent Claude sessions | Performance-first allocation |
| **Degraded** | 1.2–2.4GB | High pressure | Haiku-only, OpenRouter unavailable, 2 concurrent sessions, Graphiti search limited | Throughput-first, reduced scope |
| **Critical** | <1.2GB | Emergency | Haiku-only, local Ollama only, single session, incident response mode | Stop new work, finish in-flight |

**Monitoring:** Heartbeat service samples `/proc/meminfo` every 30 seconds, alerts Boot when crossing thresholds.

**Gradient vs. Cliff:** Bands are *soft* — Boot receives warnings at -20% (e.g., 4.8GB → 4.0GB) and again at threshold crossing. No hard cliff switches. This prevents thrashing.

### B. CPU / Thermal Constraints

RP5 thermal throttle at 70°C. At 65°C, Ollama inference slows ~15%, local models become less reliable.

**Heat Sources:**
- Coordinator (constant, ~30-40°C idle)
- Ollama (spikes during fallback inference, 55-70°C)
- Multi-agent stagger (three concurrent sessions = peak thermal load)

**Tactical:** When temp >65°C, Ollama is deprioritized (upstream Anthropic API preferred). When >70°C, system logs alert and moves to single-session operation.

### C. Network Saturation

SSH tunnels to Cloudkicker (100 Mbps LAN) can become bottleneck during delegation if multiple agents work in parallel. Coordinator staggers agent responses (45s default delay) to smooth SSH session launches.

---

## III. Health Checking & Failover Chain

### A. LLM Provider Health Checking

The coordinator runs a **three-tier failover chain** every 60 seconds (configurable `llm_health_check_interval_ms`):

```
Tier 1: Anthropic (Primary)
├─ Model: Haiku (default)
├─ Fallback: Sonnet
├─ Health Check: https://api.anthropic.com/v1/messages
└─ Latency Target: <2s
        ↓ [fails 3 consecutive checks]
Tier 2: OpenRouter (Fallback)
├─ Model: OLMo 3.1 32B Instruct (reasoning)
├─ Model: MiniMax M2.5 (frontier reasoning)
├─ Model: Kimi K2.5 (reasoning + Chinese)
├─ Health Check: https://openrouter.ai/api/v1/models
└─ Latency Target: <5s
        ↓ [fails 3 consecutive checks]
Tier 3: Greybox Local (Last Resort)
├─ Model: OLMo 7B Instruct (local inference)
├─ Health Check: http://100.108.183.68:11434/api/tags
└─ Latency Target: <1s
        ↓ [fails → incident mode]
Offline Fallback
└─ Queued tasks hold in memory; no new work initiated
```

**Key Properties:**
- Failover is **automatic** (no manual intervention needed for 99% of cases).
- Each provider has 10-second health check timeout. Slow responses = presumed down.
- Fallback to slower tier is **transparent to agents** — same API surface, different model.
- **Circuit breaker:** If 3 consecutive health checks fail, provider is marked down; next check happens 5 minutes later (exponential backoff).

### B. Delegate Session Failover

When Cloudkicker is unreachable (SSH timeout >10s):

1. Coordinator detects SSH connection failure
2. If agent requested delegation, task is **queued with fallback instructions** sent to agent
3. Agent falls back to Haiku local work (recommended) or queues task for when Cloudkicker returns
4. Coordinator retries SSH connectivity every 60s in background

**Cloudkicker Recovery:** When SSH succeeds again, queued delegate sessions resume in FIFO order.

---

## IV. Agent Lifecycle & Operational Degradation

### A. Health Scoring

Each agent (Boot, IG-88, Kelk) maintains a **health score** over a 30-minute window. Score is degraded by:

- **Timeouts** — Claude process exceeds 20-minute timeout → score -0.3
- **Tool rejections** — Invalid tool calls or failed approvals → score -0.2
- **Consecutive failures** — 3 timeouts or 5 tool rejections → circuit breaker triggered

**Circuit Breaker Protocol:**
- When 3 consecutive timeouts occur → agent is placed in "pause" state
- No new tasks assigned for 5 minutes
- During pause, coordinator probes agent health every 30s
- After 5 minutes, agent is brought back online and health score resets

### B. Degradation Thresholds

As health score degrades, the coordinator automatically restricts agent permissions:

| Health Score | Status | Tool Restrictions |
|---|---|---|
| 0.9–1.0 | Healthy | All tools (Read, Write, Bash, Task, etc.) |
| 0.7–0.9 | Caution | Dangerous Bash blocked (rm, sudo, mv); safe tools allowed |
| 0.5–0.7 | Degraded | Write/Edit gated; Bash limited to grep/cat/ls; Task subagents disabled |
| <0.5 | Emergency | Read-only mode; only tool is Graphiti search; Haiku forced |

**Design:** Degradation is **protective not punitive**. Failing agents lose privileges automatically, not arbitrarily.

### C. Timeout Behavior

- **Claude session timeout:** 20 minutes (1,200,000 ms)
- **Approval timeout:** 10 minutes (600,000 ms) — if unapproved, request is re-prompted
- **Health check timeout:** 10 seconds (10,000 ms) — slow provider = presumed down
- **Delegate session timeout:** 45 minutes (2,700,000 ms) — Cloudkicker jobs run longer

If Claude process hangs, coordinator sends SIGTERM after timeout, then SIGKILL if needed.

---

## V. Approval & Access Control — Hook-Based Gating

### A. Approval Architecture

The coordinator intercepts tool calls via `pretool-approval.sh` hook before execution. Hook logic:

1. **Check auto-approve list** — Safe operations (cat docs, git status, ls) are immediately approved
2. **Check dangerous list** — Commands in `always_require_approval` are queued for Matrix approval
3. **For dangerous:** Post approval request to Matrix #backrooms room, wait for @chrislyons to react with ✅
4. **Approval timeout:** After 10 minutes unapproved, re-prompt or deny (configurable)

**Current Auto-Approved Patterns:**
- File reads: `cat ~/dev/*/docs/*`, `cat ~/projects/*/docs/*`
- Git: `git status`, `git diff`, `git log`
- Safe commands: `ls *`, `head *`, `tail *`, `grep *`, `wc *`, `file *`, `pwd`
- Delegation: `~/dev/scripts/session-relay.sh *` (auto-routes to Cloudkicker)

**Always Require Approval:**
- Destructive: `rm *`, `mv *`, `cp *`
- System: `sudo *`, `chmod *`, `chown *`
- Network: `ssh *`, `curl *`, `wget *`
- Execution: `python *`, `node *`, `bash *`, `sh *`

### B. Trust Levels & Authorization Tiers

Three agents, three trust levels:

| Agent | Trust Level | Domains | Auto-Approved | Approval Gate | Notes |
|---|---|---|---|---|---|
| **Boot** | L3 Operator | Development, Documentation, Operations, Infrastructure | Read, Edit (in ~/dev), safe Bash | Dangerous Bash, file deletion, Python execution | Can dispatch to Cloudkicker autonomously |
| **IG-88** | L3 Analyst | Market Analysis, Trading Signals | Read, Bash grep/cat | Dangerous Bash, Write/Edit in all directories | Can request Cloudkicker delegation (Boot delegates) |
| **Kelk** | L2 Advisor | Personal, Scheduling | Read only | All Write/Edit, all Bash | Limited to personal domain; never system ops |

**Approval Delegation** (agent-config.yaml):
- IG-88's tool approvals in #IG-88 Training room are delegated to Boot (line 367)
- Boot is the approval proxy, not Chris, for IG-88's requests

### C. Dangerous Command Patterns

Coordinator blocks commands containing shell metacharacters (`|`, `>`, `<`, `&`, `;`, `$()`) because they enable injection attacks.

Valid: `ssh cloudkicker 'ls ~/dev'` (single-quoted command extracted)
Invalid: `ssh cloudkicker 'cd ~/dev && claude'` (contains `&&`)

---

## VI. Incident Response & Observability

### A. Runbook Categories

| Incident Type | Symptom | Response | Owner |
|---|---|---|---|
| **Service Down** | Heartbeat alerts on Matrix | `systemctl status <service>`, restart if needed | Boot (RP5) |
| **Coordinator Hung** | No Matrix messages for >2 min | `sudo systemctl restart matrix-coordinator` | Boot |
| **Memory Pressure** | Heartbeat alerts >70% RAM usage | Drain queued work to Cloudkicker, reduce concurrent sessions | Boot |
| **Thermal Throttle** | CPU temp >70°C logged | Reduce Ollama inference, prioritize API calls | Boot (tactical) |
| **Agent Timeout Loop** | Same agent times out 3+ times | Trigger circuit breaker manually: `~/projects/ig88/hooks/reset-agent.sh <agent>` | Boot |
| **SSH to Cloudkicker Fails** | Delegation tasks queued but not sent | Retry SSH connectivity, manually trigger `session-relay.sh` if needed | Boot |
| **Graphiti Ingestion Fails** | `add_memory()` succeeds but `search_memory_facts()` empty | Restart FalkorDB, verify Graphiti connectivity, re-ingest | Boot |

### B. Monitoring & Alerting

**Tier 1 (Real-Time Alerts)** — Heartbeat posts to #system-status room:
- Memory crossing thresholds (>70%, <30%)
- CPU thermal approaching 70°C
- Services down or unhealthy
- Agent health score <0.5

**Tier 2 (Logs, On-Demand Review)** — Check journal:
- `journalctl -u matrix-coordinator -f --no-pager` (coordinator logs)
- `journalctl -u ollama -f --no-pager` (Ollama inference)
- `docker logs qdrant --tail 50` (vector search)
- `docker logs falkordb --tail 50` (graph database)

**Tier 3 (Observability Tools)** — Not yet deployed:
- Prometheus (metrics export)
- Grafana (dashboards)
- Opentelemetry (tracing)

These are Phase 2 (documented in BTI009 Phase 1 actions).

---

## VII. Operational Philosophy — Design Principles

### A. Graceful Degradation Over Uptime

**Principle:** The system is *never* fully down. Instead, it degrades predictably.

- Memory constrained? Use Haiku-only, slower but still operational.
- Anthropic API slow? Fall back to OpenRouter or local Ollama.
- Agent unhealthy? Restrict permissions, don't kill the agent.
- Cloudkicker offline? Fall back to local work with Haiku.

This is superior to "maximizing uptime" because failures are *expected* and handled, not feared.

### B. Single-Agent by Default, Multi-Agent for Parallelism

The coordinator is **stateless and single-threaded** (no concurrent message processing). This prevents race conditions and makes debugging straightforward.

Multi-agent work is deliberately stagered (45s delay before secondary agent responds) to prevent collision. Parallelism is opt-in (e.g., Backrooms room has `all_agents_listen: true`), not default.

### C. Trust ≠ Capability

Trust levels (L1-L4) are about *authorization*, not *skill*. A low-trust agent can still run powerful commands if explicitly approved. Trust is a speedup (auto-approval), not a restriction on scope.

### D. Monitoring as Operational Narrative

Heartbeat isn't just metrics—it's the system's voice. Every alert is actionable and terse. No noise. This prevents alert fatigue and keeps Boot focused on what actually matters.

---

## VIII. Deployment & Service Management

### A. Starting Services (Boot Recovery After Outage)

```bash
# Docker services (usually already running, but in case of failure)
docker start falkordb qdrant  # Order matters: FalkorDB first (Graphiti depends on it)
sleep 5
docker start graphiti         # Graphiti depends on FalkorDB healthy

# Systemd services
sudo systemctl start ollama pantalaimon heartbeat
sleep 2
sudo systemctl start matrix-coordinator  # Coordinator last (depends on Ollama, Pantalaimon)

# Verify
docker ps --format "table {{.Names}}\t{{.Status}}"
systemctl status matrix-coordinator ollama pantalaimon heartbeat
```

### B. Service Restart (Graceful Shutdown)

```bash
# Stop agents gracefully
sudo systemctl stop matrix-coordinator   # Stops all Claude sessions

# Stop supporting services
sudo systemctl stop pantalaimon ollama
docker stop graphiti falkordb qdrant

# Restart (reverse order: dependencies first)
docker start falkordb qdrant && sleep 5
docker start graphiti
sudo systemctl start ollama pantalaimon && sleep 2
sudo systemctl start matrix-coordinator
```

### C. Monitoring Service Health

```bash
# Coordinator logs (real-time)
journalctl -u matrix-coordinator -f --no-pager -n 50

# Service status snapshot
systemctl status matrix-coordinator ollama pantalaimon heartbeat --no-pager

# Docker container status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Memory usage (graceful degradation bands)
cat /proc/meminfo | grep -E "^MemTotal|^MemAvailable|^MemFree"

# Temperature (Raspberry Pi)
vcgencmd measure_temp  # If available on this system
```

---

## IX. Current Operational State (Ground Truth)

As of 2026-02-17:

**Systemd Services:**
- matrix-coordinator: Running (verified startup at 2026-02-17T05:03Z)
- ollama, pantalaimon, heartbeat: Status presumed running (last verified restart per systemd state)

**Docker Services:**
- qdrant, falkordb: Presumably running (health checks in agent-config.yaml)
- graphiti: Running (Graphiti MCP status check confirms "ok" and connected to FalkorDB)

**LLM Failover Health:**
- Anthropic API: Primary (Claude Haiku/Sonnet available)
- OpenRouter: Secondary (health check in rotation)
- Greybox Ollama: Tertiary fallback (100.108.183.68:11434)

**Agent Status:**
- Boot: Active, delegating to Cloudkicker when available
- IG-88: Active, trading analysis paused per BKX055
- Kelk: Active, personal advisor domain

**Known Issues:**
1. Graphiti ingestion non-functional — `add_memory()` succeeds, but `search_memory_facts()` returns empty results despite FalkorDB reporting healthy. Hypothesized root cause: FalkorDB ingestion pipeline issue downstream of queuing. **Requires investigation:** Restart FalkorDB, test ingestion end-to-end with simple episode.
2. Coordinator logs show EROFS (read-only filesystem) errors from 2026-01-28 — likely due to mount state at that time. Appears resolved (logs are stale, no recent errors). **Verify:** Check current mount state: `mount | grep readonly`.

---

## X. Decision Hierarchy in Infrastructure Operations

All infrastructure decisions follow the standard T1-T4 hierarchy (BTI009 §II.A):

| Tier | Decision | Examples | Authority |
|---|---|---|---|
| **T1** | Autonomous (Boot decides alone) | Restart unhealthy service, scale Claude sessions up/down, trigger circuit breaker reset | Boot (L3 Operator, ops domain) |
| **T2** | Propose + Execute unless blocked | Trigger Cloudkicker failover (propose in Matrix, execute immediately if no objection within 60s) | Boot (can execute first, report after) |
| **T3** | Propose + Wait for Approval | Shut down coordinator for maintenance, reconfigure LLM failover chain | Boot proposes in Matrix, waits for Chris approval |
| **T4** | Escalate to Chris | Deployment of new service, major architectural changes, budget decisions | Boot escalates via @chrislyons mention |

---

## XI. Immediate Actions (Phase 0 — This Week)

These are tactical fixes and validations Boot should execute now:

1. **Verify current service state:** SSH into Blackbox, run `systemctl status` and `docker ps` to confirm all services are running. Update this document's "Current Operational State" section with real data.
2. **Diagnose Graphiti ingestion issue:** Restart FalkorDB (`docker restart falkordb`), then test with a simple `add_memory()` → `search_memory_facts()` round-trip to confirm persistence works.
3. **Check filesystem mount state:** Verify no read-only mounts causing EROFS errors. Command: `mount | grep readonly`.
4. **Create #boot-ops Matrix channel:** Dedicated async operational alerts channel (referenced in BTI009). Heartbeat should post to this room, not #backrooms.
5. **Test failover chain:** Manually trigger each provider's health check to confirm all three tiers (Anthropic, OpenRouter, Greybox) are reachable and responsive.

---

## XII. Worked Example — Incident: Cloudkicker SSH Timeout

**Scenario:** Boot delegates Module 4 research to Opus on Cloudkicker. 90 seconds later, SSH connection times out (network partition, Cloudkicker unreachable).

**System Response (Automatic):**
1. Coordinator detects SSH timeout (>10s)
2. Coordinator queues the delegate session with "Cloudkicker unreachable" status
3. Coordinator sends Boot a Matrix notification: "Cloudkicker offline. Falling back to Haiku. Task queued for retry."
4. Boot receives fallback instructions and begins local work with Haiku (graceful degradation)
5. Coordinator background process retries SSH every 60s
6. When Cloudkicker returns online, coordinator resumes delegate session from queue (FIFO)

**Boot's T1 Action (Autonomous):**
- Recognize Cloudkicker is offline
- Switch to local Haiku work (no approval needed)
- Queue complex tasks for later

**Boot's T2 Action (Propose + Execute):**
- If offline >5 min: Post to #backrooms "Cloudkicker offline — falling back to Haiku work" (informational)
- Continue work autonomously

**Boot's T3 Action (Propose + Wait):**
- If offline >30 min: Ask Chris "Should I attempt SSH reconnection manually or wait for automatic recovery?"

**Outcome:** System degrades gracefully. No work is lost, no decision bottleneck, and Boot never waits.

---

## XIII. Next Steps — Module 5 Preview

Module 5 (Portfolio & Capacity Planning) will address:
- How to size the agent swarm for different workload profiles (high-volume vs. high-reasoning)
- Budget allocation across LLM providers at scale
- Demand forecasting for agent availability
- Cross-project prioritization and resource sharing

---

## XIV. Revision Notes for Gate Review

**Open Questions for Chris:**
1. Is the graceful degradation band model (healthy/constrained/degraded/critical) realistic? Should thresholds be adjusted based on actual RP5 behavior?
2. Should Graphiti ingestion be investigated as Phase 0 (blocker) or Phase 1 (nice-to-have)? Current state: episodes stored to disk but not searchable via Graphiti.
3. For agent health scoring, is the 30-minute window and circuit breaker timing correct? Should reset be manual-only or automatic after 5 min pause?
4. Should Kelk (L2 Advisor) have any automation rights in infrastructure ops, or should all Bash/system decisions route through Boot?
5. Is the three-tier failover chain (Anthropic → OpenRouter → Greybox) the final strategy, or are there additional tiers (e.g., MiniMax, Kimi) to add?

---

**Status:** DRAFT — awaiting gate review from @chrislyons.
**Previous Modules:** BTI008 (PASSED), BTI009 (PASSED), BTI010 (PASSED)
**Next Module:** BTI012 Portfolio & Capacity Planning
