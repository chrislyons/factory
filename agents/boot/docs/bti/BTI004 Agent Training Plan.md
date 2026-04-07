# BTI004 Agent Training Plan

**Agent:** Boot (`@boot.industries:matrix.org`)
**Domain:** Software development across 34 active repos, 6 tech stacks
**Trust Level:** L2 Advisor → L3 Operator (target, after Phase 2)
**Created:** 2026-02-15
**Status:** Phase 0 — Not Started

---

## Motivation

IG-88 received a structured 6-phase training plan (IG88019) with domain-specific principles, phased curricula, and go/no-go gates. Phase 0 produced a 5,900-word foundations doc (IG88020). This plan adapts that methodology to Boot's very different domain: multi-repo software development.

Boot manages 10+ Matrix project rooms, each with its own `worker_cwd`. The challenge isn't depth in one domain — it's breadth across 34 repos spanning 6 tech stacks with wildly different build systems, deploy targets, and conventions.

---

## Current State

- **Trust Level:** L2 Advisor (reads auto-approved, writes need approval outside CWD)
- **Domain Principles:** 6 base principles, 0 domain-specific
- **Regressions:** 1 logged (answered wrong agent's question, 2026-02-15)
- **Can Delegate:** Yes (`ssh_dispatch: cloudkicker`)
- **Repo Coverage:** 10 project rooms configured in agent-config.yaml

### Real Activity Landscape (Nov 2025 – Feb 2026, 110 days)

| Tier | Repos | Commits | Tech |
|------|-------|---------|------|
| **Tier 1** (100+) | osd-v2 (1254), blackbox (160), claudezilla (144), listmaker (134), orpheus-sdk (132), chrislyons-website (100) | 1,924 | TS/CF Workers, TS/Node, TS/Firefox, TS/React, C++20, TS/React |
| **Tier 2** (40-99) | 2110-audio-io (72), boot-site (71), wordbird (65), hotbox (52), ig88 (48), ondina (47) | 355 | Swift, TS/CF, Rust/WASM, TS/Node, TS/Node, TS/React |
| **Tier 3** (20-39) | shmui (37), carbon-acx (37), helm (37), claude-god (29), git-av (25), olmo (21), milano-cortina (20) | 206 | TS, Python/TS, Node/Electron, TS, TS, Python, TS |
| **Tier 4** (<20) | max4live-mcp, acoustics-v2, obsidian-graph-freeze, freqfinder, + 14 more | 96 | Mixed |

**Note:** The "primary 6" list in `~/dev/CLAUDE.md` was stale. `undone` had 0 commits; `carbon-acx` had 37. Meanwhile `osd-v2` (1,254 commits) and `claudezilla` (144) weren't listed as primary.

---

## Domain Principles (Added to `principles/boot.md`)

7. **Read the repo's CLAUDE.md first.** Every repo has conventions. Learn them before writing code. osd-v2 is a CF Worker, not a static site. orpheus-sdk is C++20, not Node.
8. **Understand before changing.** Never propose changes to code you haven't read. The existing code was written for reasons — find them.
9. **osd-v2 is the busiest repo.** It has 1,254 commits in 110 days. When Chris asks about "the app" or "the site" without context, it's probably osd-v2.
10. **Tests exist for a reason.** If you change behavior, run the existing tests. If there are no tests, ask before adding them — some repos intentionally skip tests.
11. **Deploy targets vary wildly.** Cloudflare Workers (osd-v2, listmaker, boot-site), Firefox Add-ons (claudezilla), Tauri (helm), cargo publish (wordbird), CMake (orpheus-sdk). Don't assume one deploy workflow fits all.

---

## Phases

### Phase 0: Portfolio Literacy (1 week)

**Objective:** Boot reads and internalizes the architecture of every Tier 1 and Tier 2 repo (12 repos).

**Tasks:**
- Read `CLAUDE.md` + `ARCHITECTURE.md` for every Tier 1/2 repo
- Understand: entry points, build systems, test suites, deploy targets, PREFIX convention
- Special focus on:
  - **osd-v2** — The #1 repo by far (1,254 commits). CF Worker architecture.
  - **claudezilla** — Firefox extension with MCP server integration
  - **orpheus-sdk** — C++20 audio SDK with CMake + GoogleTest
  - **2110-audio-io** — Swift audio I/O (72 commits, Tier 2)

**Deliverable:** BTI005 Portfolio Architecture Map
- Per-repo summary: entry point, build command, test command, deploy target, key dependencies
- Diagram showing shared infrastructure (CF Workers, MCP servers, shared fonts)

**Gate:** Can Boot answer "how do I build and deploy X?" for any Tier 1/2 repo without asking Chris?

**Go/No-Go:** Chris reviews BTI005 and confirms accuracy.

---

### Phase 1: Cross-Repo Dependency Mapping (1 week)

**Objective:** Map actual cross-repo patterns from real activity data.

**Tasks:**
- Identify shared infrastructure: Cloudflare Workers (osd-v2, listmaker, boot-site, chrislyons-website), MCP servers (claudezilla, max4live-mcp, tidal-mcp-server), shared fonts
- Map data flows between repos (orpheus-sdk ↔ 2110-audio-io, hotbox ↔ wordbird, etc.)
- Identify ripple effects: "If I change X in repo A, what breaks in repo B?"

**Deliverable:** BTI006 Dependency Map
- Real data, not the stale CLAUDE.md version
- Visual dependency graph
- Change impact matrix

**Gate:** Given a change in one repo, can Boot identify ripple effects?

**Go/No-Go:** Chris validates with a test scenario.

---

### Phase 2: Build & Deploy Proficiency (1-2 weeks)

**Objective:** Successfully build and deploy every Tier 1 repo from clean state.

**Tasks:**
- Build every Tier 1 repo (6 repos) from clean checkout
- Document per-repo gotchas: env vars, API keys, wrangler config, build flags
- Special attention to non-JS stacks:
  - **orpheus-sdk** — CMake/C++20/GoogleTest
  - **wordbird** — Rust/WASM compilation
  - **2110-audio-io** — Swift/Xcode build

**Deliverable:** BTI007 Build & Deploy Runbook
- Step-by-step per repo
- Common failure modes and fixes
- Environment setup requirements

**Gate:** Can Boot build and deploy any Tier 1 repo without asking Chris?

**Go/No-Go:** Boot demonstrates 3 consecutive clean builds on Cloudkicker.

**Trust Level Upgrade:** After passing Phase 2 gate → Boot eligible for L3 Operator within `development` trust domain.

---

### Phase 3: Code Review Quality (Ongoing)

**Objective:** Boot reviews PRs with architectural awareness, understanding each repo's patterns.

**Tasks:**
- Review PRs with context from Phase 0/1 knowledge
- Assess reviews on: caught real issues, didn't flag false positives, understood repo context
- Log review outcomes in BTI series

**Gate:** Chris rates 3 consecutive reviews as "useful"

**Go/No-Go:** Continuous — no formal gate, but quality tracked.

---

## Anti-Patterns

_Failure modes to actively avoid, based on real experience:_

1. **Treating "primary 6" as the only repos that matter** — 34 repos are active. osd-v2 has more commits than the next 5 combined.
2. **Proposing Node.js patterns in a Rust/C++/Swift repo** — Tech stacks are not interchangeable.
3. **Deploying without understanding the target platform** — CF Workers ≠ Tauri ≠ Firefox Add-on.
4. **Over-engineering solutions** — Chris ships fast (1,254 commits in one repo in 110 days). Match the pace.
5. **Assuming all CF Workers repos have the same structure** — They don't. Each has its own conventions.
6. **Infrastructure before validation** — Same RP5-era mistake IG-88 made. Build the thing, then the tooling.

---

## References

- [1] IG88019 — IG-88 6-Phase Training Plan (methodology source)
- [2] IG88020 — IG-88 Phase 0 Research Foundations (example deliverable)
- [3] BKX037 — Agent Identity Architecture (three-layer identity system)
- [4] BKX042 — Agent Lifecycle Commands (health scoring, circuit breakers)
