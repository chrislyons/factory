# IG88049: Comprehensive System Review and Strategy Analysis

**Date:** 2026-04-14
**Author:** IG-88 (new model, fresh review)
**Scope:** Full audit of IG-88 trading system — all venues, strategies, code, and docs
**Objective:** Identify real edges, kill false edges, maximize sustained +PnL%

---

## I. Executive Summary

After reviewing 48 IG88### documents, 50 git commits, 170+ scripts, the full codebase, and all paper trading data, here is the honest assessment:

**What we have:**
- One validated strategy (Mean Reversion on 4h) with statistically significant edge (PF 3.01, p<0.00000001, 2,561 trades)
- One promising but unproven strategy (5m BTC MR with vol filter, PF 3.23 but only 24 trades)
- One regime-dependent strategy (H3-B Volume Ignition, PF 2.0-2.3 but only works when ATR>3%)
- One speculative venue (Polymarket with simulated LLM — not a real edge yet)
- Paper trading showing +$176 (+1.76%) on 16 real trades, 75% WR

**What we don't have:**
- Live execution (everything is paper)
- Real LLM integration for Polymarket
- Kraken account or API keys
- Any strategy validated on the actual venue we'd trade (Kraken limit orders)

**Bottom line:** We have one solid edge (4h MR) that needs paper validation on its target venue before going live. Everything else is either too early, too small-sample, or not yet real.

---

## II. Strategy-by-Strategy Audit

### A. Mean Reversion (4h) — PRIMARY EDGE [CONFIDENCE: HIGH]

**What it is:** RSI(14) <35 + Bollinger Band breach + reversal candle + volume filter on 4h candles. Adaptive stops based on ATR regime.

**Backtest performance (validated):**
| Metric | Value | Confidence |
|--------|-------|------------|
| Profit Factor | 3.01 (avg 6 pairs) | 90% CI [3.15, 3.64] |
| Win Rate | 45.1% | Realistic (not inflated) |
| Trades | 2,561 | Large sample |
| p-value | <0.00000001 | Highly significant |
| Expectancy | 1.51% per trade | After friction |

**Strengths:**
1. Statistical rigor is excellent — this is the most validated strategy in the system
2. Works across 6 pairs (SOL, AVAX, ETH, NEAR, LINK, BTC)
3. Adaptive stops are a genuine insight — tight stops + wide targets fit MR's "fail fast" nature
4. Works in current regime (2025-2026 data confirms persistence)
5. Counter-trend positioning is structurally uncrowded (good thesis on why the edge exists)

**Weaknesses and concerns:**
1. **Paper trading uses JUPITER PERPS entry prices but claims KRAKEN venue.** The scanner fetches Binance data, signals on Binance candles, but the target venue is Kraken. Price divergence between exchanges is untested.
2. **T2 entry model may be optimistic.** The "honest validation" (IG88036) shows PF drops from 66 to ~10 with realistic execution. Even PF 5-10 is great, but the gap between backtest and reality needs monitoring.
3. **NEAR is consistently losing (0W/7L in paper).** This pair should stay disabled. The backtest shows NEAR PF 3.38, but live behavior diverges. Investigate why.
4. **Session filter adds complexity for marginal gain.** The "ASIA+NY" session optimization improved expectancy 26%, but this may be overfitting to a small sample. Needs OOS validation.
5. **No fees modeled in paper trades.** All paper trades show `fees_paid: 0.0`. With Kraken maker fees (0.16% each side = 0.32% round-trip), the +1.76% paper return would be reduced. On Jupiter (0.14% round-trip), impact is smaller.
6. **Duplicate entry bug in early paper trading.** The scanner was entering the same signal multiple times per cycle (entries 1-6, 7-12, 13-18 are duplicates). This inflated trade count and may distort P&L. The `mr_scan_final.py` fix addressed this, but the paper trading data includes these artifacts.

**Recommendation:** CONTINUE paper trading with `mr_scan_final.py` for 2-4 more weeks. Track actual entry prices vs. backtest assumptions. If PF >2.0 in paper after 50+ clean trades, prepare for live on Kraken with $500 first trade.

---

### B. 5-Minute BTC Mean Reversion — PROMISING [CONFIDENCE: LOW-MEDIUM]

**What it is:** BTC-specific mean reversion on 5-minute candles with realized volatility filter (<0.3 annualized).

**Performance:** PF 3.23, 24 trades, 70.8% WR

**Strengths:**
1. BTC-specific edge makes sense — BTC has the most stable microstructure
2. Volatility filter is a genuine insight (PF 1.73 -> 2.33 for momentum, confirmed for MR)
3. High-frequency opportunity = more compounding if validated

**Weaknesses:**
1. **24 trades is NOT statistically significant.** Need 50-100 minimum for 80% power at p<0.05. Current results could easily be variance.
2. **In-sample only.** No walk-forward, no OOS validation. This is a hypothesis, not a validated edge.
3. **Kraken friction on 5m is brutal.** 0.32% round-trip maker fees on a 0.15% target = fees are 2x the target profit. This strategy needs Jupiter perps (0.14% round-trip) or a venue with sub-0.1% fees.
4. **Slippage on 5m BTC can be significant.** Market orders during volatile periods could eat the entire edge.
5. **No execution infrastructure.** We'd need sub-minute latency to enter/exit 5m trades. Current scanner runs every 4h.

**Recommendation:** DO NOT trade this yet. Run walk-forward validation first (5-split on 5000+ candles). If PF >2.0 OOS, build dedicated 5m execution infrastructure. This is a Phase 2+ concern.

---

### C. H3-B Volume Ignition — REGIME-DEPENDENT [CONFIDENCE: MEDIUM]

**What it is:** Volume spike (>2x SMA20) + price above Ichimoku cloud + close > open. Only trade when ATR >3%.

**Performance:** PF 2.03-2.28 (Kraken), PF ~2.24 (Jupiter perps at 3x leverage)

**Strengths:**
1. Validated on SOL 4h with reasonable sample (216 trades)
2. ATR regime filter is well-researched — edge degrades linearly with declining volatility
3. Jupiter perps leverage amplifies returns in high-vol regime

**Weaknesses:**
1. **Current ATR is 2.29% — BELOW the 3% threshold.** Strategy is UNTRADEABLE right now.
2. **Degradation trend is clear:** PF 3.57 (2021) -> 0.38 (2026). This edge is dying.
3. **Single-asset concentration (SOL only).** If SOL-specific dynamics change, edge disappears.
4. **ATR trailing stop was initially claimed as optimal but later shown to CUT WINNERS SHORT** (IG88033). Time-based exits (T5/T10) actually perform better.

**Recommendation:** KEEP as secondary strategy. Monitor ATR — when it crosses 3%, activate. Do not allocate significant capital. This is a bonus, not the core edge.

---

### D. Polymarket Calibration Arbitrage — SPECULATIVE [CONFIDENCE: VERY LOW]

**What it is:** LLM generates price-blind probability estimates, trade when LLM disagrees with market price.

**Current state:** Paper trading with SIMULATED LLM (hash-based random probabilities, not real inference).

**Critical issues:**
1. **The LLM assessor is fake.** It uses `hash(question) % 100 / 100` to generate "probabilities." This has ZERO predictive power. Any paper trading P&L is random.
2. **No real edge has been demonstrated.** The "signals" are noise.
3. **Brier score tracking is implemented but meaningless** with simulated probabilities.
4. **Ontario regulatory status unclear.** Polymarket's availability in Ontario needs verification.

**Strengths (the concept, not the implementation):**
1. Prediction markets are genuinely inefficient — LLM assessment could be a real edge
2. Binary contracts have clear resolution — no ambiguity in P&L
3. Fee structure favors maker orders (0% + rebate) — edge only needs to exceed spread
4. Regime-independent — can trade regardless of crypto market conditions

**Recommendation:** HALT Polymarket paper trading until real LLM integration is built. The current simulation produces noise, not signal. Priority: connect mlx-vlm-ig88 for actual probability assessment, then paper trade for 50+ markets with real Brier scores before claiming any edge.

---

## III. Venue Analysis

### Kraken Spot
| Factor | Assessment |
|--------|------------|
| Availability | Ontario-compliant (registered with CSA) |
| Friction | 0.32% round-trip (maker), 0.52% (taker) |
| Liquidity | Good for majors, thin for mid-caps |
| Execution | Limit orders needed for maker fees |
| API | Not yet connected (no account/keys) |
| **Edge impact** | **MR strategy PF drops ~10-15% vs. Jupiter due to higher friction** |

**Key concern:** Kraken's 0.32% maker round-trip is 2.3x Jupiter's 0.14%. This means the MR strategy's 1.51% expectancy drops to ~1.31% on Kraken. Still positive, but thinner.

### Jupiter Perps
| Factor | Assessment |
|--------|------------|
| Availability | Solana wallet required, no Ontario restrictions |
| Friction | 0.14% round-trip (min), up to 0.22% with impact |
| Leverage | 2-3x default, amplifies edge |
| Execution | On-chain, latency-dependent |
| Risk | Borrow fees, liquidation risk at high leverage |
| **Edge impact** | **Best friction profile for MR. H3-B also viable at 3x.** |

**Key concern:** Jupiter perps have borrow fees that accrue hourly. For MR trades held 4-8 hours, this is manageable. For longer holds, it eats into P&L. The `borrow_fee_autoclose_pct: 50` config is smart.

### dYdX
**BLOCKED** — exited Canada in 2023. Not available.

### Polymarket
| Factor | Assessment |
|--------|------------|
| Availability | Uncertain in Ontario (needs verification) |
| Edge | Not yet real (simulated LLM) |
| Fee model | 0% maker + rebate is excellent IF edge exists |
| **Status** | **Research only until real LLM integration** |

### Solana DEX
**Observation phase only.** No strategy developed. Liquidity minimum ($200K) is sensible but untested.

---

## IV. Strengths of the System

1. **Statistical rigor.** The MR validation (IG88035-037) is genuinely excellent work. Monte Carlo bootstrap, walk-forward analysis, regime-specific testing — this is professional-grade quant research.

2. **Self-correction ability.** The system caught its own T1 look-ahead bias (IG88036), corrected the EMA convolution bug (memory entry), and pivoted from trend-following to MR when data showed trend was dead. This is the most important trait.

3. **Friction awareness.** Starting from "2% friction kills most edges" and designing strategies to survive it is exactly right. Most retail algo traders ignore friction.

4. **Regime detection.** The current regime state (`RANGING_HIGH_VOL`, 67.5% MR weight) is sensible and well-structured.

5. **Document discipline.** 48 IG88### documents with clear provenance. The PREFIX system works.

6. **Infrastructure is close.** Scan loop, paper trader, config system, regime detection — the plumbing is 80% done. The gap is live execution, not architecture.

---

## V. Weaknesses and Gaps

### Critical

1. **No live execution.** Everything is paper. No Kraken account, no API keys, no Jupiter wallet funding. We cannot make money until this changes.

2. **Paper trading data is contaminated.** Duplicate entries, stale prices from legacy scanner, and zero fee modeling make the +$176 P&L unreliable. The real paper P&L after dedup and fees is probably closer to +$50-80.

3. **Polymarket is fake.** Simulated LLM probabilities mean the entire Polymarket subsystem is generating noise. This should be flagged clearly in all reports.

4. **Scripts directory is a mess.** 170+ scripts with names like `final_v2.py`, `final_strong5.py`, `validate_12_final.py`. Many are one-off test scripts that should be archived. The active scripts (`mr_scan_final.py`, `scan-loop.py`, `paper_trade_runner.py`) are buried in noise.

### Important

5. **No walk-forward on the 5m BTC strategy.** 24 in-sample trades is not enough to claim an edge. This was correctly noted in IG88047 but the scratchpad calls it "Major Finding" which overstates confidence.

6. **Entry timing edge (IG88038) is interesting but untested live.** The T1 entry improvement (+0.676 PF) is statistically significant but the mechanism (bot clustering at candle open) is theoretical.

7. **No position sizing implementation.** Kelly criterion is discussed but not coded into the scanner. All paper trades use fixed $500.

8. **Regime detection depends on live data feeds.** The `MarketDataCollector` needs to be verified — if it's pulling stale data, regime assessment is wrong.

### Minor

9. **Document collisions.** IG88001, IG88014, IG88015 each have duplicate files. Should be cleaned up.

10. **INDEX.md is outdated.** Missing IG88031-048. Should be regenerated.

11. **Memory files are well-maintained** but the scratchpad mixes durable conclusions with session notes. The fact/ files are the right place for durable knowledge.

---

## VI. New Strategy Proposals

### 1. Cross-Exchange Arbitrage (MR Signal Timing)

**Hypothesis:** Binance (data source) and Kraken (execution venue) have price divergence on 4h candles. If the MR signal fires on Binance but Kraken's price is already reverting, we get worse entries.

**Test:** Compare Binance vs. Kraken 4h candle closes for the 6 MR pairs over 90 days. Measure:
- Signal coincidence rate (do both exchanges fire the same signal?)
- Entry price divergence (how far apart are the opens?)
- P&L impact (does Kraken execution degrade PF?)

**Expected outcome:** 0.1-0.3% additional slippage per trade. If >0.5%, consider using Kraken's own OHLCV data for signals.

**Effort:** 2-3 hours to fetch Kraken data and run comparison.

### 2. Funding Rate Mean Reversion (Jupiter Perps)

**Hypothesis:** Extreme funding rates on Jupiter perps predict short-term mean reversion. When longs pay high funding (>0.1%/hour), the cost of holding longs forces liquidation, creating short-term selling pressure that reverses.

**Test:** Backtest on Jupiter perps funding rate data (if available). Entry: funding rate >2 standard deviations from mean. Exit: funding rate normalizes or 8-bar time exit.

**Why it might work:** Funding rate extremes are mechanically driven (liquidations, not information). This creates predictable mean reversion.

**Effort:** 4-6 hours. Requires funding rate historical data.

### 3. Volatility Regime Transition Trades

**Hypothesis:** When ATR crosses from low-vol (<2%) to mid-vol (2-4%), the first few MR signals have higher PF because the market is waking up but agents haven't adjusted yet.

**Test:** Filter MR trades by ATR regime transitions. Compare PF for "first 5 trades after regime change" vs. "steady state" within each regime.

**Why it might work:** Regime transitions are noisy — agents using fixed thresholds miss the early moves.

**Effort:** 2-3 hours (add regime transition flag to backtest engine).

### 4. BTC Dominance Mean Reversion (Cross-Asset)

**Hypothesis:** When BTC dominance rises sharply (>3% in 7 days), alts are oversold and revert. This creates MR signals on alt pairs with higher PF than normal.

**Test:** Add BTC.D delta as a filter to the MR backtest. Compare PF with and without the BTC.D filter.

**Why it might work:** BTC dominance spikes create forced selling in alts (portfolio rebalancing), which is mechanical, not informational.

**Effort:** 3-4 hours (need BTC.D historical data).

### 5. Polymarket REAL LLM Edge (If Ontario-Compliant)

**Hypothesis:** LLM probability assessment on prediction markets can outperform market prices for questions requiring:
- Base rate knowledge (e.g., "Will X happen?" where historical base rates are knowable)
- Logical reasoning (e.g., compound events where market misprices conditional probability)
- Domain expertise (e.g., crypto-specific events where LLM training data has an edge)

**Implementation:**
1. Verify Polymarket availability in Ontario
2. Connect mlx-vlm-ig88 for real probability assessment
3. Paper trade 100 markets with Brier score tracking
4. Only go live if Brier score <0.20 (better than random <0.25)

**Effort:** 8-12 hours for real LLM integration + 2-4 weeks paper trading.

---

## VII. Ontario Venue Constraints

**What's available:**
- **Kraken:** YES — registered with CSA, fully compliant
- **Jupiter (Solana DeFi):** YES — decentralized, no geographic restrictions, but no regulatory protection
- **Polymarket:** UNCERTAIN — needs verification. Polymarket blocks US users; Canada/Ontario status unclear as of 2026
- **dYdX:** NO — exited Canada 2023
- **Binance:** NO — not available in Ontario
- **Coinbase:** YES — but higher fees than Kraken
- **Bybit:** NO — not compliant in Ontario

**Recommendation:** Kraken is the primary regulated venue. Jupiter perps are the primary DeFi venue. Verify Polymarket status before investing in LLM integration.

---

## VIII. Actionable Priorities (Next 30 Days)

### Priority 1: Clean Paper Trading [Week 1]
- [ ] Purge all contaminated paper trade data (duplicates, stale entries)
- [ ] Add fee modeling to paper trader (0.32% Kraken maker round-trip)
- [ ] Run clean paper trading for 2 weeks with `mr_scan_final.py`
- [ ] Track: actual PF, actual WR, entry price vs. Binance signal price

### Priority 2: Validate or Kill 5m BTC Strategy [Week 1-2]
- [ ] Run 5-split walk-forward on BTCUSDT 5m data (5000+ candles)
- [ ] If PF <2.0 OOS: archive the strategy, update memory
- [ ] If PF >2.0 OOS: build dedicated 5m execution infra

### Priority 3: Venue Preparation [Week 2-3]
- [ ] Create Kraken account (if not exists)
- [ ] Set up API keys via Infisical
- [ ] Test limit order execution with $10 live trade
- [ ] Verify Jupiter wallet funding and perps execution

### Priority 4: Script Cleanup [Week 2]
- [ ] Archive 150+ one-off test scripts to `scripts/archive/`
- [ ] Keep only: `scan-loop.py`, `mr_scan_final.py`, `paper_trade_runner.py`, `poly_paper_runner.py`
- [ ] Create `scripts/README.md` documenting active scripts

### Priority 5: Cross-Exchange Validation [Week 3-4]
- [ ] Fetch Kraken OHLCV for 6 MR pairs
- [ ] Run cross-exchange divergence analysis
- [ ] Adjust signal generation if Kraken divergence >0.3%

### Priority 6: Polymarket Decision [Week 4]
- [ ] Verify Ontario availability
- [ ] If available: scope real LLM integration
- [ ] If not available: archive Polymarket subsystem

---

## IX. Portfolio Sizing Recommendation

Based on validated edges only:

| Strategy | Venue | Allocation | Rationale |
|----------|-------|------------|-----------|
| MR 4h (6 pairs) | Kraken/Jupiter | 70% | Only validated edge |
| H3-B (SOL) | Jupiter | 10% | Active only when ATR>3% |
| Cash reserve | — | 20% | Dry powder for regime shifts |

**Position sizing per pair:**
- SOL, AVAX (strongest MR): 3% of portfolio each
- ETH, LINK (solid MR): 2% each
- BTC (weakest MR): 1.5%
- NEAR: DISABLED (0W/7L in paper)

**Max concurrent exposure:** 15% of portfolio
**Per-trade risk:** 1-1.5% of portfolio (adaptive stop)

---

## X. Kill Criteria (Updated)

The existing kill criteria are good. Add:

1. **MR strategy kill:** If paper PF drops below 1.5 over 50+ clean trades, halt and re-validate
2. **5m BTC kill:** If walk-forward OOS PF <1.5, archive permanently
3. **H3-B kill:** Already triggered (ATR <3% = inactive). Reactivation requires ATR >3% for 2+ weeks
4. **Polymarket kill:** Already triggered (no real LLM). Reactivation requires Brier score <0.20 over 50+ markets

---

## XI. Final Assessment

**We have one real edge: Mean Reversion on 4h candles.**

It's statistically solid, theoretically sound (counter-trend is uncrowded), and works in the current regime. The path to profit is:

1. Clean paper trading (2 weeks) -> validate PF >2.0 with fees
2. Kraken account setup -> small live test ($500)
3. Scale up after 50+ live trades confirm backtest

**Everything else is noise until MR is live and profitable.**

The 5m BTC strategy is the best candidate for a second edge but needs walk-forward validation. H3-B is a bonus when volatility returns. Polymarket is a research project, not a trading strategy.

**Estimated timeline to first live trade:** 3-4 weeks (assuming Kraken account setup is smooth).

**Estimated realistic monthly return (once live):** 5-15% on deployed capital, based on MR backtest projections with realistic execution assumptions.

---

*End of IG88049*
