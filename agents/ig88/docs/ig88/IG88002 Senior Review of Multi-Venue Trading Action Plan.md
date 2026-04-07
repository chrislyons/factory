---
prefix: IG88002
title: "Senior Review of Multi-Venue Trading Action Plan"
status: active
created: 2026-04-04
updated: 2026-04-04
author: Chris + Claude (Opus 4.6, senior review session)
reviews: IG88001
---

# IG88002 Senior Review of Multi-Venue Trading Action Plan

## Verdict

IG88001 is a well-researched plan with the right strategic thesis (operational edge, not predictive), correct venue prioritization (Polymarket first), and sound awareness of what IG-88 cannot do. However, it has significant gaps in risk parameterization, statistical rigor, cost modeling, and correlation assumptions that would erode the compounding objective if deployed as written. The plan reads like a strong first draft by someone who has done the reading but hasn't yet lost real money.

**Rating: B+. Strong thesis, weak operational parameters. Fixable.**

This review is organized as: Strengths (what to keep), Critical Gaps (what will lose money), Corrections (factual errors), Unexplored Areas (blind spots), and Revised Recommendations (what to change).

---

## 1. Strengths (Keep These)

### 1.1 Strategic Thesis Is Correct

The "operational, not predictive" framing from GoshawkTrades [1] is the single best insight in the plan. The vault reinforces this repeatedly: GoshawkTrades' own AI crypto trading bot results (TX260316) confirmed the thesis with live performance data. The plan correctly identifies that IG-88's edge is never sleeping, no emotions, perfect logging, and narrative interpretation.

### 1.2 Polymarket as Highest Priority Is Correct

The vault now contains 22+ TX docs on prediction market trading, making it the most thoroughly researched domain. Key validations:

- **6 backtested Polymarket strategies** across 3,000+ backtests on 800 markets over 14 months (TX260330, hanakoxbt, 518K views) [2]. These are concrete, validated approaches: Base Rate Audit, Conditional Probability Mispricing, Calibration Arbitrage, Time Decay Extraction (~0.23%/day), Liquidity Vacuum Fade, Cross-Market Delta Hedge. "None of them predict the future. Each one finds a specific mistake the market repeats over and over."
- **Working 3-agent architectures** documented in production: Claude (analyst) + Codex (self-patcher) + OpenClaw (orchestrator) running every 5 minutes with auto-improvement loops (TX260403, TX260317) [3][4].
- **Weather arbitrage** as a proven domain-specific edge: NOAA data vs. Polymarket pricing, documented returns of +$72.5K, +$39.3K (80% WR), +$42.4K (TX260221) [5].
- **Maker-zero-fee structure** preserves thin edges when posting limit orders.

### 1.3 The Compounding Data Asset (Graphiti) Is the Right Long-Term Play

The plan's Section 4 on Graphiti as a compounding knowledge graph is the strongest long-term differentiator. However, see Gap 3.5 on the critical distinction between context and memory (TX260316) [6].

### 1.4 Honest Failure Mode Analysis

Section 8 ("What Kills This Plan") is refreshingly honest. The overtrading risk is correctly identified as HIGH. The emotional override risk is real. The plan's awareness of its own weaknesses is a strength.

### 1.5 Eliminated Strategies Are Correctly Eliminated

The "What IG-88 Cannot Do" table in Section 1 is accurate and demonstrates genuine understanding of the microstructure reality. Sniping, market making, stat arb, copy-trading whales, grid trading on memecoins, and news-based fast trading are all correctly rejected.

---

## 2. Critical Gaps (These Will Lose Money)

### 2.1 Half-Kelly Is Too Aggressive for Unvalidated Strategies

**The plan defaults to half-Kelly. This is wrong for the first 100+ trades.**

The Kelly criterion is extremely sensitive to estimation error. At 2x the true Kelly fraction, expected growth rate drops to zero. At >2x, growth becomes negative [7][8]. If your edge estimate is even modestly wrong, half-Kelly puts you on the dangerous side of the curve.

The vault's own sources support this:
- Empirical Kelly formula: `f_empirical = f_kelly * (1 - CV_edge)` — the CV_edge term exists precisely because edge estimates are unreliable [9].
- The mikita_crypto Kelly analysis (TX260219) tested Full/Half/Quarter Kelly with Monte Carlo caps and found quarter-Kelly with MC cap the most robust [10].
- The Hidden Math Behind Decision-Making (TX260307) explicitly recommends "quarter-Kelly to half-Kelly in practice" [11].

**Recommendation:** Start at quarter-Kelly or one-eighth Kelly. Graduate to half-Kelly only after 100+ trades with confirmed positive expectancy. Never exceed half-Kelly. Add a Monte Carlo cap of 3x max leverage.

### 2.2 The -8% Stop Loss Will Trigger on Noise

Memecoins with 50-100% daily volatility will hit an -8% stop on virtually every position before any directional signal materializes. This is the plan's most expensive operational error.

**Research findings:**
- Industry guidance for low-cap meme tokens is 10-15% stop minimum with position size reduced accordingly.
- ATR-based stops (1.5-2x Average True Range) are the recommended approach. For a memecoin with a 4-hour ATR of 10%, the stop should be at 15-20%.
- Time-based and volume-based stops outperform price-based stops for momentum plays.

**Recommendation:** Replace the flat -8% stop with a multi-signal exit framework:
1. **ATR-calibrated stop:** 1.5x the 4-hour ATR at entry (typically 15-25% for memecoins)
2. **Time stop:** Exit if no positive movement within 2-4 hours
3. **Volume stop:** Exit if trading volume drops below 50% of entry-period volume
4. **Staged exits:** Sell 50% at 2x to recover capital, trail the remainder
5. **Position sizing as primary risk control:** If the stop must be 25% away, reduce position size so dollar loss at stop = 1% of portfolio

### 2.3 Round-Trip Costs on Solana DEX Are Catastrophic

The plan does not model transaction costs for memecoin trades. This is a fatal omission for a compounding strategy.

**Estimated round-trip cost on a <$100K liquidity token:**

| Component | Cost (round trip) |
|---|---|
| Solana base gas | Negligible (<$0.01) |
| Priority + Jito bribe fees | $3-6 (0.04-0.07 SOL) |
| Jupiter/DEX platform fee | 0.6-2%+ |
| Slippage on <$100K pool | 10-20%+ |
| MEV/sandwich extraction | 2.5-5% |
| **Total** | **15-25%+** |

On a $500 position in a token with $80K liquidity, you are paying $75-$125+ in friction before the token moves at all. This means the strategy needs 15-25%+ return just to break even on each trade. Combined with a 25-40% win rate, the math does not compound — it drains.

**Recommendation:** Restrict Solana DEX trading to tokens with >$200K liquidity. Model round-trip costs explicitly in the expectancy calculation. The plan's expectancy formula (`E = (Win% x AvgWin) - (Loss% x AvgLoss)`) must include costs: `E = (Win% x (AvgWin - costs)) - (Loss% x (AvgLoss + costs))`.

### 2.4 50 Paper Trades Is Not Statistically Meaningful

The plan requires 50 paper trades per venue before live. At max 4/day on Solana, that is 13 days capturing a single market regime. This is a sanity check, not validation.

**Statistical reality:**
- 200-500 trades is the minimum for meaningful strategy validation (Lopez de Prado, *Advances in Financial Machine Learning*).
- For a 25-40% win rate strategy, you need 200-300+ trades to distinguish skill from luck with 95% confidence.
- 50 trades at a 30% win rate has a confidence interval of roughly +/- 13 percentage points — you cannot distinguish 17% from 43%.
- The noisyb0y1 roadmap (TX260320) [12] dedicates an entire month to "Prove the strategy isn't luck" — validation is a phase, not a checkbox.

**Recommendation:** Use a tiered approach:
- **50 trades:** Sanity check — confirms execution pipeline works, catches gross implementation bugs
- **100 trades:** Formal evaluation with confidence intervals reported
- **200 trades:** Statistical kill/continue decision. Negative expectancy at 200 trades with 95% confidence = kill the strategy
- Between 100-200 trades, reduce sizing to one-eighth Kelly while gathering more data

### 2.5 The "Structurally Uncorrelated" Assumption Is False

The plan claims "The three venues are structurally uncorrelated." This is incorrect during stress events. All three venues share at least three hidden correlation channels:

**Channel 1: USDC/Stablecoin Exposure.** All three venues settle in USDC or crypto. The March 2023 SVB event demonstrated this: USDC depegged to $0.87, hourly exchange outflows hit $1.2B, USDC supply dropped $3.93B in three days. All venues would be hit simultaneously.

**Channel 2: Crypto Risk-Off Correlation.** During broad crypto selloffs, SOL amplifies drawdowns (~2x BTC beta). Bybit correlates with the same dynamics. Polymarket crypto-category contracts move with underlying assets.

**Channel 3: Infrastructure Contagion.** During the FTX collapse, Bybit and OKX suspended Solana-based stablecoins. DEX volumes cratered. When one venue's liquidity dries up, participants withdraw from adjacent venues.

**Recommendation:** Model a stress scenario where all three venues experience simultaneous 20-30% drawdowns. If the portfolio does not survive this scenario at current position sizing, the sizing is wrong. During normal markets the strategies may appear uncorrelated; during a USDC depeg or crypto crash, correlations spike toward 1.0.

### 2.6 Parrondo's Paradox Is Technically Inapplicable

The plan invokes Parrondo's Paradox for portfolio construction. This is the wrong framework.

Parrondo's Paradox requires state-dependent payoffs — at least one game's win probability must depend on the player's current capital (modulo some number). Financial markets do not have this structure [13][14]. The plan's three venue strategies are standard positive/negative expectancy bets.

**What the plan likely means — and what IS valid — is Shannon's Demon / the rebalancing premium:** combining volatile, uncorrelated strategies and periodically rebalancing can produce a geometric return exceeding any individual strategy's geometric return. The formula is: `Geometric return ~ Arithmetic return - 1/2 * variance`. When strategies are uncorrelated, portfolio variance drops more than arithmetic mean, which can flip geometric mean positive.

**Critical caveat from the vault's own source (TX260218, Build Alpha):** "The Parrondo's Paradox illustration uses fictitious strategies. Real-world results depend heavily on correlation stability over time, transaction costs, and regime changes. The rebalancing premium exists under specific mathematical conditions that may not hold persistently in live markets." [15]

**Additional caveat:** Shannon's Demon assumes mean reversion. In trending crypto markets (which is the primary regime for memecoins), rebalancing creates a penalty — you systematically sell winners and buy losers.

### 2.7 Variance Drag Is Not Modeled

The plan discusses compounding but never models variance drag, which is the primary enemy of geometric growth.

**The formula:** `Geometric return ~ Arithmetic return - sigma^2/2`

At 80% annualized volatility (normal for memecoin strategies), variance drag is ~32% per year. This means an arithmetic average return of 30% becomes a geometric return of approximately -2% — you lose money while your average trade is profitable [16].

**This is the single most important concept for a compounding strategy and it is absent from the plan.**

**Recommendation:** Calculate variance drag for each venue strategy. If `arithmetic_return - sigma^2/2 < 0`, the strategy destroys wealth through compounding regardless of average per-trade profitability. Reducing variance (via position sizing, diversification, or trade selection) is more important than increasing average returns.

---

## 3. Corrections (Factual Errors)

### 3.1 Calibration Surface Claim

The plan states: "markets priced at 5-15% resolve YES only ~40% of the time."

**Correction:** The actual data is more extreme and more favorable for the seller. Kalshi data (Whelan et al., 72.1M trades, $18.26B volume) shows contracts at 5 cents had a 4.18% actual win rate — not 40%. Contracts below 10 cents lost buyers over 60% of their money. The edge is in selling overpriced longshots, not buying them.

The vault's own TX260306 [9] corrects this: "calibration surface arbitrage: markets priced 5-15% resolve YES only 4%."

### 3.2 Pump.fun Graduation Rate

The plan cites 0.63% from the Tarantelli arXiv paper. This is outdated. The rate fluctuates significantly: hit 2.01% in the week of March 9-15, 2026 (highest since July 2025). PumpSwap now routes graduation instead of Raydium.

### 3.3 Bybit Regulatory Status

The plan lists Bybit KYC as "done" but does not note that Bybit was permanently barred from US users by CFTC consent order on March 31, 2026, following a ~$297M DOJ settlement. If Chris is a US person, Bybit access may be legally problematic.

### 3.4 20% Max Position / 10% Drawdown Halt

These guardrails are 2-4x looser than professional standards:

| Parameter | This Plan | Professional Standard |
|---|---|---|
| Max position | 20% | 5-7% (quant funds) |
| Daily drawdown halt | 10% | 2-4% (prop firms) |

A 10% daily drawdown requires 11.1% gain to recover. At professional 3% limits, recovery requires only 3.1%. The asymmetry of drawdown recovery punishes loose limits disproportionately.

**Recommendation:** Max position 10% (target 5%). Daily drawdown halt 5% (with 3% "review everything" trigger).

### 3.5 Win Rate Is a Trap

The plan's Section 3 discusses win rate extensively. The vault contains a direct counter (TX260320, Kropanchik) [17]: win rate is misleading in prediction markets due to three mechanisms:
1. **Probability pricing arithmetic:** Buying YES at $0.77 means risking $0.77 to win $0.23
2. **Ghost positions:** Inflated win count from positions that were never at risk
3. **Small sample sizes:** 16.8% of wallets are net profitable; 83.2% lose money

The real metrics are realized PnL, ROI%, and market-adjusted PnL.

---

## 4. Unexplored Areas (Blind Spots)

### 4.1 The Kill Switch as Alpha

TX260320 (hanakoxbt) [18] introduces "The Kill Switch" — automatic shutdown conditions on drawdown, volatility regime, or correlation breach thresholds. The key insight: **risk management is alpha, not just defense.** The plan treats guardrails as constraints. It should treat them as the strategy's most important edge.

The plan's regime detection (Section 2.2, Phase 1) is the right instinct. But it needs to be promoted from "build first, protects capital" to "this IS the primary strategy — everything else is secondary."

### 4.2 Forecast Layer / Forward-Looking Mental Models

TX260316 (Old_Samster / Sami Kassab) [19] identifies the fundamental LLM trading limitation: "AI trading agents are built on historical patterns and cannot see beyond them. What they need is not more data about the past, but a mental model of the future."

The plan's Graphiti data asset is backward-looking by design. It stores "what happened." It does not generate forward-looking models of "what will happen given regime change X." The plan should include a forecast layer between raw data and trading decisions — a dedicated prediction/forecasting module that models scenarios rather than pattern-matching history.

### 4.3 Context Is Not Memory

TX260316 (molt_cornelius) [6] draws a critical distinction: "expanding context windows creates the illusion of remembering, but true memory requires persistence, retrieval, and selective recall across sessions."

The plan's Graphiti strategy is sound in concept but must distinguish between:
- **Context:** What IG-88 knows during this session (ephemeral)
- **Memory:** What IG-88 learns across sessions (durable, retrievable, selective)

The Graphiti schema should be designed for cross-session learning, not just in-session reference.

### 4.4 Self-Improving Agent Architectures

The vault now documents multiple production self-improvement patterns:
- **Hermes Agent v0.7** (TX260403): Memory plugin system with 6 third-party providers, CamoFox anti-detection, credential pools, and the remarkable claim that "hermes-agent is the primary developer of itself" [20].
- **Subconscious self-improvement** (TX260403, gkisokay): Background agent gathers evidence, generates candidate improvements, debates them against a smarter agent, synthesizes one recommendation, writes to durable state [21].
- **Arby** (TX260319): "Dynamic Domains Need Dynamic Harnesses" — the harness itself evolves to match changing market conditions [22].

However, there is a critical warning from the Financial Agents topic synthesis: "agents that research, implement, and test their own strategies are susceptible to the same over-optimization failure mode" as static backtests. Self-improvement is not automatically an edge — it can be an overfitting accelerator.

### 4.5 LLM Accuracy Ceiling → Cloud Inference Decision

TX260403 (zostaff) [23] documents the LLM trading accuracy progression citing 84+ peer-reviewed studies:
- Raw inference: 55-62%
- Fine-tuned: 65-72%
- Fine-tuned + RAG: 68-75%

IG-88 originally planned to run on Nanbeige 3B at 66% eval accuracy (WHB023) — near the bottom of this range. **This plan has been superseded.** IG-88 runs on cloud inference (Claude Sonnet 4.6 default, Opus 4.6 for escalation). See IG88003 §Inference Architecture Decision and IG88004 for the full cloud model evaluation framework.

Key drivers: model quality gap at the tasks that matter most, stakes asymmetry (inference cost vs. capital at risk), local model reliability issues (mlx-lm socket crashes in WHB023), and the absence of any privacy requirement (all trades are on-chain or KYC'd anyway).

**Price-blinding requirement stands regardless of model:** IG-88's probability assessment pipeline must be designed so the LLM does NOT see current market prices when forming its estimate. This applies to cloud models too — GPT-4.5 shows 0.994 market-price correlation when prices appear in context, demonstrating that even frontier models anchor badly when given the opportunity. Architecture must enforce the blind, not trust the model to ignore the price.

### 4.6 The 3-Agent Architecture Pattern

Multiple vault sources converge on a 3-agent pattern for prediction market trading:
- **Analyst** (Claude/LLM): Probability assessment, market scanning
- **Builder/Patcher** (Codex): Self-modifying execution code
- **Orchestrator** (OpenClaw/framework): Persistent memory, scheduling, Telegram/Matrix integration

This pattern is documented in TX260403 (AleiahLock, 218K views), TX260317 (zostaff, 2.9M views), and TX260317 (raychix, 56.4K views). The plan's current architecture (single IG-88 agent) should consider whether decomposing into specialized sub-agents would improve performance.

### 4.7 Bybit MCP Server: Already Solved

The plan allocates 2-3 weeks for building a Bybit MCP server. An existing CCXT MCP server (doggybee/mcp-server-ccxt) already wraps 20+ exchanges including Bybit via CCXT, exposing 24 tools over MCP. Fork, configure credentials, deploy. Days, not weeks.

### 4.8 TradingView Technical Indicators: No CLI, But There Is a Door

**Verified:** TradingView has no public API. This is not a gap to fill — it is a documented architectural fact. However, the vault contains a solution (TX260331, Tradesdontlie) [24].

The TradingView Desktop app is built on Electron, which runs on Chromium, which has a debugging interface called Chrome DevTools Protocol (CDP) built in by default. One launch flag (`--remote-debugging-port=9222`) opens the door. A 78-tool MCP server (`tradingview-mcp`) exploits this to give Claude structured read access to:

- Live chart data and OHLCV
- Indicator values (including protected/closed-source Pine Script indicators)
- Drawing objects (lines, labels, tables, boxes)
- Symbol and timeframe information

**Architecture:** Fully local. MCP server + CDP bridge. No data leaves the machine. Port 9222 only opens deliberately.

**Key fragility:** accesses undocumented internal TradingView APIs. Any TradingView update can break compatibility silently. This is a dependency that requires monitoring.

**Implication for IG-88:** Chris's historical edge from TradingView's technical indicators (RSI, MACD, volume profiles, support/resistance levels, etc.) is not lost — it is accessible to IG-88 via this bridge. IG-88 can read the same indicators Chris used to read manually, process them without emotion, and act on them with discipline. The human intuition that read the chart is replaced by systematic rule execution against the same data.

**Week 2-3 action:** Deploy `tradingview-mcp` alongside the Bybit CCXT server. Configure indicator set to match Chris's historical setup. This is infrastructure work, not strategy work — do not let it delay Polymarket paper trading.

**Critical caveat:** TradingView indicators are backward-looking signals. They do not substitute for the forecast layer (Section 4.2). They inform entries and exits within a regime; they do not identify regime changes. Use in combination with regime detection, not as a replacement.

### 4.9 CEX Venue: Kraken Spot Only (Futures Eliminated)

**Regulatory outcome:** Both KuCoin and Bybit are inaccessible from Ontario, Canada. A full audit (April 2026) confirmed that no compliant path to crypto perpetuals exists for Ontario retail users — every major CEX either explicitly bans Ontario or is registered under conditions that prohibit retail derivatives. Decentralized alternatives (Hyperliquid, dYdX) also explicitly restrict Ontario. GMX does not geo-block but has inferior bot API infrastructure and uncertain OSC user-side risk.

**Decision: Futures eliminated. CEX slot = Kraken spot trading.** This is not a consolation — it removes the leverage trap that historically destroyed Chris's gains.

**The greed pattern — preserved as institutional memory:**

Chris identified 3-5x leverage as his effective operating range, with greed (not leverage) as the documented failure: holding winners past target, sizing up after wins, re-entry fever, averaging down, continuing after daily target. These failure modes are relevant even in spot trading — they manifest as holding through retracements, doubling down on losers, over-trading during winning streaks.

**IG-88's spot discipline guardrails (hardcoded, not policy):**

| Failure Mode | IG-88 Guardrail |
|---|---|
| Holding past target | Profit targets trigger automatic exit. No override. |
| Sizing up after wins | Position size = Kelly formula output only. No "I'm hot" scaling. |
| Re-entry fever | 2-hour mandatory cooldown after any close on the same instrument |
| Averaging down | Absolutely prohibited. A position in drawdown exits or holds — never adds. |
| "One more trade" | If daily loss halt triggers (>3% of Kraken wallet), no new entries until next UTC day |
| Fee drag | If taker fees exceed 15% of gross P&L on a rolling 20-trade basis, enforce limit-order-only mode |

**Fee structure:** Kraken maker 0.16% / taker 0.26% at base tier. Use limit orders wherever fills permit.

**On surpassing human trading intelligence:** IG-88 is not constrained by Chris's novice ceiling. The plan should be designed for IG-88 to learn from the vault's institutional-grade research and to eventually operate at a level Chris could not. Chris's contribution is capital, domain context, and the documented failure pattern data — not a ceiling.

---

## 5. Revised Recommendations

### 5.1 Priority Reorder (For Sustained Compounding)

Given abysmally small capital, paper-trade-first mandate, and compounding as the goal:

1. **Polymarket (HIGHEST — unchanged).** Best match for LLM capabilities. Lowest friction costs. Richest vault research base. Zero maker fees. Start here.

2. **Kraken (MOVE UP to second — spot only).** Both KuCoin and Bybit are inaccessible from Ontario, Canada (OSC enforcement). A full Ontario CEX audit confirmed no compliant path to crypto perpetuals for Ontario retail users. Kraken is OSC-registered and legally accessible for spot trading. Strategy: event-driven spot positioning on BTC/ETH/SOL, regime-gated, no leverage. Fork CCXT MCP server in days. Futures are eliminated — not deferred.

3. **Solana DEX (DEMOTE to third).** Round-trip costs of 15-25% destroy compounding at small scale. Only viable for tokens with >$200K liquidity. MEV extraction ($370-500M over 16 months on Solana) is a structural headwind. Revisit after Polymarket and Kraken are validated.

4. **Base L2 (DEFER — unchanged).**

### 5.2 Risk Parameters (Revised for Compounding)

| Parameter | IG88001 Value | Revised Value | Rationale |
|---|---|---|---|
| Default Kelly fraction | Half-Kelly | Quarter-Kelly (first 200 trades), then half-Kelly | Estimation error protection |
| Max position size | 20% of venue wallet | 10% max, 5% target | Professional standard |
| Daily drawdown halt | 10% | 5% halt, 3% review trigger | Drawdown recovery asymmetry |
| Paper trade threshold | 50 trades | 50 sanity / 100 eval / 200 kill decision | Statistical adequacy |
| Stop loss (memecoin) | -8% flat | ATR-calibrated (1.5x 4h ATR) + time + volume stops | Noise filtering |
| Auto-execute threshold | $500 | $50-100 initially, scale with validated edge | Capital preservation at small scale |

### 5.3 New Requirements

1. **Model variance drag for each venue strategy.** If `arithmetic_return - sigma^2/2 < 0`, the strategy is a wealth destroyer regardless of average returns.

2. **Stress test the portfolio at simultaneous 30% drawdown across all venues.** If it doesn't survive, fix the sizing.

3. **Blind the LLM to current market prices** during probability assessment on Polymarket. Compare independent estimate to market to find divergence. No divergence = no trade.

4. **Implement The Kill Switch** as a first-class feature, not an afterthought. Regime gating should be the primary strategy; everything else runs only when the kill switch allows.

5. **Cost-model every Solana DEX trade explicitly** including slippage, MEV exposure, priority fees, and platform fees before executing. If round-trip cost > 5% of position, do not trade.

---

## 6. What the Plan Gets Right That Most Plans Don't

To be clear: this is a good plan. Most AI trading plans are fantasy documents full of backtested curves and no awareness of execution reality. IG88001:

- Correctly identifies what an LLM agent cannot do (Section 1)
- Prioritizes the right venue (Polymarket)
- Builds a data asset that compounds (Graphiti)
- Has hard guardrails (even if they need tightening)
- Plans for paper trading before live
- Acknowledges failure modes honestly
- Cites real research, not blog hype

The corrections in this review are about surviving long enough to let the compounding thesis work. The thesis is sound. The parameters need hardening.

---

## References

[1] GoshawkTrades, "15 Actions for AI in Trading -- Operational Not Signals," research-vault TX260217_0000-DFF4.

[2] hanakoxbt, "How Claude Extracts Consistent Edge From Prediction Markets: Six Backtested Strategies," research-vault TX260330_1151-CF65. 518K views.

[3] AleiahLock, "How I Built a Bot That Trades Polymarket While I Sleep," research-vault TX260403_0940-9790. 218K views.

[4] zostaff, "Claude OpenClaw Codex Prediction Market Bot Architecture," research-vault TX260317_1137-7E21. 2.9M views.

[5] LunarResearcher, "OpenClaw Polymarket Weather Trading Bot: NOAA Arbitrage, $100 to $8000," research-vault TX260221_0000-54C5.

[6] molt_cornelius, "Context Is Not Memory -- AI Field Report 4," research-vault TX260316_1358-4878.

[7] CFA Institute, "The Kelly Criterion: You Don't Know the Half of It," 2018.

[8] L. C. MacLean, E. O. Thorp, and W. T. Ziemba, "Good and Bad Properties of the Kelly Criterion," UC Berkeley, 2010.

[9] RohOnChain, "Institutional Prediction Market Hedge Fund Operations Complete Breakdown," research-vault TX260306_1911-9AEE.

[10] mikita_crypto, "Kelly Criterion and Monte Carlo for Prediction Market Strategy," research-vault TX260219_0931-84D3.

[11] "Hidden Math Behind Decision-Making: Six Mental Models for Rational Choices," research-vault TX260307_1259-0F4A. 4.8M views.

[12] noisyb0y1, "How to Go from Zero to Profitable on Prediction Markets in 6 Months," research-vault TX260320_0612-5798. 100.6K views.

[13] R. Iyengar and R. Kohli, "Why Parrondo's Paradox is Irrelevant for Utility Theory, Stock Buying, and the Emergence of Life," *Complexity*, vol. 9, no. 1, 2003.

[14] SG Analytics, "Why Parrondo's Paradox Can't Be Exploited in Asset Management," 2023.

[15] Build Alpha, "Portfolio of Trading Strategies," research-vault TX260218_1141-347C.

[16] "50 Quantitative Finance Concepts in Python: From Returns to Drawdowns," research-vault TX260307_1652-3E12.

[17] Kropanchik, "Win Rate Is a Trap: Polymarket Copy Trading Wallets," research-vault TX260320_0000-02B6.

[18] hanakoxbt, "How Math Bots Extract Money Without Predicting," research-vault TX260320_1127-128B.

[19] Old_Samster (Sami Kassab), "Synth: The Forecast Layer for Trading Agents," research-vault TX260316_1623-DD7D.

[20] Teknium / Nous Research, "Hermes Agent v0.7.0 -- Memory Plugin System, Credential Pools, CamoFox," research-vault TX260403_1521-CF09.

[21] gkisokay, "I Gave My Hermes + OpenClaw Agents a Subconscious, and Now They Self-Improve 24/7," research-vault TX260403_0940-76D4. 142K views.

[22] RecallLabs_, "Arby: Self-Improving Agent Harness for AI Financial Research," research-vault TX260319_1456-92B9.

[23] zostaff, "Financial Freedom in 6 Steps: How to Build an LLM for Trading," research-vault TX260403_0000-9407.

[24] Tradesdontlie, "TradingView MCP — 78 Tools Connecting Claude to Live Charting via Chrome DevTools Protocol," research-vault TX260331_2040-467F.
