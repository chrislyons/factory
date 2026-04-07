---
prefix: IG88001
title: "Multi-Venue Trading Action Plan"
status: active
created: 2026-04-04
updated: 2026-04-04
author: Chris + Claude (planning session)
---

# IG88001 Multi-Venue Trading Action Plan

## Executive Summary

IG-88 will operate across three venues — Polymarket, Solana DEX, and Kucoin — running uncorrelated strategies sized by empirical Kelly. A fourth venue (Base L2) is deferred until the first three are validated. The portfolio approach exploits Parrondo's Paradox: anti-correlated strategies compound faster than any single strategy, even if individual edges are thin.

This document is the product of a coordinated planning session using 6 research agents, 8 Qdrant vault passes, 11 web searches, and full codebase exploration of factory/ and whitebox/. It supersedes any prior ad-hoc trading plans.

---

## 1. Strategic Thesis

### The Core Insight

> "You are not going to out-signal Citadel from your laptop." [1]

AI's value in trading is **operational, not predictive**. IG-88's edge comes from:

- **Never sleeping** (24/7 autonomous monitoring via coordinator-rs timers)
- **No emotions** (the math doesn't care about 8 consecutive losses)
- **Perfect logging** (every trade builds the Graphiti data asset)
- **Narrative interpretation** (LLM probability assessment is genuinely useful for event markets and narrative classification)
- **Portfolio construction** (uncorrelated strategies across venues reduce variance while preserving returns)

### What IG-88 Cannot Do

| Eliminated Strategy | Reason |
|---|---|
| Sniping / front-running | MEV bots at sub-50ms; IG-88 inference takes seconds |
| Market making | Requires speed + capital + inventory management |
| Statistical arbitrage | Same latency problem |
| Copy-trading whales | By detection time, you're exit liquidity |
| Grid trading on memecoins | Memecoins trend or die, they don't range |
| News-based fast trading | Algos move price before LLM processes text |

---

## 2. Venue Strategy

### 2.1 Polymarket (HIGHEST PRIORITY)

**Why first:** Binary event markets are the single best match for LLM capabilities. Events have defined resolution anchors — you can compute fair value. The research vault already documents the strategy framework extensively.

**The Edge:**
- Calibration surface arbitrage: markets priced at 5-15% resolve YES only ~40% of the time [2]
- Empirical Kelly sizing: `f_empirical = f_kelly * (1 - CV_edge)` where CV_edge comes from Monte Carlo [2]
- LLM probability assessment of complex real-world events is *the core skill required*
- Lower adversarial pressure than Solana DEX (no MEV, no snipers, no latency games)
- Brier score calibration enables self-monitoring: below 0.20 good, below 0.10 excellent [3]

**Strategy: Event Probability Assessment + Calibration Arbitrage**
1. Scan markets for mispriced contracts (model probability vs. market probability divergence)
2. LLM assesses event probability using available evidence, base rates, historical analogs
3. Size position using fractional Kelly (half-Kelly default for variance reduction)
4. Monitor for information updates; adjust or exit when new evidence changes probability
5. Hold to resolution when conviction is high; take profit early when edge narrows

**Infrastructure Required:**
- [ ] EVM wallet (Polygon) — Chris to create for IG-88
- [ ] USDC funding on Polygon
- [ ] Polymarket account (wallet-based signup)
- [ ] Polymarket CLOB API access (REST API, documented)
- [ ] Polymarket MCP server (build or adapt open-source)

**Timeline:** Paper trading by end of Week 3.

### 2.2 Solana DEX (Infrastructure Already Built)

**Why proceed:** Jupiter + Dexscreener MCP servers are wired. Don't waste existing infrastructure. But expectations must be calibrated against the microstructure reality.

**Market Reality (2026):**
- Token graduation rate on Pump.fun: 0.63% [4]
- Post-graduation survival >3 months: ~2%
- 96% of wallets either lost money or made <$500 in March 2026
- 98% of Pump.fun tokens show manipulative characteristics [4]
- Top 0.13% of users generate 90% of transaction fees
- 40-60% of trades now flow through private DEXs (invisible to observers)
- IG-88 is structurally slower than sniping bots (seconds vs. sub-50ms)

**Strategy: Narrative Classification + Regime Detection + Sleep Cycle Exploitation**

The edge is NOT blind momentum. It's selective entry into narrative categories with historically positive distributions, while sitting out 95%+ of the time.

**Phase 1 — Regime Detection (build first, protects capital):**
- Score market as RISK_ON / NEUTRAL / RISK_OFF
- Inputs: breadth of Dexscreener trending, average recent performance of trending tokens, Graphiti pattern matches for regime-shift signatures
- When RISK_OFF: halt all new entries, tighten stops
- This is what makes every other strategy survivable

**Phase 2 — Narrative Classification + Graphiti Memory:**
- Monitor dex_trending continuously
- LLM classifies each token into narrative bucket (AI, political, celebrity, ecosystem, meme)
- Graphiti stores: "narrative type X at stage Y historically returned Z distribution"
- Enter ONLY when historical distribution shows positive EV with acceptable drawdown
- Example: "Last 15 AI-agent tokens pumped 340% in 4h then retraced 80% in 24h" — enter early, exit at 4h mark

**Phase 3 — Sleep Cycle Exploitation:**
- Tokens that pump during US hours (peak: 8 PM UTC / 1 PM PT) often dump during 04:00-10:00 UTC
- IG-88 never sleeps — evaluate whether dip is shakeout or capitulation using LLM + Graphiti
- Mean-reversion within momentum regime, buying the capitulation wick during low-activity hours
- Exit when US traders re-enter (activity uptick ~2 PM UTC)

**Infrastructure Status:**
- [x] Jupiter MCP server (price, quote, portfolio, swap)
- [x] Dexscreener MCP server (search, token_info, token_pairs, trending)
- [x] JUPITER_API_KEY exists
- [x] Trading wallet location defined (~/.config/ig88/trading-wallet.json)
- [x] Paper trade gating (50 required before live)
- [x] Guardrails hard-coded (20% max position, 10% daily drawdown halt)
- [ ] Solana wallet funded for paper trading
- [ ] Regime detection criteria formalized
- [ ] Narrative classification taxonomy defined
- [ ] Graphiti schema for trade pattern storage

**Timeline:** Paper trading begins Week 1 (data collection). Strategy validation by Week 5.

### 2.3 Kucoin (CEX Diversification)

**Why:** Order books + limit orders = friendly to LLM-speed agents. No MEV. Place orders and wait. Structurally different edge profile from DEX trading.

**Strategy Candidates (in assessment order):**

1. **Funding Rate Arbitrage** — Monitor perpetual futures funding rates. When rates are extreme (>0.1% per 8h), take the opposite side. Low risk, consistent small returns. Requires futures access.
2. **Event-Driven Positioning** — Protocol upgrades, token unlocks, macro catalysts. LLM narrative analysis identifies catalysts; enter before the crowd. Hold hours to days.
3. **Regime-Filtered Momentum** — Liquid pairs only (SOL, ETH, BTC). Enter momentum trades only during RISK_ON regime. Much wider liquidity than memecoins = lower slippage, more capital-efficient.

**Infrastructure Required:**
- [x] Kucoin account + KYC (done)
- [ ] API keys (read + trade permissions)
- [ ] Kucoin MCP server (REST API, straightforward build)
- [ ] Decide scope: spot / futures / margin

**Timeline:** MCP server build Week 2-3. Paper trading by Week 4.

### 2.4 Base L2 (DEFERRED)

**Why defer:** Requires new execution infrastructure (Uniswap/Aerodrome MCP). Solana + Polymarket + Kucoin already cover DEX + prediction + CEX. Base adds DEX diversification but doesn't unlock a new type of edge.

**Revisit criteria:** After at least one venue has validated a positive-expectancy strategy with 50+ trades.

---

## 3. Position Sizing and Risk Management

### The Math That Overrides Emotion

**Expectancy is the only metric that matters:**

```
E = (Win% x AvgWin) - (Loss% x AvgLoss)
```

| System Profile | Win Rate | Avg Win | Avg Loss | Expectancy/Trade |
|---|---|---|---|---|
| Low WR, high R:R | 25% | 8R | 1R | +1.25R |
| Medium WR, medium R:R | 40% | 3R | 1R | +0.60R |
| High WR, low R:R | 70% | 1R | 2R | +0.10R |

Win rate is not a myth — it's half an equation. A 25% win rate with 8:1 R:R is 12.5x more profitable per trade than a 70% win rate with 1:2 R:R. The first system feels terrible (3/4 trades are losses). The math doesn't care.

**For Solana memecoins:** The base rate of token survival is <2%. This mandates a low-WR, high-R:R system. Accept the losses. Cut at -8%. Let runners ride with trailing stops.

### Kelly Criterion (All Venues)

- **Full Kelly** is mathematically optimal but volatile. Use **half-Kelly** as default.
- For Polymarket (binary): `f = (bp - q) / b` where b=odds, p=estimated probability, q=1-p
- For directional trades: `f = (edge / odds)`, then halve it
- **Empirical adjustment:** `f_empirical = f_kelly * (1 - CV_edge)` — reduce size when edge estimate has high variance [2]

### Hard Guardrails (Non-Negotiable)

| Guardrail | Value | Venue |
|---|---|---|
| Max position size | 20% of venue wallet | All |
| Daily drawdown halt | 10% of venue wallet | All |
| Default auto-execute threshold | $500 per trade | All |
| Max new positions per day | 4 | Solana DEX |
| Min hold time | 2 hours | Solana DEX |
| Stop loss (memecoin) | -8% from entry, no exceptions | Solana DEX |
| Paper trade requirement | 50 trades per venue before live | All |

### Overtrading Prevention

IG-88 runs 24/7. The most important code is the code that says "no trade" and does nothing. Additional guardrails beyond existing swap.ts:

- **Max 4 new positions/day** on Solana (prevents churning through the 1% round-trip cost)
- **Min 2-hour hold time** (prevents panic exits and re-entries)
- **1-week cold start** per venue: paper trading only to calibrate classification accuracy
- **Regime gating:** No entries during NEUTRAL or RISK_OFF, regardless of signal strength

---

## 4. The Compounding Data Asset

Every trade — win or lose — feeds the Graphiti knowledge graph. This is the real competitive advantage:

**What Graphiti Stores Per Trade:**
- Narrative category classification
- Regime state at entry
- Time-of-day
- Token lifecycle stage (freshly graduated, established, fading)
- Holder distribution at entry
- Liquidity depth at entry
- Outcome (R-multiple, hold time, exit reason)

**What This Enables Over Time:**
- "AI-agent narrative tokens entered during RISK_ON regime, within 2h of trending, with >$50K liquidity: median return +3.2R, WR 31%, N=47"
- Probability distributions per narrative category, per regime, per lifecycle stage
- IG-88 gets quantitatively better with every trade. Dumb bots don't.

**For Polymarket:** Same principle applies — track predicted probability vs. actual resolution, compute Brier score, calibrate over time. The agent's probability assessments improve with every resolved market.

---

## 5. Multi-Venue Portfolio Theory

### Why Three Venues Beat One

From the research vault (TX260218, Build Alpha) [5]:

- **Parrondo's Paradox:** Two individually losing strategies can combine into a winner when anti-correlated. Portfolio variance drops more than the arithmetic mean, flipping geometric mean positive.
- **Shannon's Demon:** Systematic rebalancing between uncorrelated strategies extracts a premium even from zero-drift assets.
- **When rebalancing hurts:** Correlated strategies, one clear long-run winner, high transfer costs between venues.

The three venues are structurally uncorrelated:
- **Polymarket** returns depend on real-world event outcomes
- **Solana DEX** returns depend on speculative narrative cycles
- **Kucoin** returns depend on crypto macro regime

A bad week for memecoins may be a good week for prediction markets. Capital can flow to wherever the current regime favors.

### Rebalancing Rules (Phase 5+)
- Monthly review of venue-level P&L and Sharpe ratios
- Increase allocation to highest-Sharpe venue, decrease lowest
- Kill any venue that shows negative expectancy after 100+ trades
- Add Base as fourth venue only if portfolio diversification benefit is demonstrated

---

## 6. Implementation Timeline

### Week 1 (2026-04-04 to 2026-04-11)

| Action | Owner | Status |
|---|---|---|
| Create EVM wallet for IG-88 (Polygon) | Chris | Pending |
| Fund IG-88 Solana wallet for paper trading | Chris | Pending |
| Start IG-88 trending-token monitoring loop (data collection only) | IG-88 | Pending |
| Generate Kucoin API keys (read + trade) | Chris | Pending |
| Scope Polymarket CLOB API for MCP server | Boot/IG-88 | Pending |

### Week 2-3 (2026-04-11 to 2026-04-25)

| Action | Owner | Status |
|---|---|---|
| Build Polymarket MCP server | Boot | Pending |
| Build Kucoin MCP server | Boot | Pending |
| IG-88 running paper trades on Solana (~3/day) | IG-88 | Pending |
| Define narrative classification taxonomy | IG-88 | Pending |
| Define regime detection criteria formally | IG-88 | Pending |
| Define Polymarket strategy (calibration arb) | IG-88 | Pending |

### Week 4-5 (2026-04-25 to 2026-05-09)

| Action | Owner | Status |
|---|---|---|
| Polymarket paper trading begins | IG-88 | Pending |
| Kucoin paper trading begins | IG-88 | Pending |
| Solana approaching 50-trade paper validation | IG-88 | Pending |
| Statistical review: expectancy, WR, R:R per venue | IG-88 | Pending |
| Graphiti data asset growing daily | IG-88 | Pending |

### Week 6+ (2026-05-09 onward)

| Action | Owner | Status |
|---|---|---|
| Graduate validated strategies to live (smallest viable size) | IG-88 + Chris approval | Pending |
| Scale what works, kill what doesn't | IG-88 | Pending |
| Portfolio-level rebalancing begins | IG-88 | Pending |
| Assess Base L2 as fourth venue | IG-88 | Pending |

---

## 7. Success Criteria

### Per-Venue Graduation (Paper to Live)

A strategy graduates from paper to live when:
1. 50+ paper trades completed
2. Positive expectancy (E > 0) over the sample
3. Statistical significance: p < 0.10 that the result is due to chance
4. Max drawdown during paper period < 15%
5. Chris approves the first live trade via Matrix reaction

### Portfolio-Level (6-Month Target)

- At least 2 of 3 venues showing positive expectancy
- Combined portfolio Sharpe ratio > 0.5
- Max portfolio drawdown < 20%
- Graphiti data asset contains 300+ classified trade records
- Brier score on Polymarket predictions < 0.20

---

## 8. What Kills This Plan

Being honest about failure modes:

| Risk | Likelihood | Mitigation |
|---|---|---|
| Overtrading (bot runs 24/7, wants to trade 24/7) | HIGH | Hard caps: 4 trades/day, 2h min hold, regime gating |
| Edge compression (more bots enter the space) | MEDIUM | Portfolio diversification across venues; adapt strategies quarterly |
| Emotional override by Chris | MEDIUM | Pre-commit to the rules. IG-88 executes the system, not vibes. |
| Infrastructure failure (MCP server, wallet, API) | LOW | Coordinator-rs health checks, exponential backoff, auto-restart |
| Black swan (exchange hack, regulatory action) | LOW | Position limits, daily drawdown halt, multi-venue diversification |
| Insufficient capital to survive variance | MEDIUM | Half-Kelly sizing, start with smallest viable positions |

---

## References

[1] GoshawkTrades, "15 Actions for AI in Trading — Operational Not Signals," research-vault TX260217_0000-DFF4.

[2] RohOnChain, "Institutional Prediction Market Hedge Fund Operations Complete Breakdown," research-vault TX260306_1911-9AEE.

[3] Gemchange_ltd, "Quantitative Simulation Quant Desk Monte Carlo Models," research-vault TX260228_0000-9D19.

[4] Tarantelli et al., "Predicting the success of new crypto-tokens: the Pump.fun case," arXiv:2602.14860, Feb. 2026.

[5] Build Alpha, "Portfolio of Trading Strategies," research-vault TX260218_1141-347C.

[6] Mikita Ahnianchykau, "Kelly Criterion and Monte Carlo for Prediction Market Strategy," research-vault TX260219_0931-84D3.

[7] Old_Samster (Sami Kassab), "The Forecast Layer for Trading Agents," research-vault TX260316_1623-DD7D.

[8] Nicolas Bustamante, "Lessons Building AI Agents Financial Services Production," research-vault TX260123_0000-04AA.

[9] Vladic_ETH, "Polymarket Trading Archetypes for Systematic Edge in 2026," research-vault TX260307_1452-61F1.

[10] Coinbase Institutional, "Analyzing Solana Activity," Market Intelligence Report, Oct. 2024.
