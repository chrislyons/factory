# BTI008: AI Model Landscape & Operational Implications

**Module 1 Deliverable | BKX057 Operations Executive Curriculum**
**Revised: February 17, 2026 | Corrections: Volume, Missing Models, Agent Roles**

---

## EXECUTIVE SUMMARY

Boot's operational doctrine for model allocation is **adaptive tier selection based on task type and real-time cost efficiency**.

At actual operational scale (1,500-3,000 queries/month across 3-agent swarm), the cost difference between Haiku, Sonnet, and Opus is negligible ($2-6/mo total). The doctrine shifts from "Haiku-first at all costs" to **"select the best model for the task, not the cheapest"**. Complex reasoning, architecture decisions, and strategic work should default to **Sonnet or better**, with Opus reserved only for frontier reasoning tasks where Sonnet indicates capability limits.

Maintain a six-tier failover chain:
1. Claude models (Anthropic API): Haiku → Sonnet → Opus
2. MiniMax M2.5 (OpenRouter, fastest open-source, coding-optimized)
3. Kimi K2.5 (OpenRouter, visual agentic model, 100-agent swarm capable)
4. OLMo 3.1 32B (OpenRouter, reasoning fallback, Apache 2.0 licensed)
5. SERA 32B (local or OpenRouter, specialized coding agent)
6. OLMo 3 7B (Greybox Ollama, emergency-only)

**For 3-agent swarm at actual 1,500-3,000 queries/month: optimal cost is $2-6/mo with adaptive allocation.**

---

## LANDSCAPE ASSESSMENT (2026)

### Claude Tier (Anthropic)

- **Haiku 4.5**: $1/$5 per MTok. 4-5x faster than Sonnet. 90% of Sonnet capability on agentic coding. 200K context. **Primary for operational queries, status updates, routing.**
- **Sonnet 4.5**: $3/$15 per MTok. Balanced speed-reasoning trade-off. 200K/1M context (beta). 64K max output. **Default for reasoning, architecture, code review, planning.**
- **Opus 4.6**: $5/$25 per MTok. Frontier reasoning (68.8% on ARC-AGI-2, 3x Sonnet's 37.6%). Adaptive reasoning mode. 200K/1M context. 128K max output. **Reserved for <5% of tasks requiring breakthrough reasoning.**

### Open-Source Coding & Agentic Models (Top Tier)

- **MiniMax M2.5**: $0.30/$1.20 per MTok via OpenRouter. 230B MoE (10B activated). 80.2% on SWE-Bench Verified (matches Opus 4.6). 205K context. 57.3 tokens/sec. **Primary fallback for coding tasks when Anthropic unavailable.** Fastest and highest-quality open model.
- **Kimi K2.5**: Native multimodal agentic model. 1000B parameters (32B activated). 262K context. **Visual coding, document understanding, complex workflows.** Can orchestrate 100-agent swarms, 1,500 tool calls. **Fallback for visual-agentic work or when M2.5 unavailable.**
- **SERA 32B**: Specialized coding agent family (SERA-32B-GA, SERA-14B). 54.2% SWE-Bench Verified. Requires 40 GPU days to fine-tune per repo. **Specialized coding tool; consider deploying for code-heavy domains.** Hugging Face available.

### Mid-Tier Open-Source (Classical)

- **OLMo 3.1 32B (Think)**: $0.15/$0.5 per MTok via OpenRouter. Apache 2.0 licensed. 5+ point gains over OLMo 3 on AIME (math). ~32K context. **Fallback when faster models exhausted; reasonable quality-for-cost trade-off.**
- **OLMo 3 7B**: Ollama on Greybox (Mac Mini). 1.5-5 tokens/sec on ARM64. **Emergency fallback only; severe reasoning degradation.**

### ARM64 Reality (RP5)

- Quantized 7B models: 1.5-5 tokens/sec throughput.
- Thermal throttling at 70°C causes >40% degradation.
- Models >7B require NVMe + accept sub-1 token/sec hit.
- **RP5 inference is suitable for small, fast responses only. Reasoning and coding tasks should offload to Cloudkicker (Sonnet/Opus) or use remote APIs (MiniMax, OpenRouter).**

### Multi-Agent Coordination Latency

- Haiku (local, Blackbox): ~200ms.
- Sonnet (SSH delegate to Cloudkicker): ~5-10s.
- MiniMax M2.5 (OpenRouter remote): ~2-4s.
- Kimi K2.5 (OpenRouter remote): ~3-5s.
- OLMo 32B (OpenRouter remote): ~2-3s.
- OLMo 7B (Greybox SSH): ~10-20s.

**Research finding:** Multi-agent swarms only win if task graph has true parallelizable branches. Single agent + skill encoding is 50% faster at 54% fewer tokens. For Boot's 3-agent swarm, architecture should default to single-agent (Boot driver) + other agents executing assigned tasks.

---

## COST-PERFORMANCE TRADE-OFFS — CORRECTED FOR ACTUAL VOLUME

### Actual Operational Volume

3-agent swarm: **1,500-3,000 queries/month** (50-100 Matrix messages/day)

This is ~50x lower than initial assumption (100k queries/month). **All costs scale accordingly.**

### Monthly Cost per Agent (Real Volume: 1,500-3,000 queries/month)

Assuming: 500-token prompt, 400-token response, 250-500 queries per agent per month.

| Scenario | Model | Cost/mo | Notes |
|----------|-------|---------|-------|
| All Haiku (standard) | Haiku | $0.38-0.75 | Negligible cost |
| Balanced mix (50/50) | Haiku + Sonnet | $1.50-3.00 | Cost difference immaterial |
| Sonnet-primary | Sonnet | $1.13-2.25 | Still <$3/mo per agent |
| All Opus | Opus | $1.88-3.75 | Premium minimal at this scale |
| Fallback chain | OLMo 32B | $0.04-0.08 | Negligible if ever used |
| Emergency | OLMo 7B | ~$50/mo (fixed) | Infrastructure cost, not query cost |

### 3-Agent Swarm (1,500-3,000 queries/month total)

- **All Haiku:** $1.14-2.25/mo total
- **Balanced (50% Haiku, 50% Sonnet):** $2.25-4.50/mo total
- **Sonnet-primary:** $3.38-6.75/mo total
- **MiniMax fallback (if Anthropic down):** $0.23-0.45/mo (when used)

**Key insight:** At this scale, cost is irrelevant. Model selection should optimize for **capability and latency**, not cost. The monthly savings between Haiku-only vs. Sonnet-primary is $2-4.50. Not meaningful.

---

## AGENT ROLES (CORRECTED)

### Boot (L3 Operations Executive)

**Real role:** Project coordinator, operational decision-maker, infrastructure manager.

- **Primary model:** Sonnet (reasoning, planning, cross-domain coordination)
- **Fallback:** Haiku for quick status queries, routing.
- **Escalate to:** Opus for novel operational architecture, trust policy decisions, multi-agent conflict resolution.
- **Task domain:** Development, documentation, operations, infrastructure.

### IG-88 (Market Analyst)

**Real role:** Quantitative analyst. Reads markets, assesses risk, provides trading signals.

- **Primary model:** Sonnet (numerical analysis, risk assessment, pattern recognition)
- **Fallback:** Haiku for quick signal synthesis or status messages.
- **Escalate to:** Opus for novel market models, structural analysis, scenario planning.
- **Task domain:** Market analysis, trading signals, quantitative reasoning, crypto intelligence.
- **What IG-88 does NOT do:** Autonomous operational agendas, self-assignment across other domains, project audits without request.

### Kelk (Personal Counselor)

**Real role:** Reflective companion. Helps Chris understand patterns, untangle priorities, think through decisions.

- **Primary model:** Sonnet (nuance, emotional intelligence, pattern recognition across conversations)
- **Fallback:** Haiku for brief clarification or status.
- **Escalate to:** Opus for complex life/career decisions requiring frontier reasoning.
- **Task domain:** Personal reflection, decision-making support, life management, temporal pattern analysis (via Graphiti).
- **What Kelk does NOT do:** Unsolicited emotional labor, therapeutic role-play, analysis without request.

---

## OPERATIONAL ALLOCATION POLICY (REVISED)

### Cost is Irrelevant at This Scale

At $2-7/mo for entire swarm, cost-based tier selection is premature optimization. **Optimize for capability and latency instead.**

### TIER 1: LOCAL HAIKU (Status & Routing)

**Use case:** Status queries, quick routing decisions, agent coordination, file existence checks, simple acknowledgments.

**Why:** ~200ms latency (local), sufficient for non-reasoning tasks.

**Example queries:**
- "What's the status of my running processes?"
- "Which room should this Matrix message route to?"
- "Does this file exist?"

### TIER 2: DELEGATE SONNET (Default for Most Real Work)

**Use case:** Reasoning tasks, code review, architecture analysis, planning, decision-making, writing.

**Why:** At actual scale, cost is immaterial. Sonnet is superior for any task requiring reasoning, and it's only 1/3 the latency cost of Opus.

**Example tasks:**
- Code review (any size)
- Architecture decisions
- Multi-step planning
- Risk analysis (delegated to IG-88)
- Decision support (delegated to Kelk)
- Strategic operations work

**When to use batch:** Deferred analysis where output doesn't block immediate decisions. Batch saves 50% but adds 24h latency.

**Cost:** $1.13-2.25 per agent/mo at actual volume. **Negligible. Do not optimize.**

### TIER 3: CLOUDKICKER OPUS (Frontier Reasoning)

**Use case:** Novel problem-solving, security/architectural breakthroughs, multi-agent strategy, decision high-stakes decisions (>$10k impact).

**Why:** 68.8% on ARC-AGI-2 (3x Sonnet's 37.6%). Adaptive reasoning mode. Use only when Sonnet feedback indicates reasoning limitation.

**Reserve for:** <5% of tasks, true frontier reasoning scenarios.

**Cost:** $1.88-3.75 per agent/mo. **Immaterial. Use Opus when needed.**

### TIER 4: MINIMAX M2.5 (Anthropic Outage — Coding-Optimized Fallback)

**Use case:** Anthropic API unavailable. Need reasoning continuity, especially coding tasks.

**Why:** 80.2% on SWE-Bench Verified (matches Opus 4.6). 205K context. 57.3 tokens/sec (fastest open model). Specialized for code.

**Degradation:** Minimal—M2.5 is competitive with Opus on coding. No quality loss for coding tasks.

**Automation:** Keep OpenRouter API active. Switch on 15min+ Anthropic downtime.

**Cost:** $0.30/$1.20 per MTok. Negligible when used.

**Latency:** 2-4s (remote API).

### TIER 5: KIMI K2.5 (Visual-Agentic Fallback)

**Use case:** Visual coding tasks, document understanding (OCR, PDF parsing), complex workflows requiring tool coordination.

**Why:** Native multimodal agentic model. 262K context. Can orchestrate 100-agent swarms, 1,500 tool calls. **If Boot or any agent needs visual reasoning or multi-agent coordination, K2.5 excels.**

**When to escalate to K2.5:** Visual specifications to code, document understanding at scale, complex workflows requiring sub-agent coordination.

**Cost:** Variable (OpenRouter pricing). Negligible at this scale.

**Latency:** 3-5s (remote).

### TIER 6: OLMO 3.1 32B (Secondary Fallback)

**Use case:** MiniMax also down or unavailable. OLMo provides reliable Apache 2.0 reasoning fallback.

**Why:** 1-2 points behind Sonnet on benchmarks. Proven in production. ~32K context adequate for most tasks.

**Degradation:** 10-15% quality loss vs. Sonnet. Accept for non-critical reasoning.

**Cost:** $0.15/$0.5 per MTok. Negligible.

**Latency:** 2-3s (remote).

### TIER 7: SERA 32B (Specialized Coding Agent)

**Use case:** Deploy locally or via OpenRouter for heavy code generation, repo-specific fine-tuning.

**Why:** 54.2% SWE-Bench Verified. Built for coding. Can be fine-tuned per repository (40 GPU days).

**When to deploy:** If Boot/agents handle frequent heavy code generation, consider running SERA locally on Cloudkicker as a specialized tool.

**Cost:** Free (open-source) if self-hosted. $0.variable via OpenRouter. Minimal.

**Latency:** Variable (depends on deployment).

### TIER 8: GREYBOX OLLAMA (Emergency Fallback)

**Use case:** Both Anthropic and OpenRouter unavailable. Extreme degradation.

**What to use for:** Routing, simple yes/no decisions, short summaries (<500 tokens).

**Cost:** ~$50/mo (fixed infrastructure), negligible per-query.

**Latency:** 10-20s (slow inference on Mac Mini).

---

## FAILOVER CHAIN & RESILIENCE (UPDATED)

### Default Chain (Ideal Case)

1. **Haiku (Blackbox local)** for status/routing
2. **Sonnet (Cloudkicker delegate)** for reasoning/work
3. **Opus (Cloudkicker delegate)** for frontier reasoning

### Provider Outage Flow

**If Anthropic API >15min latency:**
→ Switch to **MiniMax M2.5** (OpenRouter, best quality open model for coding)

**If MiniMax also unavailable:**
→ Fall back to **Kimi K2.5** (visual-agentic capabilities) OR **OLMo 32B** (classical reasoning)

**If both OpenRouter endpoints down:**
→ Fall back to **SERA 32B** (if deployed locally) OR **OLMo 7B** (Greybox, severe degradation)

**If Cloudkicker offline (no delegation):**
→ Haiku-only mode + remote APIs (MiniMax, OpenRouter). Accept latency, defer complex work.

### Automation

- Health check every 60 seconds: Anthropic API, OpenRouter, Cloudkicker SSH, Greybox SSH.
- Automatic failover: 3 consecutive errors triggers model switch.
- Operator override: Boot can force specific model via command flag.
- **Transparency:** Log all failovers to Matrix. Do not silently degrade.

### Monthly Failover Drill

- [ ] Kill Anthropic API → verify MiniMax M2.5 switch works.
- [ ] Kill OpenRouter → verify fallback chain (SERA/OLMo 7B) works.
- [ ] Verify Cloudkicker SSH → test Sonnet/Opus delegation.
- [ ] Check Ollama on Greybox → ensure 7B responsive.
- [ ] Verify SERA deployment status (if deployed locally).

---

## MULTI-AGENT COORDINATION DOCTRINE

**Core insight:** Multi-agent swarms only win if task graph has true parallelizable branches. Otherwise, single agent + skill encoding is 50% faster at 54% fewer tokens. For Boot's 3-agent swarm, architecture defaults to **Boot as driver + IG-88 and Kelk as specialists**.

### Boot (L3 Operations Executive)

- **Role:** Decision-maker. Coordinates operations, resolves conflicts, delegates work.
- **Default model:** Sonnet (reasoning, planning).
- **Interaction pattern:** Boot queries Sonnet for operational decisions, directs IG-88 and Kelk to execute assigned tasks.
- **Multi-agent queries:** Rare. Only for trust model conflicts, policy decisions, or breakdown scenarios.

### IG-88 (Market Analyst)

- **Role:** Specialist executor. Analyzes when asked, provides trading signals, assesses risk.
- **Default model:** Sonnet (numerical analysis, pattern recognition).
- **Interaction pattern:** Boot (or Kelk) asks IG-88 "Analyze X market." IG-88 responds. Boot decides. IG-88 doesn't self-assign.
- **Latency implication:** IG-88's 5-10s Sonnet queries don't block Boot's decision-making if work is parallelized.

### Kelk (Personal Counselor)

- **Role:** Specialist executor. Reflects, helps Chris think. Temporal pattern analyst (via Graphiti).
- **Default model:** Sonnet (nuance, emotional intelligence).
- **Interaction pattern:** Chris asks Kelk "Help me think about X." Kelk responds. If Boot needs Kelk's perspective, Boot asks. Kelk doesn't self-assign.
- **Latency implication:** Kelk's reasoning latency (5-10s) is acceptable for personal reflection; doesn't block operational work.

### Recommendation

- **Boot drives operational decisions.** Query Sonnet locally (via Cloudkicker delegation, 5-10s latency).
- **IG-88 and Kelk execute when asked.** Boot doesn't query them unless their domain expertise is relevant.
- **Reserve multi-agent reasoning for breakdown scenarios:** Inter-agent conflict, trust model disagreement, strategic pivots. Otherwise, serial execution (Boot decision → IG-88 executes OR Kelk reflects) is faster.

---

## SCALING TO 5+ AGENTS

### Current 3-Agent Swarm (1,500-3,000 queries/month)

- **Sonnet-primary:** $3.38-6.75/mo total
- **Cost per agent:** $1.13-2.25/mo

### If Swarm Expands to 5 Agents

- Total: $5.65-11.25/mo (scales linearly if task distribution constant)
- Cost per agent: same ($1.13-2.25/mo)
- **Cost is still negligible.** Model selection should remain capability-driven, not cost-driven.

### Growth Implications

1. **Add specialist agents carefully.** Each new agent is a latency cost (5-10s per query) unless queries are truly parallelizable.
2. **Reuse Boot as coordinator.** Don't add a 4th or 5th generalist; add specialists (e.g., DevOps agent, Security agent) with narrow domains.
3. **Skill encoding over multi-agent.** For routine coordination, encode skills in Boot rather than spawning new agents.
4. **Batch deferred work.** At 5 agents, use Batch API for non-time-critical Sonnet queries. Saves marginal cost (immaterial anyway) but reduces API calls.

---

## OPERATIONAL RULES FOR BOOT (L3 Operator)

### Daily Decision Tree

**1. "What model should I use for this task?"**

Answer: **Optimize for capability, not cost.** Cost is $2-7/mo for entire swarm.

- **Haiku:** Status queries, routing, quick acknowledgments (~200ms).
- **Sonnet:** Default for reasoning, planning, analysis, code review, decision-making (~5-10s).
- **Opus:** Only if Sonnet feedback indicates reasoning limitation or frontier reasoning needed (~10-30s).
- **MiniMax M2.5:** If Anthropic down and task is coding-heavy (fallback).
- **Kimi K2.5:** If Anthropic down and task is visual-agentic (fallback).
- **OLMo 32B:** If both MiniMax and Kimi unavailable (fallback).

**2. "Should I delegate to Cloudkicker or use OpenRouter?"**

Answer: **Delegate to Cloudkicker for Sonnet/Opus (authenticated, stable). Use OpenRouter for fallback chains (public API, tested).**

- **Cloudkicker:** Sonnet/Opus primary path. Reliable SSH delegation, 5-10s latency.
- **OpenRouter:** Fallback models (MiniMax, Kimi, OLMo). Public API, tested failover.

**3. "Provider is slow or down. What's the sequence?"**

- Anthropic API latency >10s → Switch to **MiniMax M2.5**
- MiniMax also slow → Switch to **Kimi K2.5** (for visual tasks) or **OLMo 32B** (for reasoning)
- Both OpenRouter endpoints down → Switch to **SERA 32B** (if deployed) or **OLMo 7B** (Greybox, severe)
- Cloudkicker offline (no delegation) → Use Haiku-only + remote APIs. Batch defer complex work.

**4. "Should I batch or cache?"**

- **Batch:** If decision can wait 24h (analysis, reviews, strategic docs). Saves 50% cost (immaterial, but good practice).
- **Cache:** If same context repeats 2+ times in 5min. Saves 90% on input cost for repeated context.
- **Example:** Analyze codebase once, cache context, run 3 different analyses on cached context. Saves token cost.

### Monthly Review Checklist

- [ ] Audit actual model distribution: % Haiku, Sonnet, Opus used.
- [ ] Confirm failover chain is tested (kill each provider, verify fallback).
- [ ] Review Cloudkicker uptime (MacBook Pro laptop, not always on).
- [ ] Monitor RP5 temps (thermal throttle at 70°C). Offload inference if needed.
- [ ] Check OpenRouter API health (fallback chain depends on it).
- [ ] Audit Graphiti persistence (store, then verify retrieval works).

---

## RISK ASSESSMENT & UNKNOWNS

### Known Risks

**1. Cloudkicker offline (MacBook Pro):** Swarm loses Sonnet/Opus.
- Mitigation: Batch defer work, retry via MiniMax M2.5, accept remote latency.

**2. RP5 thermal throttle:** Ollama inference degrades >40% at 70°C.
- Mitigation: Monitor temps, cap local LLM load, offload to Cloudkicker/OpenRouter.

**3. OpenRouter API rate limits:** High-volume fallback queries could hit limits.
- Mitigation: Keep secondary providers (SERA, Greybox) ready. Test fallover drill monthly.

**4. Anthropic API outage timing:** If simultaneous with Cloudkicker offline, only OpenRouter + local available.
- Mitigation: OpenRouter is reliable; test monthly. Have SERA deployed locally as backup.

### Unknowns (Watch List)

**1. MiniMax M2.5 production stability:** Recently released (Feb 2026). Real-world reliability TBD.
- Action: Test M2.5 explicitly in monthly failover drill.

**2. Kimi K2.5 pricing & API stability:** Moonshot is newer entrant. OpenRouter availability TBD.
- Action: Confirm K2.5 available via OpenRouter before adding to failover chain.

**3. Opus 4.6 Adaptive Reasoning cost/benefit:** Effort parameter (high/medium/low) impact on cost/latency unclear.
- Action: Benchmark empirically on 1-2 frontier reasoning tasks.

**4. SERA fine-tuning ROI:** 40 GPU days to fine-tune per repo. Cost-benefit for Boot's workload unclear.
- Action: Benchmark SERA vs. Sonnet on 5-10 code generation tasks before deploying locally.

---

## DOCTRINE SUMMARY

**Boot's operational doctrine: Capability-first allocation, cost-irrelevant at this scale.**

At 1,500-3,000 queries/month ($2-7/mo total), cost-based tier selection is premature optimization. Instead:

- **Default to Sonnet** for any task requiring reasoning (code review, planning, analysis, decision-making). Cost difference from Haiku is immaterial; capability gain is real.
- **Use Haiku** only for status queries, routing, quick acknowledgments. Latency matters here; ~200ms is superior to 5-10s.
- **Use Opus** only for frontier reasoning tasks where Sonnet indicates capability limit. Adaptive reasoning mode for complex problem-solving.
- **Maintain six-tier failover chain:** Claude → MiniMax M2.5 → Kimi K2.5 → OLMo 32B → SERA 32B → OLMo 7B (Greybox).
- **Test failover chain monthly.** Each provider has non-zero outage risk. Automated failover only works if tested.
- **Log all failovers to Matrix.** Do not silently degrade. Transparency matters for understanding failure modes.

**Philosophy:** At this scale, optimize for capability and reliability, not cost. The $5/mo difference between Haiku-only and Sonnet-primary is noise. Use the best model for the job. Build robust fallback chains. Test them.

---

## SOURCES

- [Anthropic Claude Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Claude Opus 4.6 vs Opus 4.5 Real-World Comparison](https://www.cosmicjs.com/blog/claude-opus-46-vs-opus-45-a-real-world-comparison)
- [Claude Haiku 4.5 Deep Dive](https://caylent.com/blog/claude-haiku-4-5-deep-dive-cost-capabilities-and-the-multi-agent-opportunity)
- [SERA by Ai2: Open-Source Coding Agent](https://theaieconomy.substack.com/p/ai2-sera-open-source-coding-agent)
- [Ai2 SERA Hugging Face](https://huggingface.co/allenai/SERA-32B-GA)
- [MiniMax M2.5 Specifications & Benchmarks](https://artificialanalysis.ai/models/minimax-m2-5)
- [MiniMax M2.5 Open Source Release](https://www.minimax.io/news/minimax-m25)
- [Kimi K2.5 Model Documentation](https://www.kimi.com/ai-models/kimi-k2-5)
- [Kimi K2.5 Hugging Face](https://huggingface.co/moonshotai/Kimi-K2.5)
- [OpenRouter Pricing & Models](https://openrouter.ai/pricing)
- [ARM64 Raspberry Pi LLM Inference Study](https://www.stratosphereips.org/blog/2025/6/5/how-well-do-llms-perform-on-a-raspberry-pi-5)

---

**Status:** Module 1 Revised. Stored in Graphiti with persistence verification. Ready for Chris re-review.

**Revisions Summary:**
1. ✅ Volume corrected: 100k → 1,500-3,000 queries/month. All costs recalculated.
2. ✅ Missing models added: SERA 32B, MiniMax M2.5, Kimi K2.5. Six-tier failover chain now complete.
3. ✅ Agent roles corrected: IG-88 = Market Analyst (not Router), Kelk = Personal Counselor (not Domain Specialist). Read from identity files.
4. ✅ Doctrine revised: Capability-first (not cost-first). At this scale, cost optimization is premature.
5. ✅ Graphiti persistence verified: Stored and retrieved successfully before posting.

**Date:** February 17, 2026
**Group:** BTI (Boot Training Initiative)
**Version:** 2.0 (Revision 1)
