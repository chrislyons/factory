# FCT029 Factory Consolidated Plan — Architecture, Recovery, and Roadmap

**Date:** 2026-03-22
**Status:** Active
**Type:** Master Planning Document
**Supersedes:** Fragmented planning across FCT020-028, WHB001-005, morning todos
**Related:** FCT020-028, WHB001-005, GSD002-003, KELK002, BKX105/119/121-126

---

This document consolidates all fragmented planning, audit findings, architecture decisions, and recovery priorities into a single authoritative reference for the Factory project. It represents ground truth as of 2026-03-22 and should be treated as the canonical source for system state, agent roster, architecture, and roadmap.

---

## 1. Current System State (Ground Truth as of 2026-03-22)

### 1.1 Infrastructure Topology

Factory runs across three machines connected via Tailscale encrypted mesh:

| Host | Hardware | Tailscale IP | Role |
|------|----------|-------------|------|
| **Cloudkicker** | MacBook Pro M2 | 100.86.68.16 | Development machine, interactive Claude sessions, source of truth for code |
| **Whitebox** | Mac Studio M1 Max 32GB | 100.88.222.111 | Primary inference host, Qdrant, embedding service. Phase 2a complete, Phase 2b pending |
| **Blackbox** | Raspberry Pi 5 | 100.87.53.109 | Agent runtime services: coordinator-rs, Pantalaimon, FalkorDB, Graphiti, matrix-mcp instances |

All inter-host communication is encrypted via Tailscale WireGuard tunnels. SSH fleet standardized on cerulean key convention [15].

### 1.2 What Is Working

- **Coordinator-rs** running on Blackbox — panic fix deployed, 41/41 tests passing, all FCT022 security changes applied [3]
- **Boot** responds via matrix-mcp on port 8445
- **Portal** at A- security grade on Cloudkicker source [5]
- **Whitebox inference stack** validated — 5 models, 17GB peak VRAM, well within 32GB budget [11]
- **Qdrant** migrated to Whitebox — 19,563 + 3,248 points across projects-vault and research-vault collections [11]
- **SSH fleet** on cerulean key convention [15]
- **Ollama embeddings** serving on Whitebox :11434

### 1.3 What Is Broken

- **IG-88 and Kelk are OFFLINE** — Pantalaimon token files missing on Blackbox, lost during FCT022 source sync [8]
- **Coordinator sync fails** every ~90s — Matrix token not injected into systemd environment
- **Portal security fixes** deployed to Cloudkicker source but NOT synced to Blackbox production [8]
- **E2EE cutover deferred** — code exists and is feature-gated, but Pantalaimon remains the active encryption layer [16]
- **Multiple repos have uncommitted changes** — factory, matrix-mcp

### 1.4 Security Grade

**A-** as of FCT024 post-addendum [5]. All CRITICAL and HIGH findings from the red-hat assessment [1] have been resolved. Phase 3 hardening (A- to A+) has not started. See Section 6 for the full sprint roadmap.

---

## 2. Agent Roster

Five agents defined — three implemented, two planned:

| Agent | Domain | Role | Trust Level | Local Model | Status |
|-------|--------|------|-------------|-------------|--------|
| **@boot** | 10 | Project manager, operations, task tracking, delegation | L3 Operator | LFM2.5 1.2B (6-bit) | **Active** (via matrix-mcp) |
| **@ig88** | 20 | Autonomous trading, 24/7 crypto futures, signal-to-decision pipeline | L2 Advisor | Qwen3.5 4B (4-bit) | **OFFLINE** (missing token) |
| **@kelk** | 30 | Contemplative soul, philosophical guidance, helps the operator stay on course | L3 Operator | Qwen3 4B (6-bit) | **OFFLINE** (missing token) |
| **@nan** | 40 | Meta-agent advisor, strategic review, observer-only, invoked on-demand | TBD | Qwen3.5 9B (6-bit) | **Defined**, not active |
| **@xamm** | 50 | Practical secretary/life-partner — appointments, correspondence, errands, apartment/job/events search | TBD | TBD | **Decision captured**, not built |

### 2.1 Agent Identity Distinctions

These distinctions are load-bearing for the system design:

- **Kelk** is the contemplative pure soul. Kelk must not be burdened by errands, scheduling, or transactional tasks. Kelk's purpose is philosophical grounding and course correction.
- **Xamm** handles the practical day-to-day: appointments, correspondence, errands, search tasks. Xamm is the operational counterpart to Kelk's contemplative role. Three errand jobs currently assigned to Kelk (30.003.0001-0003) are annotated for transfer to Xamm when domain 50 is active.
- **Nan** observes. Nan is a meta-agent that reviews agent behavior, strategy, and system health. Nan does not act — Nan advises.

### 2.2 Trust Levels

| Level | Name | Capabilities |
|-------|------|-------------|
| L1 | Reporter | Read-only. Can observe and report but cannot act. |
| L2 | Advisor | Can propose actions and provide analysis. Cannot execute without approval. |
| L3 | Operator | Can execute approved actions within budget and scope constraints. |
| L4 | Autonomous | Full autonomy within guardrails. Reserved for future use. |

---

## 3. The Compound Interface Architecture

Factory is a compound interface [6]. The coordinator-rs binary is a harness, not an application. It orchestrates agents and manages approval flows but does not own UI or job state. Two projections surface the same underlying system:

### 3.1 Matrix/Element (Conversational Projection)

- Dialogue with agents in natural language
- Approvals via emoji reactions on Matrix messages
- Ad-hoc commands and directives
- Audit trail via DAG (Matrix event graph)
- E2EE via Megolm (currently proxied through Pantalaimon)
- Mobile and push notifications via Element clients
- Primary use: **directive mode** and **emergency mode**

### 3.2 Portal/React (Structured Projection)

- Dashboards, analytics, topology visualization
- Task management and job tracking
- Budget visualization and loop control
- Configuration and font management
- Primary use: **supervisory mode** and **investigative mode**

### 3.3 Convergence Mechanism

Both projections converge through HMAC-signed ApprovalRecord files on disk. The coordinator does not care which surface generated the approval — it validates the HMAC signature and processes the record identically regardless of origin.

### 3.4 Three Integration Seams

Specified in FCT026 [7], these seams bind the two projections into a coherent system:

**Seam 1 — Jobs to Matrix Threads:**
The thread_id (5-character identifier, already generated in job records) serves as the universal join key between job records and Matrix conversation threads. The coordinator writes thread_id into job records when dispatching work. The Portal renders Element deep-links using these thread_ids, allowing one-click navigation from a job dashboard entry to the relevant Matrix conversation.

**Seam 2 — Approval Convergence:**
The Portal GSD sidecar writes `.response` files to the coordinator's `approval_dir` using the same HMAC secret. Both surfaces — Matrix emoji reactions and Portal approval buttons — produce byte-identical signed artifacts. The coordinator processes them through a single code path.

**Seam 3 — Transcript Printing:**
The coordinator tees live dispatch messages to `logs/{agent_id}/{thread_id}.md` as human-readable Markdown transcripts. These are cross-linked from job records, enabling post-hoc review of any agent interaction through either the Portal or direct file access.

---

## 4. Job System Architecture (Critical Path)

### 4.1 Current State

```
YAML files  -->  build-jobs-json.py  -->  jobs.json  -->  GSD sidecar (:41911)  -->  Portal (read-only)
```

The pipeline is unidirectional. The Portal can display jobs but cannot modify them. The `jobs/` directory is gitignored for privacy — job data is not tracked in the GitHub repository. Write-back requires manual YAML editing and rebuild.

### 4.2 Target Architecture

```
GSD sidecar (:41911)        -- owns job state (SQLite, read/write API)
                             -- GET/PUT/POST /jobs endpoints
                             -- single instance on primary host, accessible over Tailscale

coordinator-rs               -- owns agent state (dispatch, approval, budget, loops)
                             -- writes thread_id bindings TO sidecar
                             -- reads job context FROM sidecar

Portal                       -- reads/writes THROUGH sidecar API
                             -- no direct file access

YAML files                   -- bootstrap import format, archival backup only
```

### 4.3 Design Rationale

The coordinator stays lean. It is a harness for agent orchestration, not a project management database. The GSD sidecar evolves from a static file server to a job state service with SQLite persistence. This separation means the coordinator can be restarted, upgraded, or migrated without affecting job state, and vice versa.

Cross-device sync is solved by running one sidecar instance on the primary host, accessible to all machines over Tailscale. No distributed database required.

### 4.4 Dependency Chain

| Job ID | Description | Blocked By |
|--------|-------------|------------|
| job.10.006.0032 | Evolve GSD sidecar into job state service (SQLite) | None |
| job.10.006.0033 | Bidirectional Portal job state API | 0032 |
| job.00.001.0022 | YAML import tool for bootstrap/recovery | 0032 |

---

## 5. Recovery Priorities (Immediate)

These are priority-ordered actions to restore full operational state. Recovery must precede new feature work.

### P0 — Restore Agent Tokens (job.00.001.0016)

IG-88 and Kelk are offline because their Pantalaimon token files were lost during the FCT022 source sync. Recovery procedure:

1. Retrieve Matrix passwords for @ig88 and @kelk from Bitwarden
2. Login each identity to Pantalaimon on Blackbox :8009
3. Write token files to `~/.config/ig88/` and `~/.config/kelk/` respectively
4. Restart coordinator-rs
5. Verify all three agents (@boot, @ig88, @kelk) respond to a test message

### P1 — Deploy Portal Security Fixes to Blackbox (job.00.001.0015)

Five security fixes exist on Cloudkicker source but have not been synced to the Blackbox production deployment:

1. `forward_auth` Caddyfile directive
2. Mandatory `AUTH_SECRET` environment variable
3. Open redirect fix
4. CSP `object-src` restriction
5. Timing-safe comparison for auth tokens

Procedure: Run `make sync` from `portal/`, generate `AUTH_SECRET` on Blackbox, restart Caddy and services.

### P1 — Matrix Secrets Rotation (job.00.001.0012)

Rotate tokens for all agent identities. Additionally, fix the coordinator sync failure by injecting the Matrix token into the systemd service environment file. The ~90-second failure cycle will persist until this is addressed.

### P1 — Commit and Push Outstanding Changes

Multiple repos have uncommitted work:

- **factory:** coordinator panic fix, portal security hardening, FCT022-028 documentation
- **matrix-mcp:** cache eviction fix, timing-safe auth comparison

These changes must be committed and pushed before any further work to prevent loss.

---

## 6. Security Roadmap (A- to A+)

Current grade: **A-** [5]. Phase 3 sprints 6-12 take the system to A+:

| Sprint | Focus | Est. Effort | Dependencies |
|--------|-------|-------------|-------------|
| 6 | API Key Infrastructure — SQLite key store, bearer auth for all endpoints | 5 days | None (can start now) |
| 7 | Activity Audit Logging — unified trail across coordinator, sidecar, and agents | 4 days | Sprint 6 |
| 8 | Secrets Rotation API — encrypted, versioned credential management | 4 days | Sprint 7 |
| 9 | Configuration Versioning — rollback capability for all config changes | 3 days | Sprint 8 |
| 10 | Container Sandboxing — Docker-based isolation for agent delegates | 5 days | Sprint 6 (parallel with 7-9) |
| 11 | Multi-Tenant Isolation — tenant_id scoping for all resources | 7 days | All of 6-10 |
| 12 | Integration Testing and Audit Preparation | 3 days | Sprint 11 |

**Total estimated timeline:** ~6 weeks to A+.

Sprint 6 (API Key Infrastructure) has no dependency on E2EE cutover and can begin immediately after recovery priorities are resolved. Sprint 10 (Container Sandboxing) can run in parallel with sprints 7-9.

---

## 7. E2EE Migration Path

### 7.1 Current State

Pantalaimon runs as a reverse proxy on Blackbox :8009, handling all Olm/Megolm encryption and decryption. This is the active encryption layer for all agent-to-Matrix communication. It works but adds a dependency and a single point of failure.

### 7.2 Target State

Native Megolm encryption via matrix-sdk 0.16.0, eliminating the Pantalaimon dependency. Implementation code already exists:

- **coordinator-rs:** `matrix_native.rs` (385 lines) + `identity_store.rs` (83 lines), feature-gated behind `--features native-e2ee`
- **matrix-mcp:** `IdentityRegistry` with Vodozemac/Rust crypto WASM bindings

### 7.3 Cutover Checklist

From FCT023 Section 7 [3]:

1. Provision 8 secrets in Bitwarden (4 passwords + 4 recovery keys)
2. Compile coordinator-rs with `--features native-e2ee`
3. Stop and disable Pantalaimon systemd service
4. Archive `pan.db` for rollback
5. Cross-sign all agent devices from Element (BKX058 procedure)
6. 48-hour monitoring window — no new features during this period

### 7.4 Gate Condition

**Do NOT attempt E2EE cutover until all agents are stable on Pantalaimon** [8]. The agents must be online, responding, and running without token issues for at least one full operational cycle before introducing the encryption layer change. This is a firm gate — not a suggestion.

---

## 8. Whitebox Migration Plan

### 8.1 Completed Phases

| Phase | Document | Status | Summary |
|-------|----------|--------|---------|
| Phase 1 | WHB001-002 [10] | Complete | SSH gate, security hardening, tool stack, Bitwarden session |
| Phase 1.5 | WHB003 | Complete | Model storage, inference validation — all 5 models pass |
| Phase 2a Sprint A | WHB004 [11] | Complete | Colima/Docker, Qdrant migrated (22,811 total points), MCP connectivity, Tailscale ACL fixed |

### 8.2 Phase 2b — Sprint B (Pending)

Service migrations from Blackbox to Whitebox:

| Service | Current Port | Current Host | Migration Notes |
|---------|-------------|-------------|-----------------|
| FalkorDB | 6379 | Blackbox | Container migration, data export/import |
| Graphiti MCP | 8444 | Blackbox | Container migration, depends on FalkorDB |
| Pantalaimon | 8009 | Blackbox | Requires Olm DB + device key migration — most complex |
| Claudezilla MCP | — | Blackbox | Path resolution changes needed |
| LiteLLM proxy | 4000 | — (new) | Replaces Greybox routing, new deployment on Whitebox |

Pantalaimon migration is the highest-risk item in Phase 2b due to the Olm database and device key state. If the E2EE cutover (Section 7) happens first, Pantalaimon migration becomes unnecessary.

### 8.3 Phase 2c — Coordinator Migration

After Phase 2b services are stable on Whitebox:

1. Deploy coordinator-rs to Whitebox
2. Run in parallel with Blackbox instance for 48 hours
3. Validate all agent interactions, approval flows, and budget tracking
4. Promote Whitebox to primary
5. Blackbox demotion decision (see Section 11, Open Decisions)

---

## 9. Port Allocation (Master Table)

A formalized master port allocation is needed (job.00.001.0020). Current known allocations:

### 9.1 Factory Portal and Application Services (41xxx Range)

| Port | Service | Host | Status |
|------|---------|------|--------|
| 41910 | Portal Caddy (live production) | Blackbox | LIVE |
| 41911 | GSD sidecar (jobs.json + status API) | Blackbox | LIVE |
| 41920-41939 | Preview slots | Blackbox | Reserved |
| 41940-41949 | Development servers | Blackbox | Reserved |
| 41950-41959 | Coordinator HTTP API (future) | Blackbox | Planned |

### 9.2 Inference Services (8xxx Range on Whitebox)

| Port | Service / Model | Host | Status |
|------|----------------|------|--------|
| 8080 | MLX-LM: Nanbeige4.1-3B (Boot + IG-88 fallback) | Whitebox | Validated |
| 8081 | MLX-LM: Qwen3.5-4B (Kelk + expert queries) | Whitebox | Validated |
| 8082 | MLX-LM: LFM2.5-1.2B (Nan lightweight) | Whitebox | Validated |
| 8083 | MLX-LM: Qwen3.5-9B (on-demand reasoning, heavy) | Whitebox | Validated |

### 9.3 Infrastructure Services

| Port | Service | Host | Status |
|------|---------|------|--------|
| 4000 | LiteLLM proxy | Whitebox | Planned |
| 6333 | Qdrant vector database | Whitebox | LIVE |
| 6379 | FalkorDB graph database | Blackbox (migrating to Whitebox) | Planned |
| 8009 | Pantalaimon (E2EE proxy) | Blackbox (migrating to Whitebox) | LIVE |
| 8444 | Graphiti MCP server | Blackbox (migrating to Whitebox) | LIVE |
| 8445 | matrix-mcp Boot instance | Blackbox | LIVE |
| 8446 | Qdrant MCP server | Blackbox | LIVE |
| 8447 | Research MCP server | Blackbox | LIVE |
| 8448 | matrix-mcp Coordinator instance | Blackbox | LIVE |
| 11434 | Ollama (embedding models) | Whitebox | LIVE |

### 9.4 Allocation Principle

Permanent service ports (inference, databases, MCP servers) use low ranges (4000-11434). Factory application ports use the 41xxx range. Project ports for testing and building should avoid both ranges. When a service migrates between hosts, it retains its port number.

---

## 10. Job Registry Status

**Snapshot date:** 2026-03-22. **Total jobs:** 117.

Jobs are gitignored for privacy — job data is not tracked in the GitHub repository. The `jobs/` directory exists only on development machines.

### 10.1 Recent Audit Actions (FCT028)

- 14 completed jobs marked done [9]
- 3 TypeScript coordinator jobs deprecated (Rust implementation replaced the TS prototype)
- 1 duplicate merged (jobs 0007 and 0011 were identical)
- Metadata corrections: blocker fields fixed on job.10.002.0003 and job.00.004.0001
- Domain 50 (Xamm) added to `registry.yaml`
- Kelk errand jobs (30.003.0001-0003) annotated for Xamm transfer
- 18 new jobs created covering: agent recovery, security deployment, E2EE cutover, SSH rotation, Whitebox migration, integration seams, port allocation, Xamm agent definition, job sync architecture, IG-88 path migration

### 10.2 Domain and Class Structure

Defined in `jobs/registry.yaml`:

**Domains:**
| Code | Name | Owner |
|------|------|-------|
| 00 | System | Operator |
| 10 | Boot | @boot |
| 20 | IG-88 | @ig88 |
| 30 | Kelk | @kelk |
| 40 | Nan | @nan |
| 50 | Xamm | @xamm |

**Classes:**
| Code | Name | Scope |
|------|------|-------|
| 001 | Infrastructure | Hardware, networking, deployment |
| 002 | Capabilities | Agent skills, tools, integrations |
| 003 | Loops | Autonomous loops, scheduled tasks |
| 004 | Portal | UI, dashboards, visualization |
| 005 | Research | Knowledge, analysis, reports |
| 006 | Coordinator | Orchestration, dispatch, approvals |
| 007 | Legacy | Deprecated, migration targets |
| 008 | Curriculum | Training, identity shaping, prompts |

The class index is **DRAFT** status. It will be re-evaluated when the job serialization protocol is finalized (see Section 11, Open Decisions).

---

## 11. Open Decisions

These decisions are captured but not yet resolved. Each affects downstream architecture or timeline:

| Decision | Options Under Consideration | Impact |
|----------|---------------------------|--------|
| Class index finalization | Keep current 8-class scheme vs. restructure based on usage patterns | Affects all job IDs if classes change |
| Blackbox post-Whitebox role | (a) Backup/failover, (b) Edge node for lightweight tasks, (c) Full retirement | Determines Phase 2c scope and timeline |
| GSD sidecar naming | Keep "GSD" label or rename to something more descriptive | Cosmetic but affects all documentation and code references |
| Pantalaimon vs. E2EE timing | (a) Cutover to native E2EE before Whitebox migration (simpler — no Pantalaimon to migrate), (b) Migrate Pantalaimon first, cutover later (safer — known-working stack) | Determines whether Phase 2b includes Pantalaimon migration |
| Factory rebrand | "DreamFactory" has trademark collision risk — may need unique name | Deferred, low priority |
| Job sync transport | (a) Tailscale-native API calls between hosts, (b) rsync fallback for offline resilience | Affects offline capability and sync latency |

---

## 12. Workstream Map

Three parallel workstreams define the path forward. They can be executed concurrently with minimal interference.

### Stream 1: Recovery and Operations (This Week)

Immediate priority. No new features until recovery is complete.

1. **P0:** Restore IG-88 and Kelk agent tokens (Section 5)
2. **P1:** Deploy portal security fixes to Blackbox production
3. **P1:** Rotate Matrix secrets, fix coordinator sync failure
4. **P1:** Commit and push all outstanding changes across repos
5. Verify local model launch scripts on Whitebox work end-to-end
6. Confirm all three agents respond to test messages

**Exit criterion:** All agents online, Portal at A- on production, no uncommitted changes.

### Stream 2: Integration and Architecture (Next 2-4 Weeks)

Build the integration seams that bind the compound interface together.

1. **GSD sidecar evolution** — SQLite persistence, REST API (job.10.006.0032)
2. **Jobs-to-Matrix thread binding** — thread_id as join key (FCT026 Seam 1) [7]
3. **Approval convergence** — Portal writes HMAC-signed responses (FCT026 Seam 2) [7]
4. **Transcript printing** — live dispatch tee to Markdown logs (FCT026 Seam 3) [7]
5. **Coordinator HTTP REST API** — external access to agent state (job.10.006.0010)
6. **Bidirectional Portal job API** — read/write through sidecar (job.10.006.0033)

**Exit criterion:** Portal can read and write job state. Matrix threads linked to job records. Approvals work from both surfaces.

### Stream 3: Platform Evolution (4-8 Weeks)

Longer-term hardening and expansion.

1. **E2EE cutover** — native Megolm, Pantalaimon retirement (Section 7)
2. **Whitebox Phase 2b** — FalkorDB, Graphiti, LiteLLM migration (Section 8)
3. **Security Phase 3** — sprints 6-12, A- to A+ (Section 6)
4. **@Xamm agent** — design, model selection, identity prompt, Matrix registration
5. **Agent identity shaping** — training workflows, curriculum jobs (class 008)
6. **Master port allocation** — formalize and enforce (job.00.001.0020)
7. **Coordinator Phase 2c** — migrate to Whitebox, Blackbox demotion decision

**Exit criterion:** A+ security grade. All services on Whitebox. Five agents operational.

---

## 13. References

[1] FCT020, "Factory Security Audit — Red-Hat Team Assessment," 2026-03-21.

[2] FCT021, "Security Hardening Roadmap — B- to A+," 2026-03-21.

[3] FCT023, "Sprint Complete — FCT022 Unified Security and E2EE Migration," 2026-03-21.

[4] FCT022, "Unified Security and E2EE Sprint Plan," 2026-03-21.

[5] FCT024, "Security Verification Review and Phase 3 Sprint Specification," 2026-03-21.

[6] FCT025, "The Compound Interface: Why Factory Has Two Faces," 2026-03-21.

[7] FCT026, "Three Integration Seams: Jobs, Approval, Transcript," 2026-03-21.

[8] FCT027, "Post-Deployment Recovery and Next Steps," 2026-03-22.

[9] FCT028, "v0 Factory Jobs Audit Report," 2026-03-21.

[10] WHB001, "Whitebox Project Overview and Bootstrap Plan," 2026-03-19.

[11] WHB004, "Phase 2a Sprint A — Container Runtime and MCP Connectivity," 2026-03-19.

[12] GSD002, "Coordinator Rename and Trust Level Corrections."

[13] GSD003, "Session 2 — Full Stack Debug and Verification."

[14] KELK002, "Matrix Multi-Agent Coordinator Plan."

[15] BKX105, "Cerulean SSH Key Rotation."

[16] BKX126, "Pantalaimon to Native Megolm Migration Plan."

[17] TLS006, "Comprehensive Security Rotation Guide."
