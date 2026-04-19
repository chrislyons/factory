# BTI012 Project Portfolio Strategy

**Curriculum:** BKX057 Operations Executive (Boot) | **Module:** 5 of 6
**Status:** DRAFT for gate review
**Version:** 1.0 | **Date:** 2026-02-17

---

## Executive Summary

Portfolio strategy for a three-agent swarm (Boot, IG-88, Kelk) answers four questions:

1. **How do we size the agent swarm for different workload profiles?** — Distinguish high-volume throughput work (Haiku-dominant) from high-reasoning work (Sonnet/Opus-dependent) and allocate agents accordingly.

2. **How do we allocate budget across LLM providers at scale?** — At 1.5k–3k queries/month, cost is immaterial (<$3/month). Shift optimization from cost to capability-first allocation, with local fallback as a strategic reserve, not a cost-cutting measure.

3. **How do we forecast demand for agent availability?** — Seasonal patterns (trading signals paused, project bursts, personal tasks) drive concurrent session needs. Maintain 2–3 buffer sessions above baseline.

4. **How do we prioritize and share resources across projects?** — T1-T4 decision hierarchy maps workload urgency to agent assignment and model selection. Cross-project contention is resolved via async hand-off protocols (Graphiti temporal signaling, Matrix queue management).

**Key Principle:** Portfolio strategy is *not* about maximizing utilization or cutting costs. It's about ensuring the right agent + model reaches the right work at the right time, with predictable fallback when primary paths saturate.

---

## I. Workload Profiling — Three Archetypes

All work in the Boot/IG-88/Kelk swarm fits one of three patterns:

### A. High-Volume / Low-Reasoning (Throughput)

**Characteristics:**
- Many queries, each simple
- Latency tolerance: 500ms–5s
- Model demand: Haiku-dominant (85%+)
- Examples: Log summarization, list operations, status checks, simple Matrix bot responses

**Resource Profile:**
- Boot: Technical documentation, config reading, boilerplate code generation
- IG-88: Data ingestion, simple signal calculations (paused per BKX055, but pattern remains)
- Kelk: Scheduling queries, calendar management

**Optimal Allocation:**
- Route to Haiku by default (cost ~$0.80/1M input)
- Fallback to Sonnet only if Haiku timeout (circuit breaker at 30s)
- Concurrent session requirement: 1–2 (baseline)

### B. High-Reasoning / Medium-Volume (Reasoning)

**Characteristics:**
- Fewer queries, but each requires deep analysis
- Latency tolerance: 10–60s acceptable
- Model demand: Sonnet primary (60%), Opus secondary (10%), Haiku fallback (30%)
- Examples: Architecture design, operational planning (BTI modules), code review, decision synthesis

**Resource Profile:**
- Boot: Spike planning, operational decision trees, cross-repo dependency analysis
- IG-88: Trading signal synthesis, market narrative generation (when active)
- Kelk: Reflection, life planning, pattern recognition

**Optimal Allocation:**
- Route to Sonnet by default (cost ~$3/1M input)
- Escalate to Opus only if Sonnet insufficient (circuit breaker: max 5% of reasoning work)
- Fallback to OpenRouter Qwen 3.5 MoE if Anthropic API slow
- Concurrent session requirement: 2–3 (peaks possible)

### C. Frontier / Asymmetric (Opus-Only)

**Characteristics:**
- Rare queries with massive impact
- Latency tolerance: hours acceptable
- Model demand: Opus only (100%)
- Examples: Major architectural redesigns, novel delegation patterns, multi-agent coordination proofs

**Resource Profile:**
- Boot: Cross-project architecture, new operational patterns, delegation strategy proofs
- IG-88: Never (trading analysis doesn't require Opus)
- Kelk: Never (personal domain doesn't require Opus)

**Optimal Allocation:**
- Route via delegate session to Cloudkicker Opus
- Batch multiple frontier tasks when possible (reduce session overhead)
- Concurrent session requirement: 0–1 (rare, on-demand)

---

## II. Cost-Performance Economics

### A. Model Selection by Price-to-Capability Ratio

At the baseline workload (1.5k–3k queries/month, ~$1–3/month total spend):

| Model | Use Case | Cost | Capability | Best For |
|-------|----------|------|-----------|----------|
| **Haiku** | Throughput baseline | $0.80/1M in | Fast, narrow | High-volume work (85% of queries) |
| **Sonnet** | Reasoning sweet spot | $3/1M in | Deep reasoning + speed | Planning, synthesis (15% of queries) |
| **Opus** | Frontier | $15/1M in | Frontier capability | <1% of queries (rare) |
| **Qwen3-32B (local)** | Graceful degradation | ~$1/month inference | Matches Sonnet perf | Strategic reserve (offline failover) |
| **MiniMax M2.5 (OpenRouter)** | Tier 2 reasoning | $2/1M in | Proven fallback | When Anthropic API slow |

**Key Insight:** Cost optimization is *not* a lever at this scale. A 50% reduction in costs saves $0.50–1.50/month. Instead, optimize for:
- **Capability-first allocation** — Use best tool for job, not cheapest
- **Failover coverage** — Maintain three-tier chain (Anthropic → OpenRouter → Greybox)
- **Graceful degradation** — Stay in healthy memory band; local fallback as strategic reserve

### B. Batch API as Strategic Option (Not Baseline)

Anthropic Batch API: 50% discount on input tokens, 24-hour processing window.

**When to use:**
- Work that can be queued 24h in advance (rare for Boot/IG-88/Kelk)
- High-volume throughput (>100k tokens/batch) to break even on overhead
- Example: IG-88 end-of-day signal synthesis (if trading resumes)

**Recommendation:** Monitor for seasonal peaks (project bursts, IG-88 reactivation). Batch strategy becomes viable if query volume reaches 10k+/month (10x current).

### C. Local Inference as Resilience, Not Cost Reduction

Greybox 2.0 with Qwen3-32B:
- Electricity cost: ~$0.50–1.00/month for 20h inference/month
- Strategic purpose: **Offline fallback** when all three API tiers fail
- Performance: Matches Sonnet 4.5 on reasoning tasks
- Not a cost-cutting measure; complement to API chain

---

## III. Agent Allocation Strategy — T1-T4 Routing

Portfolio decisions follow the T1-T4 hierarchy established in BTI009:

### A. T1: Autonomous (Boot Decides Alone)

**Workload:** Routine throughput, operational tasks, documentation

**Allocation:**
- Agent: Boot (L3 Operator, operations domain)
- Model: Haiku (primary), Sonnet if timeout
- Concurrency: Solo (1 session needed)
- Example: Reading configs, writing runbooks, logging tasks

**Boot's autonomy:** No approval needed; act immediately.

### B. T2: Propose + Execute Unless Blocked

**Workload:** Planning tasks, operational decisions, moderate reasoning

**Allocation:**
- Agent: Boot (for planning/ops) or IG-88 (for analysis, when trading active)
- Model: Sonnet (primary), Opus if insufficient
- Concurrency: Multiple agents okay (2–3 sessions)
- Example: Spike planning (BTI009 pattern), architecture review

**Boot's autonomy:** Propose in Matrix, execute immediately if no objection within 60s. Report outcome.

**IG-88's constraints:** Requires Boot approval (approval delegation per agent-config room 367); can propose freely.

### C. T3: Propose + Wait for Approval

**Workload:** Major infrastructure changes, resource reallocation, experimental features

**Allocation:**
- Agent: Boot (infrastructure decisions)
- Model: Opus (if required for analysis)
- Concurrency: Delegate session to Cloudkicker
- Example: Coordinator shutdown for maintenance, LLM failover chain changes

**Boot's process:** Propose to Chris with full context and impact analysis. Wait for explicit approval (✅ reaction or `/delegate` command). Then execute.

### D. T4: Escalate to Chris

**Workload:** Policy changes, trust model shifts, vendor validation

**Allocation:**
- Agent: Boot (escalator; not decider)
- Model: N/A (information gathering only)
- Concurrency: N/A
- Example: Should Kelk be promoted to L3? When does IG-88 resume trading? New agent onboarding.

**Boot's process:** Present decision with tradeoffs. Wait for Chris decision. Do not propose unilaterally.

---

## IV. Concurrent Session Management — Graceful Saturation

### A. Baseline Concurrency Model

From BTI011 graceful degradation + agent-config.yaml:

| Scenario | Healthy (>4GB) | Constrained (2.4–4GB) | Degraded (1.2–2.4GB) | Critical (<1.2GB) |
|----------|---|---|---|---|
| Max Claude sessions | 5 | 3 | 2 | 1 |
| Primary model | Haiku/Sonnet/Opus | Haiku + gated Sonnet | Haiku-only | Haiku-only |
| Fallback available | Yes (all tiers) | Yes (Anthropic → OpenRouter) | Yes (local Ollama) | No (incident mode) |
| Queuing policy | No queue | Queue T2/T3 (prioritize T1) | Queue T2/T3 | Queue everything |

### B. Seasonal Demand Patterns

**Current (2026-02-17):**
- Boot: Steady 30–50 queries/day (ops, projects, training)
- IG-88: Minimal 5–10 queries/day (trading paused; baseline persistence)
- Kelk: Minimal 10–20 queries/day (personal tasks)
- Total: ~50–80 queries/day (1.5k–2.4k/month)

**Predicted Seasonal Peaks:**
- **IG-88 Trading Resume:** +200–300 queries/day (spike planning, signal synthesis, portfolio monitoring). Requires 2–3 concurrent Sonnet sessions.
- **Project Bursts (Cloudflare API migration, refactoring):** +100–150 queries/day for 1–2 weeks. Boot needs 2–3 Sonnet sessions.
- **Year-End Planning (Dec):** +50–100 queries/day (Kelk reflection, Boot annual review).

**Buffer Strategy:** Maintain 2 idle sessions in healthy band. If memory dips to constrained, shed T2/T3 work (async queue in Graphiti/Matrix).

### C. Contention Resolution — Async Hand-Off Protocol

When multiple agents compete for limited sessions:

1. **Signal intent in Matrix** — Agent posts to #backrooms: "@boot: I need Sonnet for spike [title]. ETA: 2h."
2. **Async acknowledgment** — Boot replies immediately: "Approved. Session 2 reserved."
3. **Graphiti temporal log** — Both agents log decision with timestamp and rationale.
4. **Async unblock** — When done, agent posts: "Spike complete. Releasing session 2."

**Why async:** Synchronous approval (daily standups) is slower and creates artificial scarcity. Async protocols scale to 10+ agents without coordination overhead.

---

## V. Demand Forecasting and Scaling

### A. Query Volume Baseline (90-day rolling average)

- **Observed (2026-02-17):** 1.5k–3k queries/month
- **Confidence:** Medium (small sample, seasonal variation unknown)
- **Next milestone:** 90-day rolling average stabilizes by mid-May 2026

**Implication:** All capacity planning assumes 3–5k queries/month until data contradicts.

### B. Scaling Triggers

When should portfolio strategy change?

| Trigger | Action | Timeline |
|---------|--------|----------|
| Query volume >10k/month | Revisit Batch API economics; consider delegation scaling | Q2 2026 |
| IG-88 trading resumed | Allocate 2–3 concurrent Sonnet sessions; review seasonal model | Upon resume |
| Kelk promoted to L3 | New agent trust model; possible new workload domain | TBD (Chris decision) |
| New agent onboarded | Redraw allocation matrix; review concurrent session caps | TBD |
| Cloudkicker offline >1 week | Degrade Opus availability; shift frontier work to OpenRouter Qwen 3.5 | Contingency |
| RP5 memory >1 week constrained | Optimize Ollama inference; consider secondary RP5 instance | Phase 2 (not Module 5) |

### C. 12-Month Scaling Assumptions

For financial and infrastructure planning:

| Month | Scenario | Concurrent Sessions | Avg Queries/Day | Model Mix |
|-------|----------|---|---|---|
| Feb–Apr | Baseline | 2–3 | 50–80 | Haiku 85%, Sonnet 14%, Opus 1% |
| May–Jun | IG-88 resume | 3–4 | 200–300 | Haiku 65%, Sonnet 30%, Opus 5% |
| Jul–Aug | Summer dip | 1–2 | 30–50 | Haiku 90%, Sonnet 10% |
| Sep–Nov | Project peak | 3–4 | 150–200 | Haiku 75%, Sonnet 23%, Opus 2% |
| Dec | Year-end + trading | 4–5 | 250–350 | Haiku 60%, Sonnet 35%, Opus 5% |
| *Est. annual* | *Average* | *3* | *~120/day* | *Haiku 75%, Sonnet 22%, Opus 3%* |

**Contingencies:**
- If IG-88 trading grows 10x: Scale to 5–6 concurrent sessions; revisit Cloudkicker capacity.
- If new agent onboarded: Add 1–2 sessions; revisit RP5 memory management.
- If volume <50 queries/day (downturn): Consolidate to 1 session; shift to local Ollama.

---

## VI. Cross-Project Prioritization Framework

### A. Work Priority Matrix (T1-T4)

When Boot receives competing directives:

| Priority | Duration | Urgency | Approval | Example | T-Level |
|----------|----------|---------|----------|---------|---------|
| **Critical** | <1 day | Incident/blocker | T1 (Boot autonomous) | Coordinator down, failover needed | T1 |
| **High** | 1–3 days | Blocking other work | T2 (propose + execute) | Spike for upcoming migration | T2 |
| **Medium** | 3–7 days | Important but not blocking | T3 (propose + wait) | Infrastructure upgrade, new deployment | T3 |
| **Low** | 1–4 weeks | Nice-to-have | T4 (escalate) | Optimization, documentation cleanup, policy changes | T4 |

### B. Resource Contention Heuristics

When Boot has two competing High-priority directives:

1. **Ask: Which unblocks more work?** — Prioritize the blocker.
2. **Ask: Which is shorter?** — If equal blocking, tackle short task first (parallelism with second task).
3. **Ask: Can we parallelize?** — If tasks use different agents (Boot + IG-88), run in parallel (§IV.C async hand-off).
4. **Ask: Does one require Chris approval?** — T3/T4 tasks may have approval latency; start T1/T2 tasks while waiting.

**Example:** Boot receives:
- **Task A:** Spike for CF API migration (High, 2 days, T2, uses Boot only)
- **Task B:** Infrastructure incident (Critical, 1 day, T1, uses Boot only)

**Decision:** Handle Task B immediately (T1 critical). Task A queued until Task B complete (1 day). Total: 3 days, no parallelism available (both need Boot solo).

---

## VII. Cost Allocation Across Projects

### A. Charge-Back Model (Informational)

For financial tracking, allocate query costs by project:

```
Project: Boot-Site CF API Migration
├─ Spike: 2 days × 40 queries/day × avg $0.01/query (Haiku) = $0.80
├─ Planning: 1 day × 30 queries/day × $0.02/query (Sonnet 20%) = $0.60
├─ Implementation: 4 days × 50 queries/day × $0.015/query (mix) = $3.00
└─ Subtotal: ~$4.40 (estimated, 90–110 queries total)

Project: IG-88 Trading Signals (when resumed)
├─ Daily synthesis: 200 queries/day × 20 days/month × $0.012/query = $48
└─ Subtotal: ~$48/month (estimated)

**Total:** All projects, all months = <$100/month
```

**Use:** Informational only. No charging gates between projects. All agents share LLM budget pool.

### B. When Charge-Back Becomes Mandatory

Only necessary if:
- Multiple customers or external stakeholders (currently: none)
- LLM costs >$1k/month (triggers ROI scrutiny)
- IG-88 trading activity >$200/month (triggers audit)

Current state: All agents share cost pool, no allocation needed.

---

## VIII. Worked Example — Scaling Scenario

**Scenario:** IG-88 trading signals resume (May 2026). Volume jumps to 250 queries/day.

**Portfolio Impact Analysis:**

**1. Workload Shift**
- Boot: Stable 50 queries/day (operations)
- IG-88: New 200 queries/day (trading analysis + signal synthesis)
- Kelk: Stable 10 queries/day (personal)
- Total: 260 queries/day (vs. baseline 80) = **+3.25x**

**2. Model Demand**
- IG-88 workload: 50% throughput (Haiku), 40% reasoning (Sonnet), 10% frontier (Opus delegation)
- New split: Haiku 65%, Sonnet 30%, Opus 5% (vs. baseline 85/14/1)
- Sonnet load: +60 queries/day

**3. Concurrent Session Impact**
- Baseline: 2–3 sessions
- New scenario: 3–4 sessions (IG-88 needs 2–3 concurrent Sonnet)
- RP5 memory band: Stable (healthy >4GB, no memory pressure)
- Cloudkicker delegation: Opus queries rare, stays 0–1 concurrent

**4. Cost Impact**
- Baseline: ~$2/month
- New scenario: ~$8/month (4x increase)
- Decision: Accept; still <$10/month, capability-first justified

**5. Failover Chain Validation**
- IG-88 trading analysis latency-critical (signals degrade after 5s)
- Anthropic API primary: 50ms baseline ✓
- OpenRouter MiniMax fallback: 200–500ms acceptable ✓
- Local Ollama fallback: 2–5s (degraded but operational) ✓
- Resilience: All three tiers remain viable

**6. Rebalancing Decision**
- No changes needed to agent trust levels (IG-88 stays L3)
- No changes to concurrent session caps (4 is within healthy band)
- No changes to failover chain (all tiers still healthy)
- Portfolio adjustment: **Proceed with resume. Monitor first week for actual vs. predicted load.**

---

## IX. Decision Hierarchy Applied to Portfolio

### T1 Autonomous (Boot Decides)
- Rebalance concurrent session caps based on memory band
- Route workload to alternate agent if primary overwhelmed
- Trigger fallback tier if primary API slow

### T2 Propose + Execute
- Promote IG-88 trading to high-priority queue
- Recommend IG-88 scheduling (time-of-day clustering for Sonnet batches)
- Suggest Batch API trial if volume sustains >10k/month

### T3 Propose + Wait
- Major concurrent session reallocation (e.g., 3→6 sessions)
- New failover provider addition (e.g., switch MiniMax for Kimi)
- Infrastructure upgrade (Cloudkicker RAM expansion)

### T4 Escalate
- Promote Kelk to L3 (changes trust model, new autonomy domain)
- Resume IG-88 trading (strategic decision)
- Onboard new agent (architecture change)

---

## X. Risk Mitigation — What Can Go Wrong

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| **IG-88 trading volume 10x baseline** | Low (M) | High (needs 5–6 sessions) | Maintain 2 idle sessions; delegate to Cloudkicker if needed |
| **Anthropic API rate-limited** | Very low (edge case) | Medium (fallback required) | OpenRouter Qwen 3.5 tier 2 maintains >90% availability |
| **Cloudkicker offline >1 week** | Low (hardware issue) | Medium (no Opus) | OpenRouter Qwen 3.5 provides frontier capability; 3–5s latency acceptable |
| **RP5 memory constrained >1 week** | Very low (requires bug/leak) | High (service degradation) | Auto-fallback to 2 sessions; local Ollama activated; incident runbook (BTI011 §VI) |
| **New agent onboarded without planning** | Medium (could happen) | Medium (allocation disruption) | Portfolio rebalancing within 24h; T3 escalation to Chris for resource approval |
| **IG-88 trading never resumes** | Low (business decision) | Low (plan remains valid) | Baseline portfolio stays constant; no action needed |

---

## XI. Immediate Actions (Phase 0 — This Week)

1. **Establish query volume baseline:** Log 7-day query distribution (by agent, by model, by latency) into Graphiti
2. **Validate seasonal assumptions:** Check Matrix history for patterns (Jan–Dec 2025) that suggest IG-88 trading seasonality
3. **Test Batch API economics:** Run mock batch with 50k tokens; measure discount ROI
4. **Profile Greybox 2.0 Qwen models:** Benchmark Qwen3-32B vs. OLMo 32B on reasoning tasks; record latency
5. **Document allocation policy:** Share portfolio strategy with IG-88 and Kelk (inform them of T1-T4 routing)

---

## XII. Next Steps — Module 6 Preview

Module 6 (Communication & Coordination Protocols) will address:
- Matrix message conventions for cross-agent hand-offs
- Graphiti temporal signaling (how to queue work async)
- Escalation paths (when to @mention Chris, when to use `/delegate`)
- Heartbeat messaging (what alerts go to #boot-ops vs. #backrooms)
- Agent communication style guidelines (tone, formality, context sharing)

---

## XIII. Revision Notes for Gate Review

**Open Questions for Chris:**

1. Is the seasonal forecast realistic? Should IG-88 trading activity be higher/lower than estimated (200–300 queries/day)?
2. When IG-88 trading resumes, should it get dedicated Sonnet sessions (2–3 exclusive) or share the pool with Boot?
3. Should Qwen3-30B-A3B (MoE) benchmarking be prioritized over dense 32B, or pursue both in parallel?
4. If Cloudkicker offline >1 week: Should frontier work route to OpenRouter Qwen 3.5 automatically, or escalate for explicit approval?
5. Is the T1-T4 routing policy (with IG-88 requiring Boot approval per agent-config) the final trust model, or should IG-88 be promoted to autonomous T1/T2 in trading domain?

---

**Status:** DRAFT — awaiting gate review from @chrislyons.
**Previous Modules:** BTI008 (PASSED), BTI009 (PASSED), BTI010 (PASSED), BTI011 (PASSED)
**Next Module:** BTI013 Communication & Coordination Protocols
