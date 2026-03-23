# FCT032 Strategy Vet: Research Vault Findings vs. Compiled Assessment

I ran 12 compound semantic searches across the research-vault corpus (418 TX docs, 331 synthesis docs) and delegated factory codebase exploration to a subagent. Here's what the evidence says about each strategic pillar.

---

## 1. Blackbox Retirement — STRONGLY SUPPORTED

The vault's own research validates the core rationale:

**Compound failure math directly applies.** TX260314_1706-38E1 (Cornelius, "The Orchestrator's Dilemma") documents the exact problem your split-brain topology creates: *"if each agent has 95% reliability, a 5-agent chain has ~77% reliability."* Every cross-host hop (coordinator on Blackbox → Pantalaimon on Whitebox → LLM on Whitebox → back) is a link in that chain. Collapsing to one host literally removes links from the failure chain.

**The Agent Orchestration Layer pattern** (`docs/patterns/Agent Orchestration Layer.md`) names "graceful degradation" as a design requirement and warns that *"the orchestrator is itself an agent — it is the most consequential one."* Your coordinator-rs is that orchestrator. Having it on a different host from its dependencies is the antipattern the pattern explicitly warns against.

**"Minimize the coordination surface"** — TX260315_0000-9A31 (Claude Subagents vs Agent Teams): *"Every channel of communication between agents is a potential failure point and overhead source."* Cross-host networking is a coordination surface. Localhost eliminates it.

**Verdict: Full retirement is the correct call.** The vault evidence is unambiguous — colocation reduces compound failure probability, simplifies the coordination surface, and aligns with every orchestration pattern documented in the corpus.

---

## 2. IG-88 5-Agent Trading Architecture — SUPPORTED WITH CRITICAL CAVEATS

The strategy's thesis — "AI synthesizes more context, detects regime shifts faster, maintains emotional discipline better" — is **partially validated but carries documented risks the assessment undersells.**

### What the vault supports:

**Multi-agent trading specialization works.** Financial Agents topic (32 sources, medium confidence) documents the pattern: *"Decompose trading into parallel agents: market scanner, research, execution, risk monitor."* The 5-agent consensus system (Regime → Scanner → Narrative → Exit → Governor) mirrors this architecture.

**AI as operations multiplier, not signal generator** is the vault's strongest finding:
> *"You are not going to out-signal Citadel from your laptop."* — GoshawkTrades (TX260217_0000-DFF4)

The strategy correctly positions IG-88 as an operational edge (context synthesis, discipline) rather than an alpha generator. This aligns with the vault's consensus.

**Jupiter pivot is sound.** The fee structure analysis (gross Sharpe 5.05, net negative on KuCoin) that drove the Jupiter pivot is the kind of rigorous backtest-to-live analysis the vault praises. Zero maker fees on Jupiter removes the friction that killed the edge.

### What the vault warns about:

**The survivorship bias caveat is severe.** Financial Agents explicitly flags:
- *"87% of Polymarket wallets lose money. You just never see them post about it."* (TX260307_1259-0F4A)
- *"Backtests don't survive live markets"* — Build Alpha's practitioner finding after a decade of ML trading (TX260218_1141-347C)
- *"AI amplifies competent traders; for those without edge, it accelerates losses."*

**Nunchi overfitting is the most directly relevant warning.** TX260319_0000-5B6D and the Financial Agents synthesis both document that self-improving trading agents (which is what IG-88's research loop aspires to) are *"susceptible to the same over-optimization failure mode as static models — the improvement loop can overfit to historical data just as a human quant can."* This elevates overfitting from a backtest artifact to an **architectural risk**.

**The Forecast Layer gap.** TX260316_1623-DD7D (Old_Samster/Synth): *"AI trading agents are built on historical patterns. They can execute against them flawlessly, but cannot see beyond them."* IG-88's GARCH/regime detection (Phases 0-3) is entirely backward-looking. The vault documents this as a structural limitation, not just a quality issue.

### Recommendations:
1. **The 100-trade paper validation is necessary but insufficient.** The vault says you need regime-diverse validation — 100 trades in one regime proves nothing about regime transitions. Add a minimum of 2 distinct regime environments to the success criteria.
2. **Add a kill-switch that goes beyond drawdown.** The strategy has 10% daily drawdown halt — good. But the vault's "Math Bots" doc (TX260320_1127-128B) emphasizes *"The Kill Switch — How the Best Algorithms Know When to Stop"* as a distinct capability. Consider regime confidence collapse (not just drawdown) as a halt trigger.
3. **The 52% WR threshold is too low.** Given the vault documents 87% of wallets losing money, a 52% WR with no disclosed R:R expectancy is not a meaningful success criterion. Define expectancy (average win × WR - average loss × loss rate) as the primary metric.

---

## 3. 5-Agent Consensus System — TENSION WITH SKILLS-FIRST DECISION

The vault has an **accepted decision** that directly challenges this architecture:

**Skills-First over Multi-Agent Architecture** (`docs/decisions/Skills-First over Multi-Agent Architecture.md`, confidence: high, status: accepted):
> *"For personal and small-team agentic workflows, prefer a single agent with skills over multi-agent orchestration."*

The decision cites:
- DeepMind research: accuracy degrades past 4 agents ("Coordination Tax")
- jordymaui: *"Output was worse with more agents"*
- Cost: $90/month vs hundreds/week with 8 agents

**IG-88 has exactly 5 agents — right at the degradation threshold.** The Coordination Tax finding says accuracy degrades past 4. You're at 5.

**However:** The decision also documents when to break the pattern: *"Multi-agent is correct when... heavy isolated tasks, different models for different budgets, shared team environments."* Trading agents arguably qualify — each agent has a narrow scope (regime detection vs. exit timing), and isolation is a feature (the Governor shouldn't share context with the Scanner).

**The Anthropic counter-evidence is important:** Multi-agent achieves 90.2% accuracy *when correctly orchestrated.* The vault notes this is evidence that multi-agent is *"demanding, not inferior."*

### Recommendation:
The 5-agent design is defensible but demands the discipline the vault warns about. Each agent must have extremely narrow scope, and the coordination surface between them must be minimal (shared data, not shared context — the S3-first pattern from Fintool, TX260123_0000-04AA). If any agent starts needing another agent's full context to function, collapse them into skills on one agent.

---

## 4. Secrets Architecture — WELL-ALIGNED, ONE GAP

The vault's Agent Security topic (16 sources, established maturity) is unambiguous:

> *"By construction, transformer models will surface any credential in their context window. Not a patchable flaw — an architectural property."* (TX260208_0000-C2H8)

> *"Credentials must never enter agent context. Full stop."*

The strategy's approach (Bitwarden + age encryption, credentials injected at runtime, never in LLM context) aligns with the **agent-vault pattern** (TX260219_0839-43CA): placeholder substitution where secrets are swapped at execution time, never visible to the agent.

**Gap:** The assessment mentions storing Jupiter API key and Solana keypair in `~/.config/ig88/.env` (age-encrypted). This is fine for storage, but the strategy doesn't explicitly state how these credentials reach the jupiter-mcp tool at runtime without entering the LLM context. The agent-vault pattern requires a clear injection pathway. Verify that jupiter-mcp reads credentials from environment variables or files directly, never from the coordinator's context window.

**Hot wallet security is a documented concern.** TX260208_0000-C2H8 reports a hot wallet key compromised within 5 days despite explicit instructions. The $200-800 USDC + 0.05 SOL funding plan is appropriately small, but ensure the Solana keypair is **never** passed through coordinator-rs's LLM context.

---

## 5. E2EE / Megolm Gate — CORRECT SEQUENCING

The firm gate condition ("all agents stable on Pantalaimon for at least one full operational cycle") is well-justified by the vault's pattern evidence:

**Agent Orchestration Layer** requires *"Design for degradation — system must continue if individual agents fail."* Cutting over E2EE while agents are unstable violates this. The sequencing — stabilize → operate → cutover — is textbook.

**Agent Security** documents inter-agent authentication as an *"open problem"* (checklist item in the mitigation section). The Megolm cutover adds cross-device signing complexity. Doing this during instability compounds the risk the vault warns about.

**No vault objections to this sequencing.**

---

## 6. Whitebox Model Workflows — SUPPORTED BY EVIDENCE

**Local LLM Agents** topic (16 sources, active maturity) validates the local inference stack:
- Nanbeige 4.1-3B documented in TX260218_0640-382E as *"built for efficiency first... solid reasoning, math, and long workflow stability"*
- The Qwen family and MLX-LM on Apple Silicon are well-documented in the corpus
- TX260305_1055-FAD5 (LocalCowork) demonstrates 67 tools + 13 MCP servers running on a MacBook — your Whitebox setup is architecturally similar but on better hardware

**The "no launchd plists" gap is real** — the strategy correctly identifies this as a Phase 2c prerequisite. Without persistent services, Graphiti stays down every time Whitebox reboots.

---

## 7. Action Plan Phasing — MOSTLY SOUND, ONE ORDERING CONCERN

**Phase A (restore agent health)** is correctly prioritized. Compound failure math says fix the existing chain before adding new links.

**Phase B (Jupiter API keys)** before Phase 2c is fine — it's independent work that doesn't require migration.

**Phase 2c (migration)** — The 48h parallel operation window is good practice. The vault's orchestration patterns recommend explicit degradation testing, not just parallel operation. Suggest: during the 48h window, intentionally kill each Whitebox service one at a time and verify the system degrades gracefully rather than catastrophically.

**Phase C (paper trading)** — See the caveats in section 2 above. The 100-trade framework needs regime diversity and expectancy metrics added.

**Phase D (Megolm)** — Correctly gated. No concerns.

### Ordering concern:
The assessment places Jupiter API keys (Phase B) before agent health is fully verified (Phase A step 7: "verify all 3 agents respond in Matrix"). If Phase A stalls on token restoration, Phase B work isn't wasted, but Jupiter integration testing requires a working coordinator to dispatch to IG-88. Confirm Phase A completion before investing time in Phase B step 14 (verify connectivity).

---

## Summary Scorecard

| Section | Vault Alignment | Confidence | Action Needed |
|---------|----------------|------------|---------------|
| Blackbox retirement | **Strong support** | High | None — execute |
| IG-88 trading architecture | **Supported with caveats** | Medium | Add regime diversity to validation, expectancy metric, kill-switch beyond drawdown |
| 5-agent consensus | **Tension with Skills-First** | Medium | Monitor Coordination Tax threshold; collapse agents if context sharing needed |
| Secrets architecture | **Well-aligned** | High | Verify Jupiter credential injection pathway avoids LLM context |
| E2EE gate | **Correct** | High | None |
| Whitebox models | **Supported** | High | Create launchd plists before Phase 2c |
| Action plan phasing | **Mostly sound** | High | Add degradation testing to 48h window; confirm Phase A before Phase B step 14 |

**Overall assessment:** The strategy is well-constructed and aligns with the research corpus on infrastructure, security, and orchestration patterns. The main risk the vault surfaces that the assessment underweights is **trading overfitting** — the corpus has three independent sources warning that backtest-to-live degradation is the norm, not the exception. The paper trading framework is necessary but needs stronger success criteria than 52% WR over 100 trades.