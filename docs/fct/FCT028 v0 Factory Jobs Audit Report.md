
# FCT028 v0 Factory Jobs Audit Report

**Date:** 2026-03-21 | **Scope:** 99 jobs in `factory/jobs.json` | **Method:** 4 parallel Qdrant-backed subagents cross-referencing PREFIX docs, coordinator-rs source, portal source, and MEMORY.md

---

## A) COMPLETED (marked pending/deferred, but work is done) — 14 jobs

| Job | Title | Evidence |
|-----|-------|----------|
| `job.00.001.0001` | ~~☑~~ Set up Bitwarden Secrets Manager | **CORRECTION (FCT030):** MEMORY.md "Bitwarden Session Sync" refers to the Bitwarden *vault* (password manager), not Bitwarden *Secrets Manager* (programmatic API). Vault is active; BSM is not set up. Reverted to pending. |
| `job.00.001.0003` | ☑ Security audit — Tailscale MCP | Description self-documents completion; `tailscale-acl-guard.sh` deployed both machines |
| `job.00.001.0004` | [COMPLETE] Implement comprehensive backup system | MEMORY.md: `sys-bup` fully operational (script, alias, encryption, Whitebox destination) |
| `job.00.003.0001` | ☑ Write first real Loop Spec (researcher type) | `researcher-boot-2026-03-19.md` exists in autoresearch/loop-specs/ |
| `job.00.005.0002` | ☑ Research Tooltime | OLM044: fully documented Rust MCP gateway, actively integrated with olmo |
| `job.00.005.0009` | ☑ Evaluate local model / agent planning docs | OLM047/048/049 cover entire MLX lineup, LiteLLM config, three-layer stack |
| `job.10.004.0001` | ☑ Wire live data endpoints into portal | `api.ts` has real HTTP calls to all coordinator-rs endpoints; React Query hooks wired |
| `job.10.004.0002` | ☑ Build approval inbox page (FCT006 P1.1) | Merged into `LoopsPage.tsx` with full approval queue UI |
| `job.10.004.0003` | ☑ Build live agent run cards (FCT006 P1.2) | `TranscriptTail` component live in Dashboard + AgentDetail pages |
| `job.10.004.0004` | ☑ Build budget status page (FCT006 P1.3) | Merged into `AnalyticsPage.tsx` with BudgetBar, colour coding, override button |
| `job.10.004.0006` | ☑ Build analytics charts page (FCT006 P2.2) | `AnalyticsPage.tsx`: 4 Chart.js charts, `/analytics/summary?days=14` wired |
| `job.10.004.0007` | ☑ Build per-agent detail pages (FCT006 P3.1) | `AgentDetailPage.tsx` with transcript, budget, run history, config |
| `job.10.004.0008` | ☑ Build agent control panel (FCT006 P3.2) | `useAgentAction` (pause/resume/heartbeat) + `useRunCancel` wired |
| `job.10.004.0009` | ☑ JSX personal budget tracker component | Incorrectly assumes this is about agent budgeting, but is actually a personal funds tracker. |

---

## C) SUSPECT (flagged for review) — 7 jobs

| Job | Title | Issue |
|-----|-------|-------|
| `job.00.001.0002` | ☑ Security audit — Matrix MCP | BKX029/071 not findable in vault. Work may be absorbed into hooks sprint (WHB007). Recent work was also done in FCT020+. |
| `job.00.001.0005` | ☑ (done?) (check) Rename coordinator project dir on Blackbox | May be **deprecated** if coordinator-rs replaced the TS coordinator entirely. Hinge question: is the TS coordinator still the active runtime on Blackbox? `ssh blackbox 'systemctl status matrix-coordinator'` resolves this. |
| `job.00.001.0007` | [COMPLETE] [@COORD IS CORRECT] Verify @coord:matrix.org identity | BKX083 not in vault. GSD002 says the plan is `@blackbox:matrix.org`, not `@coord:matrix.org` — account name contradicts. |
| `job.00.001.0008` | (done?) (check) Fix systemd build path mismatch | npm/TypeScript-specific bug. If coordinator-rs is now the runtime, this is **deprecated**. Same hinge question as 0005. |
| `job.00.005.0001` | ☑ Research Project Narwhal | Not unknown — narwhal is a real repo with architecture diagrams (XPL008). Job framing is wrong. Rewrite or close. |
| `job.10.002.0003` | ☑ Implement dreaming sessions | **Wrong blocker:** `blocked_by: [job.00.005.0006]` (JSX in Element) has zero relation to dreaming. Real deps are loop engine + budget wiring. |
| `job.10.007.0001` | ☑ Stress-test relay loop fix | GSD003 fix was in TypeScript coordinator (now replaced). Job intent valid but framing is stale — reframe as coordinator-rs relay loop stress test. |

**Also note:** `job.00.007.0002` (rename systemd unit description) shares the same TS-vs-Rust hinge question as 0005/0008 above.

---

## D) CRUFT (vague/orphaned/no deliverable) — 6 jobs [[DEEMED HEALTHY AND NOT CRUFT - TO BE INCLUDED WITH OTHER JOBS AS PER CL]]

| Job | Title | Reason |
|-----|-------|--------|
| `job.00.001.0009` | ☑ First cross-repo synthesis in projects-vault | Vault coherence audit (2026-03-02) shows this work will becom routine ops. Deliverable: successful initial run and run schedule. |
| `job.00.005.0003` | ☑ Research Pandalite Browser | Should be in research-vault, consult other sources if necessary. CLZ014 already covers Claudezilla competitive landscape. Pantalite is probably not "for us" but could hold lessons for Claudezilla. |
| `job.00.005.0004` | ☑ Research Mirofish | Should be in research-vault, consult other sources if necessary. Suspicions around whether Mirofish is "real" predictions or just smoke and mirrors. Mirofish is probably not "for us" but could hold lessons for IG88 trading agent. |
| `job.00.005.0005` | ☑ Evaluate JSX in Obsidian | Speculative, conflicts with vault-as-filesystem contract. No deliverable path. |
| `job.00.005.0006` | ☑ Evaluate JSX in Element | Speculative, no prior work, Matrix is a message bus not a UI host, but could be interesting. Markdown is already being rendered in Element to positive results. (Also a wrong blocker target for job.10.002.0003.) |
| `job.00.005.0007` | ☑ Research Obsidian integrations in Chainly | "Chainly" is homespun crypto tax app at ~/dev/chainly/ |

---

## E) DUPLICATE — 1 pair [[ELIMINATE]]

| Jobs | Issue |
|------|-------|
| `job.00.008.0007` + `job.00.008.0011` | Both ref BKX115, both address "how does Boot run unsupervised for extended periods." 0007 = write the spec, 0011 = design the test suite. Merge or scope-split explicitly. |

---

## F) PARTIALLY COMPLETED — 2 jobs

| Job | Title | Status |
|-----|-------|--------|
| `job.00.008.0004` | ☑ Write/review SOUL.md for each agent | Soul directories exist at `~/dev/blackbox/src/agents/{boot,ig88,kelk}/soul/`. Whether SOUL.md specifically exists needs filesystem check. |
| `job.00.008.0008` | ☑ Agent coordination protocol document | Substantial prior art exists (multi-agent-role-contract.md, GSD002, KELK0001). Job should be reframed as consolidation, not original research. Lots to do here, including planning training curriculums for each a) agent, b) agent's local model(s). |

---

## G) METADATA FIXES (no status change needed)

| Job | Fix |
|-----|-----|
| `job.10.002.0003` | Remove `blocked_by: [job.00.005.0006]`. Replace with `[job.10.006.0011]` or unblock entirely. |
| `job.10.003.0003` | Add note distinguishing this from WHB007 hooks audit (different scope). |
| `job.10.006.0005` | Description says "3s window" but FCT007 specifies minute-bucket idempotency. Minor drift. |
| `job.00.004.0001` | Blocker `job.10.004.0001` is now completed — can be unblocked. |
| `job.10.004.0005` | SUSPECT — needs full read of `DashboardPage.tsx` to confirm 4-card metric row exists before marking done. |

---

## H) USER DECISION NEEDED

| Jobs | Question |
|------|----------|
| `job.30.003.0001–0003` | Are apartment search, job search, and events search still active life goals for Kelk? If resolved, deprecate all three. |
		>> ANSWER: @Kelk should not be burdened by day to day tasks. Kelk is the idyllic "child" thinker. The contemplative pure soul who helps me stay on cours. Errands, and tasks, should go to another agent whom we havent' named yet. We will add @Xamm a new agent who acts as a more actionable assistant and secretary of sorts. A life partner role, less contemplative and more practical. Booking appointments, correspondence, errands, life tasks like moving or finding work or looking up what to do that weekend. Clear distinction? And @Nan remains as an observer: not @Kelk, and not @Xamm.

| `job.00.001.0005`, `0008`, `00.007.0002` | Is the TypeScript coordinator still the active runtime on Blackbox, or has coordinator-rs replaced it? One `systemctl status` resolves 3 jobs. |
		>> I believe this has been answered in our documentation (verify) but Coordinator Typescript has been replaced by Coordinator Rust. This still resides on Blackbox to my knowledge and has not yet been migrated to Whitebox as planned.

---

**No duplicates found** beyond the 0007/0011 pair. The serialization of the file itself looks clean — no structural issues with the JSON.