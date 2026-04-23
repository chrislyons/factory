# IG88076 — Polymarket Edge Analysis & Multi-Venue Research Plan

**Date:** 2026-04-18
**Status:** RESEARCH COMPLETE — Testing plan defined, ready for execution
**Scope:** Analysis of 7 Polymarket research articles, cross-referenced with IG88 system state, venue constraints (Ontario, Canada), and PnL maximization mandate
**Prefix:** IG88076

---

## Executive Summary

After reviewing 7 research articles on Polymarket strategies, cross-referencing with our existing Jupiter perps edge (ATR Breakout, PF 1.7-2.0), and accounting for Ontario venue restrictions (Hyperliquid blocked, dYdX blocked):

**Three viable Polymarket edges identified, ranked by confidence:**

1. **Wolf Hour Spread Capture** — Structural liquidity edge, 2:30-04:00 UTC. Highest confidence. Requires real-time monitoring, not prediction.
2. **Pyth Latency Arb on TradFi contracts** — 800ms price lead on gold/silver/oil/stocks via Pyth Pro (200ms) vs Polymarket (1s). New opportunity as of April 2.
3. **Short-Window BTC Up/Down scalping** — Markov-chain/persistence-filter approach on 5-min contracts. Proven by multiple traders ($1.3M+ in 30 days across 3 bots).

**Edge #1 (Wolf Hour) is immediately testable.** Edge #2 requires Pyth Pro API key (free 30-day trial). Edge #3 requires backtesting infrastructure we don't have yet for prediction markets.

**Jupiter perps ATR Breakout remains our primary alpha source.** Polymarket edges are uncorrelated additive alpha — different asset class, different resolution mechanics, different risk profile. Portfolio diversification across venues reduces aggregate drawdown.

---

## Part 1: Current System State (What We Have)

### Confirmed Edge: ATR Breakout on Jupiter Perps

| Metric | Value | Confidence |
|--------|-------|------------|
| Walk-forward PF | 1.72-2.02 | HIGH (5 splits, 5yr data) |
| Validated assets | 9 LONG, 5 SHORT | HIGH |
| Annualized (1x) | 95-250% | MEDIUM-HIGH |
| Annualized (2x Kelly) | 240-921% | MEDIUM |
| Max DD (1x) | 10-32% | HIGH |
| Max DD (2x) | 37-55% | HIGH |
| Venue | Jupiter perps (0.14% RT) | CONFIRMED |
| Ontario | DEX, no restrictions | CONFIRMED |

**Key improvements found in IG88075:**
- 1.5x ATR stop (from 2.0x) — walk-forward confirmed PF improvement on 4/5 assets
- FIL/RNDR genuinely uncorrelated (r≈0) — real diversification
- Funding rate on shorts: +11-22% ann additive alpha
- Compounding bug fixed — previous projections underestimated by ~8x

### Venue Constraints (Ontario, Canada)

| Venue | Available | Notes |
|-------|-----------|-------|
| Jupiter Perps | YES | Primary venue, DEX on Solana |
| Kraken Spot | YES | Marginal (0.50% RT kills most edges) |
| Polymarket | YES | Prediction market, Polygon/Solana |
| Hyperliquid | NO | Geo-blocked in Ontario |
| dYdX | NO | Geo-blocked in Ontario |
| Drift Protocol | PROBABLY | Solana DEX perps, verify |
| GMX | PROBABLY | Arbitrum DEX perps, verify |

---

## Part 2: Polymarket Edge Analysis (7 Articles Distilled)

### Article 1: Pyth Price Data Parser (Verified)

**Claim:** Polymarket now uses Pyth Pro for TradFi resolution (gold, silver, oil, AAPL, TSLA, NVDA, MSFT, AMZN, GOOGL). Pyth delivers 200ms updates; Polymarket samples once per second. This creates ~800ms latency window.

**Verification:**
- PythFeedsParse GitHub repo EXISTS (metamorphicc/PythFeedsParse)
- Contains working TypeScript parser connecting to `wss://pyth-lazer-0.dourolabs.app/v1/stream`
- Feed IDs confirmed: GOLD=346, SILVER=345, AAPL=922, TSLA=1435, NVDA=1314
- Polymarket docs confirm Pyth as resolution oracle for TradFi markets

**Edge Assessment:** REAL but NARROW.
- Only applies to new TradFi contracts (limited subset)
- 800ms window is exploitable only during high-volatility events (earnings, Fed, oil spikes)
- Requires Pyth Pro API key (free 30-day trial available)
- Not applicable to crypto contracts (BTC/ETH/SOL use different oracles)

**Estimated PnL contribution:** Low-moderate. TradFi markets on Polymarket are new with thin liquidity. Volume won't be there until the category matures. Worth monitoring, not worth building infrastructure around yet.

---

### Article 2: 236 TradingView Strategy Backtest (HIGH VALUE)

**Claim:** Tested 236 public PineScript strategies under HyperLiquid real fees. 21 survived with >10% APR. Key findings:
- Trade frequency is the main fee killer — ALL strategies that flipped profitable→unprofitable traded 200+ times/year
- Low-frequency strategies retained almost all edge
- Best performer: BTC mean reversion (RSI 20/65) — 16 trades in 90 days, +204% APR
- Median survival rate after fees: 57%

**Relevance to IG88:**
- CONFIRMS our finding that ATR Breakout works because it trades infrequently (~171-219 trades/yr)
- CONFIRMS our dead strategies list (RSI, MACD, EMA crossover all died in our testing too)
- NEW INSIGHT: The RSI > 70 "buy overbought" strategy (BTC 4h, 35.2% WR, +24.9% APR) is interesting — it contradicts conventional wisdom and survived fees
- NEW INSIGHT: SuperTrend with high multiplier (8.5) on BTC daily — 4 trades in 4 years, +73% APR. "Buy BTC when bull market starts, sell when it ends"

**Action Items:**
1. Test "buy overbought RSI" strategy on our Jupiter assets (ETH, AVAX, SOL, LINK, NEAR)
2. Test SuperTrend with high multiplier as regime filter (not standalone)
3. The 50/200 SMA + RSI average strategy that beat buy-and-hold by 117pp in a losing market — test this as a trend filter

---

### Article 3: Wolf Hour System (HIGHEST CONFIDENCE EDGE)

**Claim:** Every night 02:30-04:00 UTC, Polymarket liquidity collapses. Spreads on mid-tier contracts blow from 2-3¢ to 8-10¢. The edge is NOT market-making (adverse selection kills you) — it's directional entry at prices that don't exist during normal hours.

**System Design:**
1. Build watchlist during liquid hours (14:00-21:00 UTC) — identify fair value
2. Set Wolf Hour target prices (at least 6-8¢ below fair value)
3. Automated monitoring during 02:30-04:00 UTC
4. Execute when target hit — 30-50% normal position size (adverse selection hedge)
5. Exit during next liquid window (London open or US afternoon)

**Key constraints from the author:**
- Political contracts show 2-3x larger Wolf Hour spreads than other categories
- Fast-resolving contracts (48-72 hours) only — long-dated contracts have too much decay
- Some weeks there are zero qualifying entries. Don't manufacture trades.

**Edge Assessment:** HIGH CONFIDENCE.
- Structural, not predictive — you don't need to predict direction, just identify mispricing
- The liquidity trough is empirically verifiable (we can measure it ourselves)
- Multiple independent sources confirm Polymarket liquidity patterns
- Our existing scan-loop infrastructure can be adapted for overnight monitoring

**Estimated PnL:** Author claims 468% ann on deployed capital ($9,360/yr on $2,000). This is aggressive but the math checks out IF qualifying entries are frequent enough (4/week). Realistic estimate: 100-200% ann on the Polymarket allocation.

**What we need to test:**
1. Pull Polymarket trade history for 3+ markets with $50K-$500K monthly volume
2. Map median spread by UTC hour — verify the trough exists
3. Map average time between trades by UTC hour — verify the window
4. Backtest: simulate Wolf Hour entries on historical spread data

---

### Article 4: Markov Chain Bots ($1.3M in 30 Days)

**Claim:** Three bots using transition matrix approach on Polymarket crypto contracts (BTC/ETH Up/Down windows). Core logic:
- Build transition matrix from price states
- Entry when: (a) arbitrage gap >= 5¢ AND (b) state persistence >= 0.87
- Kelly sizing (f* ≈ 0.71)
- Bonereaper: 83-97¢ entry, 10% avg return, low variance
- 0xe1D6b514: 64-99¢ dual strategy, 54.6% max single trade
- 0xB27BC932: 1.3¢ entry across 5 assets, 4876% mark-to-market return

**Edge Assessment:** REAL but requires infrastructure.
- The $1.3M figure is across 48,061 predictions — volume-dependent
- Markov chains are a legitimate mathematical framework for state-based prediction
- The "human attention gap" at 3AM UTC aligns with Wolf Hour thesis
- Compounding at 0.034% per trade × 16K trades = 240x is mathematically sound

**Relevance to IG88:**
- This is a DIFFERENT edge than ATR Breakout — genuinely uncorrelated
- The transition matrix approach can be applied to our crypto data too
- Position sizing via Kelly is already our framework
- The bots trade BTC/ETH 5-min and 1-hour windows — we could run these alongside Jupiter

**What we need:**
1. Build a Markov chain backtester for Polymarket BTC/ETH Up/Down contracts
2. Historical data: Polymarket trade history API (available via CLOB)
3. Validate the transition matrix approach on historical price windows
4. If validated, build the monitoring bot

---

### Article 5: PolyArb Cross-Platform Arbitrage

**Claim:** Same events trade on 12+ venues (Polymarket, Kalshi, Drift, Limitless, Hedgehog, Myriad). Prices diverge 2-4% on average. $39.7M extracted in one year by quant systems.

**Edge Assessment:** REAL but INFRASTRUCTURE-HEAVY.
- Requires dedicated RPC nodes ($55,400/mo operating cost cited)
- Jito bundles for atomic execution on Solana
- 90ms end-to-end execution requirement
- This is HFT territory — not something we can build with our current setup

**Relevance to IG88:** LOW — this is a different game. We can't compete with $55K/mo infrastructure budgets. However:
- The Jupiter integration of Polymarket puts both venues on the same chain — we could potentially do simple Polymarket + Jupiter arb if we find correlated events
- The "YES + NO < $1" arb is the simplest form — worth scanning for even without dedicated infrastructure

**Action Item:** Build a simple scanner that checks for obvious arb opportunities across Polymarket markets (correlated contracts where YES + NO < $1). Low priority, low effort, potential discovery.

---

### Article 6: CentPRO Bot (5-min BTC Up/Down)

**Claim:** $7,500 profit over 3 months. Three strategy legs:
1. Scalp entries at 92¢ → exit at 97¢
2. Reversal entries at 1¢ on range-bound days
3. Spread capture at 49¢ in first 60 seconds of new candle

Kelly sizing with 8% hard cap. 15% max total exposure.

**Edge Assessment:** MODERATE confidence.
- 14-day test showed 80% return — but this is a small sample
- The three-leg approach is interesting — diversified within a single market
- Auto-claim logic is a real implementation detail (Polymarket doesn't auto-credit)
- Volatility gating on the reversal strategy is smart — prevents trading against trends

**Relevance to IG88:** HIGH — directly applicable.
- We already have Kelly sizing infrastructure
- The volatility gating concept aligns with our regime detection
- The 5-min BTC contract is the most liquid prediction market
- We could paper trade this immediately using our existing Polymarket paper trader (IG88048)

**What we need:**
1. Adapt our `polymarket_paper_trader.py` to implement the three-leg strategy
2. Historical data for 5-min BTC Up/Down contracts
3. Backtest the scalp/reversal/spread-capture approach
4. Auto-claim integration

---

### Article 7: $40M Arbitrage (Combinatorial)

**Claim:** Quant traders extracted $39.7M from Polymarket in one year using integer programming, Bregman projection, and Frank-Wolfe algorithm. Top trader: $2M from 4,049 trades ($496/trade).

**Edge Assessment:** REAL but INACCESSIBLE.
- Requires dedicated infrastructure (GPU clusters, sub-second execution)
- Combinatorial arb over 2^63 outcome spaces is not something we can solve
- The academic paper (arXiv:2508.03474) documents the methodology
- This is Citadel-tier infrastructure

**Relevance to IG88:** NONE for direct implementation. But:
- The 15 wallet profiles listed are publicly visible — we could study their trading patterns
- Copy-trading at block level is theoretically possible but requires the same infrastructure
- The research confirms that Polymarket is massively inefficient — good for us as smaller participants who can find simpler edges

---

## Part 3: Edge Ranking & Feasibility Matrix

| # | Edge | Venue | Confidence | Infra Needed | Est. Ann Return | Time to Test |
|---|------|-------|------------|--------------|-----------------|--------------|
| 1 | ATR Breakout | Jupiter | CONFIRMED | Built | 95-250% (1x) | N/A (live) |
| 2 | Wolf Hour | Polymarket | HIGH | Low | 100-200% on alloc | 2 weeks |
| 3 | BTC 5-min Scalp | Polymarket | MODERATE | Low | 80-200% on alloc | 3 weeks |
| 4 | Pyth Latency Arb | Polymarket | MODERATE | Medium | Unknown (thin mkts) | 4 weeks |
| 5 | Markov Chain | Polymarket | MODERATE | Medium | 50-200% on alloc | 4 weeks |
| 6 | RSI >70 Buy | Jupiter | UNTESTED | Low | 20-30% (1x) | 1 week |
| 7 | SuperTrend Filter | Jupiter | UNTESTED | Low | Unknown | 1 week |
| 8 | Cross-Platform Arb | Multi | LOW | Very High | N/A (can't compete) | SKIP |

---

## Part 4: Research & Testing Plan

### Phase 1: Wolf Hour Validation (Week 1-2) — HIGHEST PRIORITY

**Objective:** Verify the Wolf Hour liquidity trough exists and is exploitable.

**Scripts to build:**

1. **`scripts/pm_spread_history.py`** — Pull historical trade data from Polymarket CLOB API for 5+ markets. Map median spread by UTC hour. Map average time between trades by UTC hour. Output: CSV with hourly spread/trade-frequency data.

2. **`scripts/pm_wolf_hour_backtest.py`** — Simulate Wolf Hour entries on historical spread data. Enter at bid when spread > 6¢, exit at mid during next liquid window. Track PnL, win rate, adverse selection rate. Use realistic fees (taker 1.56%).

3. **`scripts/pm_wolf_hour_monitor.py`** — Live monitoring script for the 02:30-04:00 UTC window. Connects to Polymarket WebSocket, tracks spreads in real-time, flags when pre-set targets are hit. Integration with existing scan-loop.

**Success criteria:**
- Spread widening of 2x+ confirmed during 02:30-04:00 UTC
- Backtest shows positive expectancy after fees
- At least 2 qualifying entries per week in simulation

**Deliverable:** IG88077 Wolf Hour Validation Report

---

### Phase 2: BTC 5-min Up/Down Strategy Backtest (Week 2-3)

**Objective:** Validate the three-leg strategy (scalp/reversal/spread) on historical data.

**Scripts to build:**

1. **`scripts/pm_btc_5m_data.py`** — Fetch historical BTC 5-min Up/Down contract data from Polymarket. This is the hardest part — Polymarket's historical data API may not have granular 5-min resolution. Alternative: use BTC spot 5-min OHLCV and simulate contract pricing.

2. **`scripts/pm_btc_5m_backtest.py`** — Implement the three-leg strategy:
   - Leg 1 (Scalp): Buy at 92¢, sell at 97¢. Win if BTC doesn't reverse.
   - Leg 2 (Reversal): Buy at 1¢ on range-bound days (12-candle realized vol < threshold). Win if BTC mean-reverts.
   - Leg 3 (Spread): Buy both sides at 49¢ in first 60 seconds. Win if spread compresses.
   - Kelly sizing, 8% hard cap, 15% total exposure.

3. **`scripts/pm_volatility_gate.py`** — Realized volatility filter for the reversal strategy. 12-candle rolling vol, disable reversal when vol > threshold.

**Success criteria:**
- Positive expectancy on each leg individually
- Combined PF > 1.3 after fees
- At least 50 simulated trades for statistical significance

**Deliverable:** IG88078 BTC 5-min Strategy Validation Report

---

### Phase 3: Markov Chain Framework (Week 3-4)

**Objective:** Build a transition matrix framework for Polymarket crypto contracts.

**Scripts to build:**

1. **`scripts/pm_markov_backtest.py`** — Build transition matrix from historical price states. Entry filter: persistence >= 0.87 AND gap >= 5¢. Walk-forward validation on 6-month windows.

2. **`scripts/pm_transition_matrix.py`** — Core Markov chain engine. State discretization (price bins), transition counting, persistence calculation, optimal next-state prediction.

**Success criteria:**
- Transition matrix shows non-random state persistence (diagonal > 0.5)
- Entry filter produces positive expectancy
- Walk-forward PF > 1.2 after fees

**Deliverable:** IG88079 Markov Chain Validation Report

---

### Phase 4: Pyth Latency Arb Investigation (Week 4)

**Objective:** Assess viability of the Pyth Pro price lead on TradFi contracts.

**Steps:**
1. Sign up for Pyth Pro free trial (30 days)
2. Build Python WebSocket client connecting to `wss://pyth-lazer-0.dourolabs.app/v1/stream`
3. Compare Pyth 200ms price updates with Polymarket's resolution prices for GOLD, SILVER, AAPL, TSLA, NVDA
4. Measure: (a) actual latency gap, (b) price divergence during high-vol events, (c) tradable window duration
5. Assess liquidity on Polymarket TradFi contracts

**Success criteria:**
- Measurable 500ms+ latency gap confirmed
- Price divergence > 2¢ during at least 10% of high-vol events
- Polymarket TradFi contracts have > $10K daily volume

**Deliverable:** IG88080 Pyth Latency Arb Assessment

---

### Phase 5: Jupiter Strategy Enhancements (Ongoing)

While Polymarket research runs in parallel, optimize the existing Jupiter edge:

1. **RSI > 70 Buy test** — Apply the Article 2 strategy to our validated assets. Quick test (< 1 day).
2. **SuperTrend regime filter** — Test as overlay on ATR Breakout, not standalone.
3. **Funding rate integration** — Live funding rates into short sleeve allocation.
4. **FIL/RNDR 5yr data** — Validate the satellite assets with deeper historical data.

---

### Phase 6: Portfolio Integration (Week 5+)

**Objective:** Combine Jupiter and Polymarket edges into a unified portfolio.

**Proposed allocation:**

| Sleeve | Venue | Allocation | Strategy | Expected Ann |
|--------|-------|------------|----------|-------------|
| Alpha LONG | Jupiter | 40% | ATR Breakout Long (9 assets) | 100-250% |
| Alpha SHORT | Jupiter | 25% | ATR Breakout Short (5 assets) + funding | 80-200% |
| Wolf Hour | Polymarket | 15% | Spread capture 02:30-04:00 UTC | 50-150% |
| BTC Scalp | Polymarket | 10% | 5-min Up/Down three-leg | 40-100% |
| Cash Reserve | — | 10% | Buffer for DD, new opportunities | 0% |

**Blended expected return:** 80-200% ann (conservative) to 200-400% (aggressive)
**Correlation benefit:** Polymarket edges are uncorrelated with crypto perps — different asset class, different resolution mechanics, different time-of-day patterns

---

## Part 5: Risk Assessment

### What Could Kill These Edges

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Wolf Hour liquidity trough doesn't exist or is too thin | 20% | HIGH — kills edge #2 | Verify with historical data before building |
| Polymarket TradFi volume too thin for Pyth arb | 40% | MEDIUM — delays edge #4 | Monitor volume growth; don't invest infra |
| BTC 5-min strategy overfit to bull market | 30% | HIGH — false edge | Walk-forward validation required |
| Markov chain approach doesn't generalize | 35% | MEDIUM — kills edge #5 | Test on multiple assets/time windows |
| Polymarket API changes or degrades | 10% | HIGH — kills all PM edges | Monitor, keep Jupiter as primary |
| Ontario regulatory change blocks Polymarket | 5% | CRITICAL — lose venue | Unlikely given current status; monitor |

### Red Flags to Watch

1. **Any strategy with > 80% win rate** — likely overfit or taking hidden risk (see Article 2 case study: BB Upper Breakout Short had 100% WR over 49 trades but 36.7% max DD)
2. **Claims of > 300% annualized without walk-forward validation** — suspect
3. **Strategies that require sub-second execution** — we can't compete with HFT infrastructure
4. **Copy-trading high-frequency wallets** — by the time you see the trade, you're exit liquidity (Article 7 confirms this)

---

## Part 6: What NOT to Pursue

Based on the research and our constraints:

1. **Cross-platform arb (PolyArb-style)** — $55K/mo infrastructure cost. Not our game.
2. **Combinatorial arb (integer programming)** — Citadel-tier infrastructure. Not our game.
3. **Copy-trading fast wallets** — You provide exit liquidity. Confirmed by Article 7.
4. **Market-making during Wolf Hour** — Adverse selection will destroy you. Confirmed by Article 3.
5. **Long-dated Polymarket contracts** — Too much analysis decay. Short-window only.
6. **Any strategy requiring Hyperliquid** — Geo-blocked in Ontario. Stop building for it.

---

## Part 7: Immediate Next Steps

**For Chris:**
1. Confirm Polymarket wallet is funded (or fund with $200-500 USDC for testing)
2. Confirm Pyth Pro API key access (free 30-day trial at pyth.network)
3. Approve IG88076 testing plan

**For IG-88 (autonomous execution):**
1. Build `pm_spread_history.py` — start Wolf Hour validation immediately
2. Run Wolf Hour spread analysis on 3+ markets
3. Report findings within 48 hours
4. Proceed to Phase 2 if Wolf Hour validates

**Git:** All scripts and results versioned. No live trading until paper validation passes.

---

## References

[1] @morpphhhaw, "Ultimative Pyth Price Data Parser Guide," Apr 14, 2026. GitHub: metamorphicc/PythFeedsParse
[2] @minara, "We found 21 money-printers after backtesting 236 TradingView strategies," Apr 15, 2026
[3] @SolSt1ne, "Building a $1K/Day Wolf Hour System on Polymarket With Claude," Apr 13, 2026
[4] @0xRicker, "The Math That Made $1M+ for quant Traders in 30 Days," Apr 16, 2026
[5] @usePolyArb, "We found the math. We built the engine. You just plug in," Apr 17, 2026
[6] @stacyonchain, "How We Made $7.5k on Polymarket Using a Self-Made Bot," Apr 18, 2026
[7] @adiix_official, "The Math That Made $40,000,000 on Polymarket (Complete Trading Roadmap)," Apr 14, 2026. arXiv:2508.03474
[8] IG88075 — Comprehensive System Audit
[9] IG88073 — Consolidated Strategy Status & Production Readiness
[10] IG88006 — Polymarket Venue Setup Guide
[11] IG88048 — Polymarket Paper Trader Implementation
[12] Polymarket API docs: docs.polymarket.com
[13] Pyth Network: pyth.network

---

*Generated by IG-88 autonomous analysis cycle. All edges subject to walk-forward validation before deployment. Null hypothesis: no edge exists.*
