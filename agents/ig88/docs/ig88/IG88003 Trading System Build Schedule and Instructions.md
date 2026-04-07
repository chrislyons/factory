---
prefix: IG88003
title: "Trading System Build Schedule and Instructions"
status: active
created: 2026-04-04
updated: 2026-04-05
author: Chris + Claude (Opus 4.6)
supersedes: null
depends_on: IG88001, IG88002, IG88004
---

# IG88003 Trading System Build Schedule and Instructions

## Purpose

This document is the operational schedule for building and validating IG-88's multi-venue trading system. It translates the strategic plan (IG88001) and senior review (IG88002) into concrete, sequenced, owner-assigned instructions.

**Reading guide:**
- **Chris** — actions only you can take (wallets, keys, legal, capital)
- **Boot** — build work (MCP servers, infrastructure)
- **IG-88** — strategy design, paper trading, analysis
- **[DECISION]** — open questions that must be resolved before dependent work starts

**Critical path to first Polymarket paper trade:**
`Chris: EVM wallet + USDC → Boot: Polymarket MCP → IG-88: strategy selection + regime criteria → first paper trade`

Everything else is parallel.

---

## Inference Architecture Decision

**IG-88 runs on cloud inference. Local models are not used for trading decisions.**

This is a deliberate departure from the original IG88001 plan which assumed local Nanbeige 3B. The decision was made during the IG88002 review session and is documented here as a hard architectural constraint.

### Rationale

IG-88 is a technical execution engine running tightly scoped, high-stakes financial tasks. It is not a personalised assistant and has no identity requirements that would benefit from a custom local model. The right model is whichever one reasons most accurately about probabilities and structured financial analysis — determined by published research benchmarks, not internal evals on general tasks.

- **Model quality:** Nanbeige 3B at 66% eval accuracy is near the bottom of the LLM accuracy progression for trading tasks (raw inference: 55-62%, fine-tuned+RAG: 68-75% per TX260403). The accuracy gap between a 3B local model and a frontier cloud model is largest precisely on the multi-step reasoning tasks IG-88 needs most.
- **Stakes asymmetry:** Cloud inference costs ~$20-50/month. A single avoided bad Polymarket trade or missed regime signal pays for months of API usage. The cost argument for local inference does not hold when real capital is at risk.
- **Reliability:** Local mlx-lm inference has documented socket crashes on tool-calling tasks (WHB023). Trading agents cannot have inference layer failures.
- **Anonymity is moot:** Every Polymarket trade is on-chain (Polygon). Every Bybit trade is KYC'd. Every Solana swap is on-chain. There is nothing to protect by running locally.

### Task → Model Routing

| Task | Model | Why |
|---|---|---|
| Polymarket probability assessment | Cloud frontier (see IG88004) | Highest-stakes reasoning task; accuracy directly determines edge |
| Bybit regime detection scoring | Cloud frontier (see IG88004) | Structured scoring; reliability critical for halt decisions |
| Solana narrative classification | Cloud frontier (see IG88004) | Consistency matters more than latency here |
| Kill switch / circuit breaker logic | **Hardcoded rules — NO LLM** | Deterministic; never trust inference for halt decisions |
| Trade sizing (Kelly calculation) | **Hardcoded formula — NO LLM** | Math, not inference |
| Graphiti writes / trade logging | **Structured code — NO LLM** | Schema-driven, no reasoning required |

**The kill switch and position sizing must never route through any model.** These are deterministic rules. If the inference layer is down, unavailable, or returning garbage, the system defaults to HALT — not to a cached LLM decision.

### Cloud Model Selection

See **IG88004** for the full cloud model evaluation framework. Model selection is based on published research benchmarks across financial reasoning, probability calibration, instruction following, and structured output tasks. The selected model is updated whenever the benchmark landscape changes materially.

**Current recommendation pending IG88004 evaluation:** Claude Sonnet 4.6 as working default. Re-evaluated quarterly or on major model release.

### Cost Model

At 5-minute Polymarket scan cycles across ~50 markets, with ~10 markets requiring full LLM assessment per cycle:
- ~288 cycles/day × ~10 assessments × ~500 tokens each = ~1.44M input tokens/day
- At Sonnet 4.6 pricing: approximately $4-8/day depending on output length
- Monthly: ~$120-240

This is the operating cost floor. It rises with Bybit and Solana activity. Budget $300/month for inference until volume data justifies revision. This cost is a fixed overhead — model it as a deduction from gross P&L when calculating strategy expectancy.

### Effort Split (Revised)

**Four active venues as of 2026-04-06:**

| Venue | Effort % | Rationale |
|---|---|---|
| Polymarket | 40% | Deepest research base, strongest LLM-capability match, most validated strategies |
| Kraken Spot | 20% | Event-driven BTC/ETH/SOL positioning; CCXT/CLI ready; low build overhead |
| Jupiter Perps | 25% | SOL-PERP only; replaces blocked CEX futures; `jup` CLI installed; on-chain, no jurisdiction risk |
| Solana DEX | 15% | Observational/data-collection phase only until cost model validates; no active build until evidence |

Solana DEX effort in early phases is almost entirely watching and classifying — not building execution infrastructure. Jupiter Perps is higher priority than Solana DEX because it has lower round-trip costs and a cleaner signal requirement.

---

## Phase 0: Pre-Flight (Before Week 1 starts)
**Target completion: 2026-04-06**

These are blocking items. Nothing in Week 1 can start until they are done.

---

### VENUE SUBSTITUTION NOTICE: KuCoin/Bybit → Kraken (Spot Only)

**Both KuCoin and Bybit are inaccessible from Ontario, Canada.** KuCoin is permanently banned by the OSC. Bybit withdrew from Canada in 2023 and is also inaccessible. A full Ontario CEX audit (April 2026) confirmed that **no CEX with crypto perpetuals/futures operates legally for Ontario retail users** — every platform with a futures product either explicitly bans Ontario/Canada or is registered with the OSC under conditions that prohibit derivatives for retail clients.

**Futures are off the table for Ontario.** This is not a venue selection problem — it is a regulatory reality. The strategic response is to accept it, stop optimising around it, and focus capital and effort on the venues that are compliant and genuinely profitable: Polymarket and spot trading.

**The CEX slot is now Kraken — spot trading only:**
- OSC-registered (Payward Canada, Inc., MSB No. M19343731) — fully compliant for Ontario
- Spot BTC/ETH/SOL trading — event-driven positioning, not leveraged speculation
- Clean REST + WebSocket API, full CCXT support
- Maker 0.16% / taker 0.26% at base tier; drops to 0.00% / 0.10% at $50K+ 30-day volume
- Deep liquidity on major pairs adequate for IG-88's position sizes
- No leverage. No perpetuals. No Ontario legal risk.

**Strategic reframe — spot is not a consolation prize:**
- Event-driven positioning (protocol upgrades, macro catalysts, token unlocks) works on spot
- Regime-filtered momentum on BTC/ETH/SOL works on spot
- IG-88 enforcing entry/exit discipline on spot produces the same compounding benefit that was sought from futures discipline — without the leverage that historically gave back gains
- The compounding objective (positive expectancy × discipline × time) does not require leverage

**Note on prior KuCoin/Bybit accounts:** Do not use personal trading accounts for IG-88. Open a fresh Kraken account.

---

### CHRIS — P0.1: ~~Jurisdiction Check~~ RESOLVED

Jurisdiction confirmed: Ontario, Canada. Futures venues (KuCoin, Bybit) eliminated on regulatory grounds. CEX slot = Kraken spot. D1 closed.

**Blocker for:** P0.2, W1.C.2, W1.C.3

---

### CHRIS — P0.2: Decide Auto-Execute Threshold

IG88001 sets the default auto-execute threshold at $500 per trade. IG88002 recommends $50-100 to start given abysmally small capital.

**Action:** Set your starting threshold. This is a number Chris commits to and IG-88 hard-codes. It can only be raised after 50+ validated paper trades per venue.

**Recommended:** $50 for Polymarket, $50-100 for Kraken spot (smaller = more trades = faster statistical validation).

**Blocker for:** IG-88's execution module configuration

---

### IG-88 — P0.3: Read IG88001 and IG88002 in Full

Before any strategy design work begins, IG-88 must internalize both documents. Key sections:
- IG88001 §2: Venue strategies
- IG88001 §3: Position sizing and guardrails
- IG88002 §2: Critical gaps (all 7 — these are design requirements)
- IG88002 §4.9: Bybit futures greed-pattern guardrails (these must be coded, not policy)
- IG88002 §5.2: Revised risk parameters table

**Action:** Read both docs. Write a 200-word session note to `~/factory/agents/ig88/memory/ig88/scratchpad.md` confirming internalization and flagging any questions.

**Blocker for:** All IG-88 strategy work in Week 1

---

## Week 1: 2026-04-04 to 2026-04-11
**Goal: Polymarket MCP server ready. EVM wallet funded. IG-88 paper trading regime and strategy defined. Bybit API keys generated.**

---

### CHRIS — W1.C.1: Create EVM Wallet for IG-88

IG-88 needs a dedicated Polygon wallet for Polymarket. Do not reuse any personal wallet.

**Steps:**
1. Install MetaMask (or use an existing installation)
2. Create a new account — label it "IG-88 Polymarket"
3. Record the wallet address (public key) — share with Boot and IG-88
4. Record the seed phrase — store securely offline, never in any file or chat
5. Switch MetaMask network to Polygon (Chain ID 137)

**Then:**
6. Acquire USDC on Polygon. Recommended starting amount: the smallest viable amount you are willing to lose entirely (e.g., $50-200 USDC). This is paper-trade-adjacent capital — assume it is at risk.
7. Send USDC to the IG-88 Polygon wallet. **Must use Polygon network. Sending on Ethereum mainnet = lost funds.**
8. Note: as of early 2026, Polymarket uses native USDC (not bridged USDC.e). Circle/Polymarket announced native USDC integration — check current deposit instructions at docs.polymarket.com before depositing.

**Shares:** Wallet address (not seed phrase) → Boot (for MCP config), IG-88 (for account setup)

**Blocker for:** W2-3.B.1 (Polymarket MCP needs wallet address for auth), W4.I.1 (first Polymarket paper trade)

---

### CHRIS — W1.C.2: Create Kraken Account and Generate API Keys

**If you don't have a Kraken account:**
1. Sign up at kraken.com — use a fresh account, not any personal trading account
2. Complete Intermediate verification (KYC) — required for API trading access
3. Enable 2FA

**Generate API keys:**
1. Navigate to: Security → API → Create API Key
2. Create two keys:
   - **Read-only key:** permissions = Query Funds, Query Open Orders, Query Closed Orders, Query Trades. Label: "IG-88 Read".
   - **Trade key:** permissions = Query Funds + all Query permissions + Create & Modify Orders + Cancel & Close Orders. Label: "IG-88 Trade". Enable IP whitelist — add Whitebox's Tailscale IP (100.88.222.111).
3. Record: API Key + API Secret (Private Key) for each. Store securely in Bitwarden.
4. **Do not commit these to any git repo.**

**Note on fees:** Kraken's base maker/taker (0.16%/0.26%) drops significantly with volume. At IG-88's early scale these are the operating fees — model them into expectancy calculations.

**Shares:** Both key sets → Boot (for CCXT MCP config), IG-88 (for execution module)

**Blocker for:** W2-3.B.2 (CCXT MCP server config)

---

### CHRIS — W1.C.3: Fund Kraken Spot Account

**Steps:**
1. Deposit CAD via Interac e-Transfer or SWIFT (Kraken supports CAD deposits from Canadian banks), or deposit crypto directly (USDC, BTC, ETH, SOL accepted)
2. No internal transfer needed — Kraken spot is a unified account
3. Recommended starting amount: same philosophy as Polymarket — smallest amount you are willing to lose entirely during paper trading validation phase. The futures account needs enough to place paper trades without hitting minimum margin requirements (Level 1 minimum = ~$10 notional at 0.8% initial margin, so even $100 provides adequate room).

**Note:** Do not size up the futures wallet until 50+ paper trades are validated and IG-88 recommends graduation. Capital preservation is the entire point of the paper trading phase.

**Blocker for:** W4.I.3 (first Bybit paper trade)

---

### BOOT — W1.B.1: Scope Polymarket CLOB API

Before building the MCP server, Boot needs to assess the current state of the CLOB API and any existing open-source clients.

**Steps:**
1. Review Polymarket CLOB API documentation at `docs.polymarket.com`
2. Assess the official Python client (`py-clob-client`) and TypeScript client (`@polymarket/clob-client`) — determine which is more suitable for an MCP wrapper
3. Check for any existing Polymarket MCP servers in the open-source ecosystem (search GitHub for `polymarket mcp`)
4. Identify: auth mechanism (EIP-712 signed orders, L1/L2 API key tiers), rate limits (15,000 req/10s global, 3,500/10s for POST /order), WebSocket subscription format
5. Write a 1-page scoping note: recommended implementation approach, estimated build time, any blockers

**Output:** Scoping note posted to IG-88 Training room
**Blocker for:** W2-3.B.1

---

### IG-88 — W1.I.1: Define Regime Detection Criteria

The regime detection module is the Kill Switch. It must be defined before any paper trading begins — it is the first thing that runs on every cycle.

**Design requirements:**
- **Three states:** RISK_ON / NEUTRAL / RISK_OFF
- **Inputs (Solana DEX):** Dexscreener trending breadth (how many tokens trending vs. baseline), average recent performance of trending tokens (7-day), Graphiti pattern matches for prior regime-shift signatures, Pump.fun graduation rate trend
- **Inputs (Bybit):** BTC/SOL 24h price change, BTC/SOL volume vs. 7-day average, funding rates on Bybit perpetuals, VIX-equivalent (Crypto Fear & Greed Index from cfgi.io)
- **Inputs (Polymarket):** Not applicable — Polymarket strategies run in all regimes (event outcomes are uncorrelated with crypto regime). Exception: if RISK_OFF triggered by a crypto-specific event that would also affect crypto prediction markets, apply caution flag.
- **Output:** A score (0-10) with threshold mapping: 0-3 = RISK_OFF, 4-6 = NEUTRAL, 7-10 = RISK_ON
- **Hard rule:** No new positions opened in NEUTRAL or RISK_OFF on Solana DEX or Bybit. Polymarket continues regardless. All open positions tighten stops in RISK_OFF.

**Action:** Write the regime detection specification to `docs/ig88/` as a working document (does not need a IG88### number yet — this is a draft). Post summary to IG-88 Training room for Chris review.

**Blocker for:** W1.I.2, W4.I.2, W4.I.3

---

### IG-88 — W1.I.2: Select Starting Polymarket Strategy

The vault contains 6 validated Polymarket strategies (TX260330, hanakoxbt, 3,000+ backtests). IG-88 must select one to start with — not all six. Validate one edge before adding complexity (IG-88 Principle #11).

**The 6 strategies:**
1. **Base Rate Audit** — Market priced at $0.45 vs. 18% historical base rate → sell. Lowest inference complexity. Relies on historical data lookup.
2. **Conditional Probability Mispricing** — Mathematical contradictions across related market pairs (e.g., A + B > 1.0). Requires scanning multiple correlated markets simultaneously.
3. **Calibration Arbitrage** — Favourite-longshot bias: sell overpriced longshots (<15%), buy overlooked favourites (>85%). Empirically robust across 72M+ trades.
4. **Time Decay Extraction** — ~0.23%/day on correctly identified setups. Adapted from bond market-making. Requires precise timing.
5. **Liquidity Vacuum Fade** — Enter when bid-ask spread widens beyond threshold (thin market, temporary mispricing). Requires order book monitoring.
6. **Cross-Market Delta Hedge** — Hedge correlated markets against each other. Most complex; requires multi-position management.

**Recommendation criteria:** Start with the strategy that requires the fewest external data dependencies, has the clearest entry/exit rules, and is least susceptible to LLM overconfidence.

**Action:** Select one strategy. Write a 1-page selection rationale including: entry criteria, exit criteria, position sizing formula (Kelly-based), expected win rate range, expected R:R ratio, and how "no current market price" will be enforced during LLM probability assessment. Post to IG-88 Training room.

**[DECISION]** IG-88 to recommend; Chris to approve before Week 2 paper trading begins.

**Blocker for:** W2-3.I.1

---

### IG-88 — W1.I.3: Define Narrative Classification Taxonomy

Required before Solana DEX paper trading can begin (Week 4+).

**Categories to define (minimum):**
- AI / agent-themed tokens
- Political / PolitiFi tokens
- Celebrity / influencer tokens
- Ecosystem tokens (Solana-native projects)
- Animal memes (dog, cat, frog variants)
- Unclassified / other

**For each category, define:**
- Classification criteria (what makes a token belong to this category — text signals, wallet patterns, launch timing)
- Historical return profile (based on vault research + web data): typical pump duration, typical peak multiple, typical retracement depth, survival rate
- Entry criteria specific to category (e.g., celebrity tokens: DO NOT ENTER — vault data shows overwhelmingly negative returns)
- Exit criteria specific to category

**Action:** Write taxonomy to `docs/ig88/` working document. Flag any categories with insufficient data to trade (conservative default: if no return profile data, category is BLOCKED until data exists).

---

## Week 2-3: 2026-04-11 to 2026-04-25
**Goal: Polymarket MCP server operational. CCXT Bybit MCP operational. TradingView MCP deployed. Polymarket paper trading begins.**

---

### BOOT — W2-3.B.1: Build Polymarket MCP Server

**Input required from Chris:** IG-88 Polygon wallet address (from W1.C.1)
**Input required from IG-88:** Selected starting strategy + entry/exit criteria (from W1.I.2)

**Build spec:**

The MCP server must expose at minimum these tools to IG-88:

| Tool | Description |
|---|---|
| `polymarket_get_markets` | List open markets with filters (category, min_volume, max_probability) |
| `polymarket_get_market` | Full market detail: question, outcomes, current prices, volume, resolution criteria |
| `polymarket_get_orderbook` | Current bid/ask depth for a market |
| `polymarket_place_order` | Place GTC (maker) or FOK (taker) order — **maker preferred, zero fees** |
| `polymarket_cancel_order` | Cancel a specific order |
| `polymarket_get_positions` | Current open positions for IG-88 wallet |
| `polymarket_get_trades` | Trade history for IG-88 wallet |

**Auth:** Polymarket uses EIP-712 signed orders. The MCP server needs access to IG-88's private key to sign orders. **Security requirement:** private key must never appear in logs, tool output, or Matrix messages. Use environment variable `POLYMARKET_PRIVATE_KEY`.

**Rate limits to respect:** 3,500/10s burst for POST /order; 9,000/10s general CLOB. Implement backoff.

**Implementation path (in order of preference):**
1. Check if an existing Polymarket MCP server exists on GitHub — adapt rather than build from scratch
2. If not, wrap `py-clob-client` (official Python client) as an MCP server using the FastMCP pattern
3. TypeScript alternative: wrap `@polymarket/clob-client`

**Paper trading mode:** Add a `paper_mode: bool` flag. When true, all orders are logged but not submitted. This is the default until Chris reacts ✅ to the "ready for live" announcement.

**Testing:** Before IG-88 touches it, Boot must verify: market listing works, orderbook fetching works, paper mode order logging works. Post test results to IG-88 Training room.

**Blocker for:** W4.I.1

---

### BOOT — W2-3.B.2: Deploy CCXT MCP Server for Bybit

**Input required from Chris:** Kraken API key + secret (from W1.C.2)

**Steps:**
1. Fork `doggybee/mcp-server-ccxt` from GitHub
2. Configure for Kraken: add API credentials via environment variables (`KRAKEN_API_KEY`, `KRAKEN_SECRET`)
3. Verify the 24 default tools work: tickers, orderbooks, OHLCV, account balance, place order, cancel order
4. Add strategy-specific tools as thin wrappers:
   - `kucoin_get_funding_rate` — current + historical funding rate for a symbol
   - `kucoin_get_position` — current futures position details
   - `kucoin_set_leverage` — set leverage for a symbol (default 3x)
   - `kucoin_get_open_orders` — all open orders
5. Add paper trading mode flag (same pattern as Polymarket MCP)
6. **Disable:** Do not enable UTA (Unified Trading Account) API — Bybit's own docs say "DO NOT use in production." Use legacy spot + futures APIs.

**Note on CCXT builder fee:** CCXT adds a 1 bps builder fee by default. Disable it: set `exchange.options['broker'] = ''` or equivalent.

**Note on Kraken API auth:** Kraken uses API Key + API Secret (private key). Auth is HMAC-SHA256 with nonce. The CCXT library handles this automatically; ensure exchange ID is set to `'kraken'`. Kraken also supports the newer Kraken Futures API — do not use it; spot only.

**Kraken Pro vs regular Kraken:** The CCXT `'kraken'` exchange ID targets kraken.com (spot). This is correct. Do not use `'krakenfutures'`.

**Testing:** Verify read operations work (balance, tickers, orderbook). Do NOT test live orders until IG-88 has confirmed the paper trading mode is working correctly.

**Blocker for:** W4.I.3

---

### BOOT — W2-3.B.3: Deploy TradingView MCP

**Steps:**
1. Install TradingView Desktop app on Whitebox (Mac Studio) if not already installed
2. Find or build `tradingview-mcp` (TX260331, Tradesdontlie — search GitHub for `tradingview-mcp`)
3. Launch TradingView Desktop with CDP flag: `open -a TradingView --args --remote-debugging-port=9222`
4. Verify MCP server connects to port 9222 and can read chart data
5. Configure TradingView chart to display the indicator set Chris used historically — **see [DECISION] below**
6. Verify IG-88 can read indicator values via MCP tools

**[DECISION — Chris input required]:** What indicators did you use? Common candidates:
- RSI (14) — momentum / overbought / oversold
- MACD — trend direction and momentum
- EMA (20/50/200) — trend levels and crossovers
- Volume (and volume MA) — confirmation
- Bollinger Bands — volatility and mean reversion
- Support/Resistance levels — price levels
- Any custom Pine Script indicators

**Action for Chris:** List the indicators you used. Boot will configure the TradingView chart to match. IG-88 will then have read access to the same data you worked with manually.

**Fragility warning:** `tradingview-mcp` accesses undocumented internal TradingView APIs via CDP. Any TradingView app update can break it silently. Boot must add a health check to the coordinator that verifies the connection on startup and alerts via Matrix if broken.

**Blocker for:** W4.I.2 (regime detection can use TV indicators as inputs), W4.I.3 (Kraken entries can use TV signals)

---

### IG-88 — W2-3.I.1: Polymarket Strategy Implementation

**Input required:** Approved strategy selection (from W1.I.2), Polymarket MCP server (from W2-3.B.1)

**Build the strategy execution loop:**

```
Every 5 minutes (coordinator timer):
1. Fetch open markets matching category filter (exclude crypto-category markets during RISK_OFF)
2. For each candidate market:
   a. Fetch market detail — question, resolution criteria, current price
   b. BLIND the LLM to the current price — do NOT include it in the prompt
   c. LLM assesses probability independently using: base rates, comparable historical events,
      available evidence, Graphiti pattern matches
   d. Compare LLM estimate to market price
   e. If |LLM_estimate - market_price| > edge_threshold AND confidence >= 0.6: candidate trade
3. For each candidate trade:
   a. Calculate position size: f_kelly * (1 - CV_edge) * 0.25 (quarter-Kelly, first 200 trades)
   b. Verify position size <= 10% of venue wallet
   c. In paper mode: log to trading.md and report to Matrix
   d. In live mode: place maker order via polymarket_place_order
4. Monitor open positions: update stops, log time decay, exit when target hit
5. Log everything to Graphiti: market, LLM estimate, market price, edge, outcome (at resolution)
```

**Key constraint:** The LLM must never see `current_price` when forming its probability estimate. The prompt structure must be audited to confirm this — test by checking whether IG-88's estimates cluster around market prices (if correlation > 0.5, the price is leaking in somehow).

**Brier score tracking:** After every resolved market, compute: `BS = (forecast - outcome)^2`. Log to Graphiti. Running Brier score target: < 0.20 at 50 trades, < 0.15 at 200 trades.

---

### IG-88 — W2-3.I.2: Implement Variance Drag Calculator

Before any live trading on any venue, IG-88 must implement and run this calculation.

**Formula:** `Geometric_return = Arithmetic_return - (sigma^2 / 2)`

**For each venue strategy:**
- Estimate arithmetic average return per trade (from paper trading data, or from vault benchmarks as prior)
- Estimate annualized volatility (sigma) of the strategy's return distribution
- Calculate geometric return
- **If geometric return < 0: strategy is a wealth destroyer. Do not graduate to live.**

**Report:** Post variance drag analysis for each active strategy to IG-88 Training room. Update quarterly or after any significant change in strategy parameters.

---

## Week 4-5: 2026-04-25 to 2026-05-09
**Goal: Polymarket paper trading active (~3-5 trades/day). Bybit paper trading begins. Solana DEX data collection continues. Graphiti schema operational.**

---

### IG-88 — W4.I.1: Begin Polymarket Paper Trading

**Prerequisites (all must be met):**
- [ ] EVM wallet funded (W1.C.1)
- [ ] Polymarket MCP server operational (W2-3.B.1)
- [ ] Strategy selection approved (W1.I.2)
- [ ] Variance drag calculated and positive (W2-3.I.2)
- [ ] LLM price-blinding verified (W2-3.I.1)

**Paper trading protocol:**
- Target: 3-5 trades per day
- Minimum hold: no minimum (Polymarket positions can resolve quickly)
- Max open positions simultaneously: 5
- Kelly fraction: quarter-Kelly for all trades until 200 trades completed
- Log every trade to Graphiti immediately: market, LLM estimate, market price, edge size, position size, entry timestamp, resolution (when it occurs)
- Post daily summary to IG-88 Training room: trades entered, positions open, running Brier score, running P&L

**Milestones:**
- 50 trades: sanity check — confirm pipeline works, Brier score trending
- 100 trades: formal evaluation — compute expectancy with confidence intervals, report to Chris
- 200 trades: statistical kill/continue decision

---

### IG-88 — W4.I.2: Begin Kraken Spot Paper Trading

**Prerequisites (all must be met):**
- [ ] Kraken API keys configured (W1.C.2)
- [ ] Kraken account funded (W1.C.3)
- [ ] CCXT MCP server operational (W2-3.B.2)
- [ ] TradingView MCP operational (W2-3.B.3)
- [ ] Regime detection module operational (W1.I.1)
- [ ] Variance drag calculated (W2-3.I.2)

**Strategy: Event-driven spot positioning on BTC/ETH/SOL.**

No leverage. No perpetuals. The edge is regime-gated entry and exit discipline — entering high-conviction positions during RISK_ON based on event catalysts (protocol upgrades, macro shifts, token unlocks, earnings-adjacent events), and exiting systematically rather than emotionally.

**Paper trading protocol:**
- Target: 1-2 trades per day
- No leverage — spot only
- Max open positions simultaneously: 3
- Kelly fraction: quarter-Kelly (position sized as % of Kraken wallet, not leveraged notional)
- Instruments: BTC/USD, ETH/USD, SOL/USD only
- Only enter in RISK_ON regime
- Minimum hold: 4 hours (prevents churn through Kraken's 0.26% taker fees)
- Use limit orders wherever possible (0.16% maker vs 0.26% taker — meaningful at scale)

**Discipline implementation checklist (replaces futures greed guardrails):**
- [ ] Profit target triggers automatic close — no "let it run" path
- [ ] Position size formula: Kelly output only — never manually sized up
- [ ] Re-entry cooldown: 2 hours after any close on same instrument
- [ ] Daily loss halt: if spot positions lose >3% of Kraken wallet in a day, halt new entries until next UTC day
- [ ] Fee drag tracker: log maker/taker fee paid per trade — if taker fees >15% of gross P&L, enforce limit-order-only mode

**Log every trade to Graphiti:** instrument, regime state, entry price, catalyst/rationale, target, stop, exit reason, fee paid, outcome.

---

### IG-88 — W4.I.4: Begin Jupiter Perps Paper Trading

**Prerequisites (all must be met):**
- [ ] `jup` CLI installed (DONE — v0.7.1 on Whitebox and Cloudkicker)
- [ ] `jup` perps MCP wrapper operational (W2-3.B.4)
- [ ] Solana wallet funded (existing)
- [ ] Regime detection module operational (W1.I.1)
- [ ] Variance drag calculated (W2-3.I.2)

**Paper trading protocol:**
- Instrument: SOL-PERP only — no BTC or ETH perps
- Target: 1-2 trades per day (high-conviction signals only — fee threshold filters most candidates)
- Leverage: 3x default, 5x maximum
- Max open positions simultaneously: 1 SOL-PERP at a time
- Kelly fraction: quarter-Kelly on Solana wallet allocation
- Only enter in RISK_ON regime
- Minimum hold: 2 hours; maximum hold: 8 hours
- Every trade must have TP and SL set at entry

**Fee drag check (mandatory before every paper trade entry):**
```
Expected move (%) × leverage > 0.25%
```
If this condition is not met, do not trade. Log the skipped signal to Graphiti.

**Log every trade to Graphiti:** asset, side (long/short), leverage, entry price, TP%, SL%, regime state, signal rationale, borrow fee accumulated, exit reason, outcome R-multiple.

**Blocker for:** Live Jupiter Perps trading (graduation criteria same as other venues)

---

### IG-88 — W4.I.3: Solana DEX — Data Collection Mode Only

Solana DEX paper trading does not begin in Week 4. The round-trip cost problem (15-25% on low-liquidity tokens) means the bar for entry is high. Week 4 is data collection.

**Actions:**
- Run the Dexscreener trending monitor continuously (already wired per IG88001)
- For each trending token: classify narrative category (using taxonomy from W1.I.3), record regime state, record liquidity depth, record time-of-day
- Do NOT simulate trades yet — collect the data that will inform which tokens are tradeable (liquidity threshold: >$200K to be eligible for any paper trade)
- Log everything to Graphiti

**When to begin Solana paper trading:** After liquidity filter and cost model are validated with 2+ weeks of data, and after at least one other venue (Polymarket or Bybit) has completed 50 paper trades.

---

### BOOT — W2-3.B.4: Build Jupiter Perps MCP Wrapper

`jup` has no native MCP server. Build a thin subprocess-based MCP server that wraps the `jup perps` and `jup lend` command groups.

**Architecture:** MCP server spawns `jup -f json <subcommand> <args>`, parses stdout as JSON, surfaces as MCP tool response. All read commands run unconditionally. Write commands (`jup_perps_open`, `jup_lend_deposit`, `jup_lend_withdraw`) are gated behind `paper_mode: bool`.

**Tools to expose:**

| MCP Tool | `jup` Command | Paper Mode Gate |
|---|---|---|
| `jup_perps_markets` | `jup -f json perps markets` | No |
| `jup_perps_positions` | `jup -f json perps positions` | No |
| `jup_perps_history` | `jup -f json perps history --asset SOL` | No |
| `jup_perps_open` | `jup -f json perps open --asset SOL --side <s> --amount <a> --leverage <l> --tp <tp> --sl <sl>` | **Yes** |
| `jup_perps_close` | `jup -f json perps close --position <id>` | **Yes** |
| `jup_perps_close_all` | `jup -f json perps close` | **Yes** |
| `jup_perps_set` | `jup -f json perps set --position <id> --tp <tp> --sl <sl>` | **Yes** |
| `jup_lend_tokens` | `jup -f json lend earn tokens` | No |
| `jup_lend_positions` | `jup -f json lend earn positions` | No |
| `jup_lend_deposit` | `jup -f json lend earn deposit --token SOL --amount <a>` | **Yes** |
| `jup_lend_withdraw` | `jup -f json lend earn withdraw --token SOL --amount <a>` | **Yes** |

**Key implementation notes:**
- Inject wallet via `JUPE_PRIVATE_KEY` env var from Infisical (not `--private-key` flag — leaks to process listings)
- Set `JUP_OUTPUT=json` or pass `-f json` on every call
- No retry built into `jup` — implement exponential backoff (3 retries, 500ms initial) in the wrapper
- `jup perps open` on SOL-PERP only — reject any call with `--asset BTC` or `--asset ETH` at the wrapper layer
- Leverage hard cap: reject any `--leverage` value > 5
- Log all calls (including paper mode) to Graphiti via `jup_perps_open` event schema

**Install location:** `~/dev/factory/mcp-servers/jup-perps-mcp/` (alongside existing MCP servers)

**Relationship to existing Jupiter MCP server:** The existing Jupiter MCP server handles spot swaps, price feeds, limit orders, DCA. This wrapper handles perps and lend only. No overlap.

**Blocker for:** W4.I.4 (Jupiter Perps paper trading)

---

### BOOT — W4.B.1: Graphiti Schema for Trade Storage

**Design the schema IG-88 will use to store every trade.** The goal is a queryable knowledge graph that improves IG-88's decisions over time.

**Per-trade entity fields:**
```
trade_id: string (venue + timestamp)
venue: polymarket | kucoin_futures | solana_dex
strategy: base_rate_audit | calibration_arb | time_decay | event_driven | regime_momentum | narrative_momentum
entry_timestamp: ISO 8601
exit_timestamp: ISO 8601 (null until closed)
instrument: market question (Polymarket) | trading pair (Bybit) | token address (Solana)
narrative_category: AI | political | celebrity | ecosystem | animal_meme | n/a
regime_state: RISK_ON | NEUTRAL | RISK_OFF
time_of_day_utc: hour 0-23
liquidity_at_entry: USD (Solana DEX only)
llm_estimate: float 0-1 (Polymarket only)
market_price_at_entry: float 0-1 (Polymarket only)
entry_price: float
exit_price: float (null until closed)
position_size_usd: float
leverage: float (Bybit only)
stop_level: float
target_level: float
r_multiple: float (null until closed) — (exit_price - entry_price) / (entry_price - stop_level)
outcome: win | loss | breakeven (null until closed)
exit_reason: target_hit | stop_hit | time_stop | volume_stop | manual
brier_score: float (Polymarket only, null until resolved)
notes: string
```

**Queryable patterns (these are the queries IG-88 will run):**
- "AI narrative tokens in RISK_ON entered within 2h of trending, >$200K liquidity: median R-multiple, WR, N="
- "Calibration arbitrage trades where LLM estimate diverged >15% from market: Brier score distribution"
- "Bybit event-driven trades by time-of-day: best performing UTC hours"
- "All trades where averaging-down guardrail would have fired: what would have happened"

**Implementation:** Use Graphiti's `add_memory` with structured JSON episodes. Group IDs: `trading_polymarket`, `trading_kucoin`, `trading_solana`. Post schema to IG-88 Training room for IG-88 review before implementation.

---

## Week 6+: 2026-05-09 onward
**Goal: First live trades on validated strategies. Portfolio rebalancing begins.**

---

### Hard Prerequisite: Infisical Secret Migration

**No strategy may graduate from paper to live until the Infisical migration is complete.**

Two private keys must be stored in Infisical before any live trade executes:

| Secret | Current State | Required State |
|---|---|---|
| Polymarket wallet private key (Polygon) | Not yet stored — key pending generation | Infisical named secret, read by IG-88 at runtime via SDK |
| Solana trading wallet private key | Flat file `~/.config/ig88/trading-wallet.json` (chmod 600) | Infisical named secret, migrate from flat file |

**Why this blocks live trading:** Both wallets will hold real capital. A flat file private key with no access control, audit logging, or rotation capability is not acceptable for production. BWS is the current vault but is being migrated — do not store new secrets in BWS. Wait for Infisical.

**This does not block paper trading.** Paper mode does not sign transactions or move funds. IG-88 can run full paper trading cycles on all venues before Infisical is live.

**Owner:** Chris (Infisical account setup + migration decision). Boot (SDK integration once Infisical is live).

---

### Graduation Criteria (Paper → Live)

A strategy graduates from paper to live when ALL of the following are met:

| Criterion | Threshold | Notes |
|---|---|---|
| Trade count | ≥ 200 completed trades | Not 50. Statistical minimum. |
| Positive expectancy | E > 0 | After costs |
| Statistical significance | p < 0.10 | Binomial test or t-test on R-multiples |
| Geometric return positive | `arithmetic_return - sigma^2/2 > 0` | Variance drag check passes |
| Brier score (Polymarket only) | < 0.20 | At 200 trades |
| Max paper drawdown | < 15% | During the paper period |
| Greed guardrails | All firing correctly | Verified by reviewing trade logs |
| **Chris approval** | ✅ reaction on graduation request | Required. No exceptions. |

**Graduation process:**
1. IG-88 posts graduation request to IG-88 Training room with full statistics
2. Chris reviews within 48 hours
3. If approved: IG-88 graduates to live with smallest viable position size (1/4 of paper trade size, then scale up over 20 live trades)
4. If not approved: IG-88 continues paper trading and addresses stated concerns

---

### W6+: Kill Criteria (Venue Shutdown)

A venue is killed when:
- Negative expectancy at 200+ trades with 95% confidence, OR
- Variance drag check fails (geometric return < 0), OR
- Three consecutive daily drawdown halts in a 10-day window, OR
- Chris requests shutdown

Killed venues are archived in Graphiti with full statistics. Data is preserved — it never goes to waste.

---

### W6+: Portfolio Rebalancing

Monthly review of venue-level Sharpe ratios and expectancy. Rebalancing rules:
- Increase allocation to highest-Sharpe venue by 10 percentage points
- Decrease lowest-Sharpe venue by 10 percentage points
- Never allocate less than 20% to any active venue (maintains diversification)
- Shannon's Demon rebalancing premium applies only when venue correlations are genuinely low — verify monthly using Graphiti cross-venue return data

---

## Open Decisions Registry

Items marked **[DECISION]** above are tracked here.

| ID | Decision | Owner | Required by | Status |
|---|---|---|---|---|
| D1 | Jurisdiction check re: CEX venue | Chris | W1.C.2 | **RESOLVED** — Ontario, CA. KuCoin/Bybit banned. Futures eliminated. Kraken spot only. |
| D2 | Auto-execute threshold ($50 vs $100 vs other) | Chris | P0.2 | Pending |
| D3 | Polymarket starting strategy selection | IG-88 recommends, Chris approves | W2-3.I.1 | Pending |
| D4 | Kraken spot pairs: BTC/ETH only or add SOL | IG-88 recommends | W4.I.2 | Pending |
| D5 | TradingView indicator set (Chris's historical setup) | Chris | W2-3.B.3 | Pending |
| D6 | Graphiti group_id schema | IG-88 + Boot | W4.B.1 | Pending |
| D7 | Infisical migration (BWS → Infisical) — blocks live trading | Chris + Boot | Before any live trade | **In progress** — Infisical v0.43.69 on Whitebox + Cloudkicker, projects created (Factory + IG88), secrets being populated. See IG88009. |

---

## Risk Parameters Reference (Revised per IG88002)

| Parameter | Value | Notes |
|---|---|---|
| Kelly fraction (first 200 trades) | Quarter-Kelly | Graduate to half-Kelly after 200+ validated |
| Kelly fraction (200+ validated trades) | Half-Kelly | Never full Kelly |
| Monte Carlo leverage cap | 3x max | Even at half-Kelly |
| Max position size | 10% of venue wallet | Target 5% |
| Daily drawdown halt | 5% | 3% triggers review |
| Auto-execute threshold | TBD (Decision D2) | $50-100 recommended |
| Paper trade sanity check | 50 trades | Confirms pipeline, not edge |
| Paper trade formal evaluation | 100 trades | Compute expectancy + confidence intervals |
| Paper trade kill/continue | 200 trades | Statistical decision |
| Kraken position type | Spot only — no leverage | Regulatory constraint (Ontario) |
| Kraken order type | Limit orders preferred | 0.16% maker vs 0.26% taker |
| Solana DEX liquidity minimum | $200K | Below this: do not trade |
| Solana DEX max new positions/day | 4 | Prevents churn through round-trip costs |
| Solana DEX min hold time | 2 hours | ATR-stop replaces flat -8% |

---

## References

[1] IG88001 Multi-Venue Trading Action Plan, 2026-04-04.

[2] IG88002 Senior Review of Multi-Venue Trading Action Plan, 2026-04-04.

[3] hanakoxbt, "How Claude Extracts Consistent Edge From Prediction Markets: Six Backtested Strategies," research-vault TX260330_1151-CF65.

[4] AleiahLock, "How I Built a Bot That Trades Polymarket While I Sleep," research-vault TX260403_0940-9790.

[5] RohOnChain, "Institutional Prediction Market Hedge Fund Operations Complete Breakdown," research-vault TX260306_1911-9AEE.

[6] Tradesdontlie, "TradingView MCP — 78 Tools Connecting Claude to Live Charting via Chrome DevTools Protocol," research-vault TX260331_2040-467F.

[7] noisyb0y1, "How to Go from Zero to Profitable on Prediction Markets in 6 Months," research-vault TX260320_0612-5798.

[8] hanakoxbt, "How Math Bots Extract Money Without Predicting," research-vault TX260320_1127-128B.
