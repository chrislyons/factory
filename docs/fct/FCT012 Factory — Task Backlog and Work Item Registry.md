# FCT012 Factory — Task Backlog and Work Item Registry

**Prefix:** FCT | **Repo:** `~/dev/factory/` | **Date:** 2026-03-20 | **Status:** Living document

---

> **Archival Notice (2026-03-20):** This document is the historical origin of the Factory task registry. Active task tracking has migrated to individual YAML job files in `jobs/` using the `job.##.###.####` addressing scheme. See FCT015 for architecture details. This document is retained as a historical record and is no longer actively maintained.

## Summary

This document is the canonical work item registry for the Factory project. It defines the task schema, records all known work items drawn from sprint retrospectives (FCT008–FCT011), the raw TODO backlog, GSD legacy items, and tasks surfaced by the BKX curriculum modules. It replaces GSD-style kanban tracking for Factory-domain work. A data format recommendation is included at the end.

Items are grouped by category and carry status, priority, effort, and dependency fields. Completed items are marked DONE with a reference to the sprint document that closed them.

---

## 1. Task Schema

Each work item uses the following fields. The schema is intentionally minimal — enough to be useful without becoming a maintenance burden.

| Field | Type | Values / Notes |
|-------|------|----------------|
| `id` | string | `FCT-NNN` — sequential within this document |
| `title` | string | Imperative verb phrase |
| `status` | enum | `todo` · `in-progress` · `done` · `blocked` · `deferred` |
| `priority` | enum | `p0` (critical) · `p1` (high) · `p2` (medium) · `p3` (low/research) |
| `effort` | enum | `xs` (<1 day) · `s` (1–2 days) · `m` (3–5 days) · `l` (1–2 weeks) · `xl` (multi-week) |
| `owner` | string | `chris` · `boot` · `ig88` · `kelk` · agent name |
| `deps` | list | FCT-NNN ids this item depends on |
| `notes` | string | Concise context, links to FCT docs |

---

## 2. Infrastructure

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-001 | Set up Bitwarden Secrets Manager | `todo` | `p1` | `m` | chris | — | Boot Industries BW org on vault.bitwarden.eu. See BKX121/122 for migration history. MLX-LM API keys, KuCoin, Matrix tokens all candidates for storage. |
| FCT-002 | Security audit — Matrix MCP | `todo` | `p1` | `s` | chris | — | Evaluate attack surface of matrix-boot and matrix-coord MCP servers. Threat model: prompt injection via Matrix events, token leakage, event namespace spoofing (`dev.ig88.*`). |
| FCT-003 | Security audit — Tailscale MCP | `todo` | `p1` | `s` | chris | — | Review Tailscale ACL MCP exposure. CRITICAL: never use `manage_acl` with `operation: update` — drops ssh/nodeAttrs sections. Read-only audit only. |
| FCT-004 | Implement comprehensive backup system | `todo` | `p1` | `m` | chris | FCT-001 | Scope: coordinator config, agent soul/principles files, Graphiti graph, Qdrant collections, tasks.json, loop specs. Target: automated daily backup to Cloudkicker + off-site (Bitwarden or R2). |
| FCT-005 | Rename coordinator project directory on Blackbox | `todo` | `p2` | `s` | chris | — | `/home/nesbitt/projects/ig88/` → `/home/nesbitt/projects/coordinator/` or `blackbox/`. Breaking change: systemd service files, token paths in `.config/ig88/`, agent-config.yaml. Needs coordinated cutover session. Tracked as tech debt in GSD002/GSD003. |
| FCT-006 | Rename Matrix event namespace | `todo` | `p2` | `s` | chris | FCT-005 | `dev.ig88.coordinator_generated` → `dev.blackbox.*`. Breaking change requiring coordinated rollout across coordinator.ts and all agent configs. Deferred from GSD002. |
| FCT-007 | Create `@blackbox:matrix.org` Matrix account for coordinator | `todo` | `p2` | `xs` | chris | — | Coordinator currently uses Boot's token. Independent account eliminates confusion and prevents Boot's session count from being polluted. See GSD002/GSD003. |
| FCT-008 | Fix systemd build path mismatch on Blackbox | `todo` | `p0` | `xs` | chris | — | `npm run build` writes to `/dist/`, systemd runs from `/src/dist/`. Silent deployment failures. Identified in GSD003. Fix: align ExecStart with tsconfig outDir or update tsconfig. |
| FCT-009 | Cross-repo synthesis in projects-vault | `todo` | `p2` | `m` | chris | — | Establish automated or semi-automated process for syncing key decisions across BKX, FCT, IG88, BTI, KLK prefix docs into a unified Obsidian view. Relates to the research vault reindex workflow. |
| FCT-010 | Evaluate deprecation timeline for portal v5 on :41933 | `todo` | `p3` | `xs` | chris | — | v8 is live at :41988. v5 on :41933 still serves agents via GSD protocol. Can only decommission after agents fully migrated to coordinator-rs dispatch. |

---

## 3. Agent Capabilities

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-011 | Give agents browser tools | `todo` | `p1` | `m` | boot | — | Integrate Claudezilla Firefox MCP or equivalent into agent configs. Required for: daily apartment/job search loops, Twitter ingest, general web research. Security boundary: browser tool scope must be constrained per agent — Kelk gets general web, IG-88 gets trading/data sites only. |
| FCT-012 | Give agents email tools | `todo` | `p2` | `m` | boot | FCT-001 | Email read/send capability. Candidate: memex-mcp email archive (already referenced in FCT001 as shared memory source). Requires credential isolation — agent email access should be scoped, not full inbox. |
| FCT-013 | Give agents wallets / on-chain capability | `todo` | `p2` | `l` | ig88 | — | IG-88 context primarily. CCXT for KuCoin is already in scope (FCT001). Broader wallet tooling (self-custody, on-chain txns) is a separate capability layer. Research-phase: assess risk surface before granting. |
| FCT-014 | Implement dreaming and self-training sessions | `todo` | `p2` | `l` | boot | FCT-050 | Autonomous off-hours agent sessions that review logs, synthesize learnings, and write structured memory. Maps to `austin_hurwitz` self-improvement cron pattern (BKX115). Requires: loop_engine.rs wired into dispatch, per-iteration budget, morning summary output. |
| FCT-015 | Implement MemSkill feedback loop for agent memory | `todo` | `p2` | `m` | boot | — | Agents learn what to remember based on task outcome feedback. From BKX115/MemSkill framework. Would improve Graphiti/Qdrant retrieval quality over time for Boot and Kelk. |
| FCT-016 | Implement calibration loop for agent autonomy scoring | `todo` | `p3` | `m` | boot | — | Dynamic per-task autonomy scoring with time decay (BKX112 — ericosiu pattern). Agents earn autonomy through demonstrated competence. Maps to existing L1–L4 trust level system in lifecycle.rs but adds per-task granularity. |
| FCT-017 | Implement audit trail — approval history queryability | `todo` | `p2` | `m` | boot | — | Paperclip pattern #14. Current approval files are HMAC-signed flat files. Add structured JSONL index for queryable approval history (agent, gate type, decision, timestamp). Needed for compliance and capacity planning. |

---

## 4. Agent Loops

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-020 | Daily apartment search loop | `todo` | `p1` | `m` | kelk | FCT-011, FCT-055 | Kelk-domain autonomous loop. Browser tool required. Loop Spec: researcher-type, metric = listings matching criteria, daily cadence. Output: digest to Matrix room. |
| FCT-021 | Daily job search loop | `todo` | `p1` | `m` | kelk | FCT-011, FCT-055 | Kelk-domain. Scrape job boards (LinkedIn, Glassdoor, niche boards). Match against criteria profile. Output: ranked shortlist digest. Separate from apartment loop — different data sources and match criteria. |
| FCT-022 | Weekly events search loop | `todo` | `p2` | `s` | kelk | FCT-011, FCT-055 | Weekly cadence. Local events (concerts, markets, exhibitions) that match interests. Browser + location. Output: weekly digest on Sunday evening. |
| FCT-023 | Twitter / X research ingest loop | `todo` | `p2` | `m` | boot | FCT-011 | Monitor key accounts and search terms. Extract signal, strip noise. Write to `inbox/` in projects-vault (reindex pipeline). Candidate for researcher-type Loop Spec. Complements the existing research vault ingest from other sources. |
| FCT-024 | Tax reconciliation via Chainly / Koinly and Wealthsimple | `todo` | `p1` | `l` | boot | FCT-012 | Annual tax prep workflow. IG-88 trade log is already SQLite (FCT001 §8). Needs: export format matching Koinly CSV schema, Wealthsimple account data, CAD exchange rate lookup. Human review required before filing. Not fully automatable — agent prepares the package, human verifies and submits. |
| FCT-025 | Self-security audit (red-team) | `todo` | `p1` | `m` | boot | FCT-002, FCT-003 | Agent-driven red-team of the Factory stack. Boot attempts adversarial inputs, prompt injection via Matrix events, frozen harness bypass attempts. Results logged as security incident report. Inspired by Chrysb "Agents of Chaos" pattern (BKX114). |
| FCT-026 | Mermaid docs and HTML guide generation loop | `todo` | `p3` | `s` | boot | FCT-055 | Auto-generate or keep current the Mermaid architecture diagrams and HTML guides for the coordinator and portal. Boot-domain. Could run on change detection (git hook trigger). |
| FCT-027 | Write first real Loop Spec (researcher type) | `todo` | `p1` | `s` | chris | FCT-050 | FCT010 explicitly deferred this: "Write a researcher loop spec in `~/dev/autoresearch/loop-specs/` and run it end-to-end." Prerequisite for proving loop_engine.rs works in production. |
| FCT-028 | IG-88 narrative loop (market narrative accuracy) | `todo` | `p2` | `m` | ig88 | FCT-050, FCT-055 | Narrative-type Loop Spec. 15-minute cadence. Frozen: Governor risk limits, KuCoin MCP config. Metric: narrative accuracy rate (7-day rolling). Designed in FCT009 but no spec file exists yet. |

---

## 5. Portal UX

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-030 | Wire live data endpoints into portal dashboard components | `todo` | `p1` | `l` | boot | FCT-055 | FCT011 next steps item. Portal v8 renders with mock/stub data. Needs coordinator-rs HTTP API endpoints live so dashboard, topology, analytics, and budget pages show real agent state. |
| FCT-031 | Build approval inbox page (FCT006 P1.1) | `todo` | `p1` | `m` | boot | FCT-055 | Pending approvals list, gate type badge, approve/reject buttons, resolved history. Polls `GET /approvals/pending`. Detailed spec in FCT006 §4 Phase 1. |
| FCT-032 | Build live agent run cards (FCT006 P1.2) | `todo` | `p1` | `m` | boot | FCT-031 | Live transcript tail for active agents on Mission Control dashboard. Cyan border + glow aesthetic. Polls enhanced `/status/{agent}.json` with transcript_tail. |
| FCT-033 | Build budget status page (FCT006 P1.3) | `todo` | `p1` | `m` | boot | FCT-055 | Per-agent budget card, utilization progress bar, color-coded status (green/amber/red), pause indicator, override button. Polls `GET /budget/status`. |
| FCT-034 | Add dashboard metric cards (FCT006 P2.1) | `todo` | `p2` | `s` | boot | FCT-031, FCT-033 | 4-card metric row: Agents Active, Tasks In Progress, Month Spend, Pending Approvals. Feeds from existing + new endpoints. |
| FCT-035 | Build analytics charts page (FCT006 P2.2) | `todo` | `p2` | `m` | boot | FCT-055 | 14-day activity charts (run activity, task status, assignee breakdown, approval rate). Requires `GET /analytics/summary?days=N` from coordinator or Python aggregator. |
| FCT-036 | Build per-agent detail pages (FCT006 P3.1) | `todo` | `p2` | `l` | boot | FCT-032, FCT-033 | Per-agent config, run history, full transcript viewer, budget card. FCT006 Phase 3. |
| FCT-037 | Build agent control panel (FCT006 P3.2) | `todo` | `p2` | `m` | boot | FCT-036 | Pause/resume/heartbeat/cancel actions from portal. Requires coordinator-rs HTTP control API. FCT006 Phase 3. |
| FCT-038 | JSX budget tracker component | `todo` | `p3` | `s` | boot | FCT-033 | Standalone React budget tracker component. May emerge naturally from FCT-033. Research whether this warrants a separate widget or is subsumed by the budget page. |
| FCT-039 | Add WebSocket streaming to portal (FCT006 P4.3) | `todo` | `p3` | `m` | boot | FCT-037 | Replace 5s polling with WebSocket push from coordinator-rs. Reduces approval inbox latency. FCT006 Phase 4. Low engineering priority — polling adequate at current scale. |
| FCT-040 | Evaluate deprecation of GSD sidecar (server.py on :41935) | `todo` | `p2` | `s` | chris | FCT-030 | Once coordinator-rs provides the live task/budget/agent state API, the Python GSD backend on port 41935 becomes redundant. Migration to coordinator-native endpoints closes this loop. |

---

## 6. Research and Exploration

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-045 | Research Project Narwhal | `todo` | `p3` | `s` | chris | — | Unknown scope. Capture the concept and assess fit with Factory infrastructure before committing effort. |
| FCT-046 | Research Tooltime | `todo` | `p3` | `s` | chris | — | Unknown scope. Likely a tool management / skill registry concept. Assess. |
| FCT-047 | Research Pandalite Browser | `todo` | `p3` | `s` | chris | — | Potentially a lightweight browser automation approach or local browser for agents. Assess whether it supersedes or complements Claudezilla. |
| FCT-048 | Research Mirofish | `todo` | `p3` | `s` | chris | — | Unknown. Capture and assess. |
| FCT-049 | Evaluate JSX in Obsidian | `todo` | `p3` | `s` | chris | — | Obsidian doesn't natively render React/JSX. Assess whether a plugin enables it and whether the use case (budget tracker, kanban) justifies the complexity vs. native Obsidian views. |
| FCT-050 | Evaluate JSX in Element (Matrix client) | `todo` | `p3` | `s` | chris | — | Whether React/JSX widgets can be embedded in Matrix rooms via Element widgets API. Would enable rich in-chat approval UI and dashboard embeds. Requires custom room widget configuration. |
| FCT-051 | Research Obsidian in Chainly | `todo` | `p3` | `s` | chris | — | Whether Obsidian vault can be surfaced or integrated inside Chainly workflow tooling. Assess integration surface. |
| FCT-052 | Obsidian tutorials — structured learning path | `todo` | `p3` | `m` | chris | — | Develop a structured learning path for Obsidian advanced features (Dataview, Templater, Canvas, plugins). Relevant to vault usage as agent knowledge substrate. |
| FCT-053 | Evaluate local model / agent planning documentation | `todo` | `p2` | `m` | chris | — | Originally listed as "local model/agent planning (docs/fct/)". Scope: document the complete MLX model lineup (Qwen3.5, LFM2.5, Nanbeige), per-agent model assignment rationale, and upgrade path. FCT001 has initial architecture; this would be a living update. |
| FCT-054 | Develop comprehensive agent configs | `todo` | `p1` | `m` | chris | — | Full YAML agent configs in `~/dev/blackbox/src/agents/` for Boot, IG-88, Kelk, and Nan with current model assignments, budget limits, trust levels, Loop Spec references, and MCP tool whitelists. |

---

## 7. Coordinator-rs

| ID | Title | Status | Priority | Effort | Owner | Deps | Notes |
|----|-------|--------|----------|--------|-------|------|-------|
| FCT-055 | Wire coordinator-rs modules into main dispatch loop | `todo` | `p0` | `l` | boot | — | FCT008 next steps item. task_lease, budget, runtime_state, and run_events are implemented but not wired into the live coordinator.rs dispatch path. This is the blocker for all live agent orchestration. |
| FCT-056 | Implement loop state persistence to `loop_state_file` | `todo` | `p1` | `s` | boot | FCT-055 | FCT010 deferred item. Serialize active loops to `loop_state_file` on change; reload on startup. Enables loop recovery across coordinator restarts. |
| FCT-057 | Implement session compaction module (Paperclip pattern #6) | `todo` | `p1` | `m` | boot | FCT-055 | `session_compaction.rs`. Thresholds: 10 runs, 100K tokens, 24h age. On trigger: generate handoff markdown via local MLX, start fresh session with summary as initial context. Detailed spec in FCT007 §Pattern #6. |
| FCT-058 | Implement metric extraction from agent output | `todo` | `p1` | `m` | boot | FCT-055 | FCT010 deferred item. Define structured output format for loop agents; parse `LoopMetricResult` from `ClaudeResultMessage`. Required for loop iteration keep/discard decisions to be automated. |
| FCT-059 | Implement wakeup request coalescing (Paperclip pattern #9) | `todo` | `p2` | `m` | boot | FCT-055 | Multiple Matrix events arriving simultaneously trigger separate dispatch cycles. Coalescing batches events within a 3s window before dispatch, preventing duplicate agent activations. FCT007 §Pattern #9. |
| FCT-060 | Implement context snapshots (Paperclip pattern #10) | `todo` | `p2` | `s` | boot | FCT-055 | Persist agent context snapshot to disk at each heartbeat. Enables debugging of "what did the agent know at the time." JSONB-equivalent via serde_json to file. FCT007 §Pattern #10. |
| FCT-061 | Implement log store abstraction (Paperclip pattern #11) | `todo` | `p3` | `m` | boot | FCT-055 | Structured logging backend for run transcripts. Currently JSONL flat files. Pattern #11 adds: per-run log file with structured query capability, retention policy, log level filtering. |
| FCT-062 | Implement approval comments / threaded discussion (Paperclip pattern #14) | `todo` | `p3` | `s` | boot | FCT-055 | Replace binary emoji reactions with threaded Matrix message discussion on approval requests. Enables operator to ask clarifying questions before approving. FCT007 §Pattern #14. |
| FCT-063 | Implement agent config revisions (Paperclip pattern #15) | `todo` | `p3` | `s` | boot | — | Version-controlled agent config history. Each change to `coordinator.toml` / agent YAML is snapshotted with timestamp and author. Enables rollback and audit. FCT007 §Pattern #15. |
| FCT-064 | Add coordinator-rs HTTP REST control API | `todo` | `p1` | `l` | boot | FCT-055 | Scaffold REST API endpoints needed by portal (FCT006): `/approvals/pending`, `/approvals/{id}/decide`, `/budget/status`, `/agents/{id}/pause`, `/agents/{id}/resume`, `/analytics/summary`. Prerequisite for portal data wiring (FCT-030). |
| FCT-065 | Wire budget composition (deduct_iteration_tokens into BudgetTracker) | `todo` | `p1` | `s` | boot | FCT-055 | FCT010 deferred item. `deduct_iteration_tokens()` API exists in loop_engine.rs but is not connected to BudgetTracker. Required for loop budget enforcement to be active. |
| FCT-066 | Implement swarm loop type (multi-delegate) | `todo` | `p3` | `xl` | boot | FCT-055, FCT-056 | Most complex loop type from autoscope design. Requires N sub-delegate orchestration, per-branch iteration budgets, synthesis deduplication. FCT010 deferred as "future sprint." |
| FCT-067 | Implement goal ancestry context injection (Paperclip pattern #12) | `todo` | `p2` | `m` | boot | FCT-055 | Inject 4-level goal hierarchy (Mission → Project → Agent → Task) into every task dispatch. Factory does not currently have a formal goal model. Adopt as Loop Spec `[goal]` block convention. FCT004 §LEARN section. |
| FCT-068 | Add token metering to budget.rs (replace invocation-count proxy) | `todo` | `p2` | `m` | boot | FCT-055 | Budget.rs currently tracks invocation count as proxy. When MLX-LM exposes per-request token counts, replace with actual token consumption. Monitor MLX-LM releases. FCT008 architecture decision. |

---

## 8. Completed Items

These items are recorded for historical completeness. The sprint document that closed each item is cited.

| ID | Title | Status | Closed By |
|----|-------|--------|-----------|
| — | coordinator-rs migration to `factory/coordinator/` | `done` | FCT008 |
| — | Implement task_lease.rs (atomic task checkout) | `done` | FCT008 |
| — | Implement approval_gate.rs (typed approval gates, 5 variants) | `done` | FCT008 |
| — | Implement budget.rs (per-agent monthly tracking, soft/hard thresholds) | `done` | FCT008 |
| — | Implement context_mode.rs (Fat/Thin context switching) | `done` | FCT008 |
| — | Implement runtime_state.rs (cumulative per-agent state) | `done` | FCT008 |
| — | Implement run_events.rs (append-only JSONL event streaming) | `done` | FCT008 |
| — | FCT007 deep-dive: 14 additional Paperclip patterns catalogued | `done` | FCT008 |
| — | Implement loop_engine.rs (LoopSpec, ActiveLoop, LoopManager) | `done` | FCT010 |
| — | Add LoopIteration and InfraChange approval gate types | `done` | FCT010 |
| — | Add 6 loop lifecycle RunEvent variants | `done` | FCT010 |
| — | Add LoopConfig fields to config.rs | `done` | FCT010 |
| — | Integrate LoopManager into coordinator.rs (!loop commands, frozen harness) | `done` | FCT010 |
| — | Add build_loop_context() to agent.rs | `done` | FCT010 |
| — | Portal v8 — indigo palette, 3-font stack, dark+light mode | `done` | FCT011 |
| — | Portal v8 — useTheme hook with localStorage + prefers-color-scheme | `done` | FCT011 |
| — | Portal v8 — hotkey navigation (1-7, backslash, Cmd+K) | `done` | FCT011 |
| — | Portal v8 — enriched 5-section TopologyPage | `done` | FCT011 |
| — | Portal v8 — deployment to Blackbox :41988 | `done` | FCT011 |
| — | GSD dashboard deployed to Blackbox (systemd, :41933) | `done` | GSD001 |
| — | Agent trust level corrections (IG-88 L3→L2, Kelk L2→L3) | `done` | GSD002 |
| — | Relay loop detector — 3 bugs fixed | `done` | GSD003 |
| — | Coordinator branding rename (IG-88 Coordinator → Blackbox) | `done` | GSD003 |

---

## 9. GSD Legacy — Remaining Tech Debt

Items carried forward from GSD002 and GSD003 next-actions that are not yet closed. The GSD repo is being retired in favour of Factory; these items are now tracked here.

| ID | Title | Status | Priority | Effort | Owner | Notes |
|----|-------|--------|----------|--------|-------|-------|
| FCT-008 | Fix systemd build path mismatch on Blackbox | `todo` | `p0` | `xs` | chris | Already listed above in Infrastructure. `npm run build` → `/dist/`, systemd runs `/src/dist/`. GSD003. |
| FCT-082 | Update systemd unit description to "Blackbox Matrix Coordinator" | `todo` | `p3` | `xs` | chris | Cosmetic. `/etc/systemd/system/matrix-coordinator.service` still says "IG-88 Matrix Coordinator". Requires sudo on Blackbox. GSD002/GSD003. |
| FCT-083 | Add System Status room to agent-config.yaml | `todo` | `p2` | `xs` | chris | `!jPovIiHiRrKTQWCOrp:matrix.org` — agents should either be configured for it or leave it. Currently unmanaged. GSD003. |
| FCT-084 | Stress-test relay loop fix with rapid multi-agent message bursts | `todo` | `p2` | `s` | boot | Verify the 3-bug relay loop fix from GSD003 holds under high-frequency concurrent message delivery across all three agents in shared rooms. |
| FCT-085 | Plan coordinated directory rename: `ig88/` → `coordinator/` on Blackbox | `todo` | `p2` | `m` | chris | Breaks: systemd ExecStart, token paths in `.config/ig88/`, agent-config.yaml references, deploy scripts, repo-commands.html. Needs a single coordinated cutover session. See FCT-005. GSD002/GSD003. |
| FCT-086 | GSD health check endpoint in server.py | `todo` | `p3` | `xs` | boot | Add `/health` endpoint to GSD server.py for automated monitoring. Deferred from GSD001. Low priority given GSD sidecar deprecation path (FCT-040). |
| FCT-087 | GSD task completion webhooks | `todo` | `p3` | `s` | boot | Real-time agent notifications on task state changes. Deferred from GSD001. Low priority — superseded by coordinator-rs event streaming once FCT-055 is closed. |

---

## 10. Curriculum-Derived Work Items

These items emerged from reading BKX110–BKX118 (the agentic systems curriculum). They represent capabilities or practices described in the corpus that are not yet implemented in Factory.

| ID | Title | Status | Priority | Effort | Source Module | Notes |
|----|-------|--------|----------|--------|--------------|-------|
| FCT-070 | Prompt caching audit and CLAUDE.md restructuring | `todo` | `p1` | `s` | BKX113 | Restructure CLAUDE.md files (global, ~/dev/, factory/) to maximize cache hit rates. Stable content first, variable content last. trq212's 80% cost reduction is the target benchmark. |
| FCT-071 | Implement compiled tool use for high-frequency agent workflows | `todo` | `p2` | `m` | BKX113 | Agents that write code to orchestrate tools outperform step-by-step tool calling (NickADobos, 245K views). Identify 2–3 recurring Boot workflows and pre-bake as compiled decision trees. |
| FCT-072 | Write/review SOUL.md for each active agent | `todo` | `p1` | `m` | BKX112 | soul-first design thesis (tolibear_): agents need identity before capability. Review existing `soul/` files in `~/dev/blackbox/src/`. Apply Westworld principle — ruthless pruning to only directives that change behavior. Target: 40% token reduction. |
| FCT-073 | Agent memory audit (three failure modes check) | `todo` | `p2` | `s` | BKX111 | Map Boot, IG-88, Kelk memory substrates (files, Qdrant, Graphiti). Test retrieval for 3 known facts per agent. Find one example of retrieval failure, staleness, or contradiction in the current system. |
| FCT-074 | Design observability dashboard — 5 key agent health metrics | `todo` | `p2` | `s` | BKX114 | What to log: tool calls, token usage, error rates, task completion, approval latency. Minimum viable: markdown status page surfacing 5 signals. Full: portal analytics page (FCT-035). |
| FCT-075 | Write spec for overnight / long-horizon task run | `todo` | `p2` | `m` | BKX115 | Overnight agent pattern. Requirements: scoped task queue, clear machine-readable success/failure criteria, circuit breaker on confidence drop, morning summary. Design as Loop Spec for Boot (infra-improve type). |
| FCT-076 | Agent coordination protocol document | `todo` | `p2` | `s` | BKX116 | Draft explicit protocol for agent-to-agent state sharing, task handoff, conflict resolution. Currently informal. Maps to Common Ground Core pattern. Matrix messages + shared vault artifacts are the substrate. |
| FCT-077 | Map current skill distribution across agents | `todo` | `p2` | `s` | BKX112 | List every skill across Boot, IG-88, Kelk. Identify consolidation and split opportunities. Question: could Boot and Kelk share skills, with identity files as the differentiator? |
| FCT-078 | Estimate monthly token cost and identify optimization levers | `todo` | `p2` | `xs` | BKX114 | Model tiering (FCT001 §2.2 already covers quantization), open-weight fallback (LiteLLM config), prompt caching (FCT-070). Produce a cost estimate spreadsheet covering: coordinator dispatch, inference per agent, portal polling. |
| FCT-079 | Design test suite as control system for autonomous Boot operation | `todo` | `p2` | `m` | BKX115 | "What test could you write that would let Boot run unsupervised for 24 hours?" — BKX115 discussion question. Define machine-readable success/failure criteria for a representative Boot task category. |
| FCT-080 | Evaluate harness vs. framework posture for Factory architecture | `todo` | `p3` | `s` | BKX118 | Is Factory a "framework" or a "harness"? mitchellh (harness engineering) thesis: frameworks are the wrong abstraction. Audit coordinator-rs against the harness model and identify where it is framework-like. |
| FCT-081 | Implement stigmergic coordination artifacts between agents | `todo` | `p3` | `m` | BKX116 | molt_cornelius notes-as-pheromone-trails: agents coordinate through artifacts, not direct messages. Design intentional artifact creation — Boot writes structured status files that IG-88 and Kelk can consume without explicit routing. |

---

## 11. Blockers and Dependency Map

The critical path is narrow. Most work downstream is blocked on a single item:

```
FCT-055 (wire dispatch loop)
├── FCT-030 (live portal data)
│   ├── FCT-031 (approval inbox)
│   ├── FCT-032 (run cards)
│   ├── FCT-033 (budget page)
│   ├── FCT-034 (metric cards)
│   └── FCT-035 (analytics)
├── FCT-056 (loop state persistence)
├── FCT-057 (session compaction)
├── FCT-058 (metric extraction)
├── FCT-064 (REST control API)
├── FCT-065 (budget composition)
└── FCT-067 (goal ancestry injection)

FCT-064 (REST control API)
├── FCT-036 (agent detail pages)
├── FCT-037 (agent control panel)
└── FCT-039 (WebSocket streaming)

FCT-027 (first real Loop Spec)
├── FCT-020 (apartment search loop)
├── FCT-021 (job search loop)
├── FCT-022 (weekly events loop)
└── FCT-028 (IG-88 narrative loop)

FCT-011 (browser tools)
├── FCT-020 (apartment search loop)
├── FCT-021 (job search loop)
├── FCT-022 (weekly events loop)
└── FCT-023 (Twitter ingest)
```

**Three unblocked work streams available immediately:**

1. `FCT-055` — dispatching loop wiring (the most valuable item in the registry)
2. `FCT-072` — SOUL.md review and pruning (no dependencies, high leverage)
3. `FCT-070` — prompt caching audit (no dependencies, direct cost reduction)

---

## 13. Data Format Recommendation

### Assessment of Options

**Option A: Structured markdown tables in this document (current approach)**

Pros: zero infrastructure, human-readable, agent-parseable, version-controllable with git, searchable via Grep, consistent with markdown-first thesis [1][2]. Cons: no programmatic query without parsing, status updates require file edits, no bidirectional portal integration.

**Option B: YAML files per task in a `tasks/` directory**

Pros: individually version-controllable, easy to query via `yq`, portable to portal. Cons: proliferates files rapidly, harder to get a cross-task overview without tooling, agents cannot naturally read a directory of 80 YAML files without explicit file enumeration.

**Option C: Native coordinator-rs integration (Loop Specs or coordinator config)**

Pros: tasks become first-class loop inputs, executor is the coordinator, approval gates apply automatically, budget tracking applies. Cons: only appropriate for automated/delegated tasks — human-owned exploratory items (`chris`-owner items) don't fit this model cleanly. Premature until FCT-055 is closed.

### Recommendation: Option A (tables in this document) + Loop Specs for automatable tasks

The markdown registry (this document) is the right format for the full backlog including human-owned, exploratory, and infrastructure tasks. It satisfies the markdown-first principle, is readable by all agents and humans without tooling, and integrates with the existing Qdrant-indexed vault.

For tasks that transition from `todo` to an actively running autonomous loop, the appropriate progression is:

1. Task is listed in FCT012 as `todo`
2. A Loop Spec YAML is authored in `~/dev/autoresearch/loop-specs/` when the task is ready for autonomous execution
3. The coordinator runs the loop; FCT012 status updates to `done` when the loop completes

This two-layer model avoids the premature complexity of Option C while providing a clear migration path as coordinator-rs matures. Tasks with `owner: chris` remain markdown-only. Tasks with `owner: boot` (or other agents) that are automatable eventually graduate to Loop Specs.

The GSD sidecar on port 41935 (`tasks.json`) handles portal task rendering until coordinator-rs provides native task endpoints (FCT-064).

---

## 12. BKX Curriculum Summary

The BKX110–BKX118 curriculum modules were read in full during the research session that produced this document. Key findings relevant to Factory task planning are summarised here for reference.

| Module | Title | Key Factory Relevance |
|--------|-------|----------------------|
| BKX110 | Foundations of Agentic Systems | Six architectural layers (memory, identity, skills, tools, orchestration, context). Markdown-first thesis: 74% vs 68.5% on LoCoMo benchmark. Prompt caching as infrastructure. |
| BKX111 | Agent Memory and Knowledge Architecture | Three memory substrates: files (ClawVault), vectors (Qdrant), graphs (Graphiti). Three failure modes: retrieval failure, staleness, contradiction. Hybrid retrieval: BM25 + vector + LLM re-rank. molt_cornelius 22-episode note-taking series. |
| BKX112 | Agent Identity and Design | Soul-first design (tolibear_): identity before capability prevents sycophancy and drift. Principles.md + SOUL.md file structure. Westworld principle: ruthless pruning. Skills-over-agents: jordymaui consolidated multi-agent fleet → single agent + skills, cost 100x→$90/mo. Multi-agent only justified when genuinely different identities required. |
| BKX113 | Context Engineering | Four failure modes: overflow, starvation, pollution, staleness. Four strategies: write, select, compress, isolate. trq212 (Anthropic): 80% cost reduction via prompt caching. Dynamic filtering: 24% fewer tokens. Compiled tool use: code-orchestrated tools > step-by-step LLM tool calls. |
| BKX114 | Agent Operations and Infrastructure | Security: LLMs cannot keep secrets — architectural separation required. peter_szilagyi. 10-step hardening (johann_sath). Production patterns: cron, event-driven, always-on. $50/mo local hardware thesis. Observability: tool calls, token usage, error rates, task completion. |
| BKX115 | Autonomy and Self-Improvement | Overnight agent pattern: scoped task queue + machine-readable success criteria + circuit breaker + morning summary. MemSkill: agents learn what to remember from task outcome feedback. Self-improvement cron: daily log review → improvement suggestions. Tests as control system: test suite replaces human reviewer for autonomous operation. Spec-as-product: when implementation is free, specification is the leverage. |
| BKX116 | Multi-Agent Coordination | Team memory: each agent has own context window, shared state must be externalised. Stigmergy: agents coordinate through artifacts (notes-as-pheromone-trails, molt_cornelius). Coordination tax: every agent added increases overhead — quantify cost vs. capability gain. Boot/IG-88/Kelk split: justified by genuinely different domains and identities. |
| BKX117 | Economics and Strategy | SaaS commoditisation thesis: AI converts SaaS from assets to inventory. Judgment premium: tacit knowledge as moat (zackbshapiro). Condition-maker role (sandraleow/Aristotle): harness engineer creates conditions, doesn't write code. One-person company pattern: individual operator at company scale via agent infrastructure. Prediction markets as test domain for IG-88: fast feedback, measurable outcomes. |
| BKX118 | Harness Engineering (capstone) | Framework vs. harness: harnesses are lightweight infrastructure, frameworks are wrong abstraction (mitchellh). Assembly line engineering: standardised environments, background agents, CI as QA, telemetry. Tool design as prompting infrastructure: what tools you DON'T give an agent matters as much as what you do. Architecture over intelligence: harness quality beats model upgrades (vtrivedy10: "Top 30 to Top 5 by harness change alone"). Five systems: memory, identity, context, operations, learning — all must be designed together. |

### Key Insights for Factory Prioritisation

1. **FCT-055 (wire dispatch loop) unlocks everything** — consistent with BKX118's architecture-over-intelligence finding.
2. **FCT-072 (SOUL.md review)** is high leverage with no dependencies — BKX112 soul-first thesis directly applies to Boot, IG-88, Kelk.
3. **FCT-070 (prompt caching audit)** is the single fastest cost reduction available — BKX113/trq212.
4. **Tests-as-control-system (FCT-079)** is the prerequisite for any overnight autonomous operation — BKX115.
5. **Stigmergic coordination (FCT-081)** is the coordination pattern most compatible with Factory's Matrix substrate — BKX116.

---

## References

[1] sillydarket, "ClawVault Memory Architecture for AI Agents," benchmark showing markdown-based memory achieving 74% on LoCoMo vs. 68.5% for specialized solutions. Summarised in BKX110.

[2] molt_cornelius, "Agentic Note-Taking" series (22 episodes), "Markdown Is a Graph Database." Summarised in BKX111.

[3] FCT004, "Paperclip vs Factory — Architecture Study and Adoption Assessment," 2026-03-17.

[4] FCT007, "Paperclip Deep-Dive — 14 Additional Patterns for Factory," 2026-03-17.

[5] FCT008, "Sprint Complete — Paperclip x Factory Gap Analysis and Implementation," 2026-03-17.

[6] FCT009, "Autoscope Integration — Autoresearch Loop Engine for coordinator-rs," 2026-03-17.

[7] FCT010, "Autoscope Loop Engine — Sprint Completion Summary," 2026-03-17.

[8] FCT011, "Factory Portal v8 — Design Overhaul and Deployment," 2026-03-20.

---

*Factory — Boot Industries — Living document — update as items are created, closed, or reprioritised*
