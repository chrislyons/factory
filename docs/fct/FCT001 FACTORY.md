# FCT001 FACTORY
## Initial Architecture & Strategic Plan
*Boot Industries — March 2026 — Draft*

---

## Table of Contents

1. [Hardware Stack](#1-hardware-stack)
2. [Local Inference Infrastructure](#2-local-inference-infrastructure)
3. [Agent Architecture](#3-agent-architecture)
4. [Fine-Tuning Strategy](#4-fine-tuning-strategy)
5. [Trading System — @ig88](#5-trading-system--ig88)
6. [Data Architecture](#6-data-architecture)
7. [Four-Week Execution Plan](#7-four-week-execution-plan)
8. [Canadian Tax Considerations](#8-canadian-tax-considerations)
9. [Future Considerations](#9-future-considerations)

---

## 1. Hardware Stack

### 1.1 Primary Inference Server — Mac Studio (Pending)

Target acquisition: M1 Max Mac Studio, 32GB unified memory, 512GB SSD. Open Box Excellent condition via Best Buy Canada with 1-year GainSaver warranty. Effective working memory budget for model inference: approximately 24GB after macOS overhead.

| Spec | Value | Notes |
|---|---|---|
| Chip | M1 Max | 10-core CPU, 24-core GPU |
| Memory | 32GB Unified | ~24GB effective for inference |
| Memory BW | 400 GB/s | Primary inference speed factor |
| Storage | 512GB SSD | Sufficient for multiple model weights |
| Interconnect | Thunderbolt 4 | TB4 — RDMA not available (TB5 only) |
| Thermal | Active cooling | Sustained 24/7 workloads — no throttle |
| OS | macOS | MLX native support |

### 1.2 Secondary Machine — M2 MacBook Pro 16GB

Role: @kelk agent host and development machine. Not suitable for primary inference due to thermal throttling under sustained load and 16GB memory ceiling. Connected to Mac Studio via Thunderbolt 4 bridge for local network routing when both machines are active.

---

## 2. Local Inference Infrastructure

### 2.1 Inference Backend

Primary: Ollama for multi-model lifecycle management, lazy loading/eviction, and OpenAI-compatible API endpoints per model on separate ports. MLX-LM for lower-level fine-tuning and direct model experimentation. CCXT handles all exchange connectivity independently of the inference stack.

### 2.2 Quantization Strategy

Default quantization: 6-bit (Q6). Rationale: materially better quality than 4-bit on reasoning and instruction following tasks, ~15-20% slower than 4-bit but within acceptable range for non-latency-critical agents. 4-bit reserved for @ig88 where inference speed matters most. 8-bit avoided — memory cost too high relative to quality gain on 32GB budget.

| Quantization | Quality | Speed vs 4-bit | Use case |
|---|---|---|---|
| 8-bit | Best | -50% | Avoided on 32GB — memory cost too high |
| 6-bit | Very good | -15% | Default for all agents except @ig88 |
| 4-bit | Good | Baseline | @ig88 — speed priority |
| 3-bit | Degraded | +20% | Not used |

### 2.3 Memory Layout

**Resident stack (always loaded):**

| Agent | Model | Quant | Footprint |
|---|---|---|---|
| @ig88 | Qwen3.5 4B | 4-bit | ~2.5GB |
| @boot | LFM2.5 1.2B | 6-bit | ~1.0GB |
| VL module | LFM2.5-VL-1.6B | 6-bit | ~1.4GB |
| Audio module | LFM2.5-Audio-1.5B | 6-bit | ~1.3GB |
| Embedding | nomic-embed-text | — | ~0.1GB |
| @coord | Python (no model) | — | 0GB |
| **Subtotal** | | | **~6.3GB** |

**On-demand stack (loaded as needed, one at a time):**

| Agent | Model | Quant | Footprint |
|---|---|---|---|
| @nan | Qwen3.5 9B | 6-bit | ~7.2GB |
| @kelk | Qwen3 4B (interim) | 6-bit | ~3.4GB |

Peak total (resident + @nan): ~21GB. Leaves ~3GB headroom for KV cache across active contexts. Comfortable for sustained operation.

---

## 3. Agent Architecture

### 3.1 Agent Roster

| Agent | Role | Model | Always On |
|---|---|---|---|
| @coord | Meta-agent: coordinator, systems admin, message routing. Zero intelligence by design — deterministic Python only. | None (Python) | Yes |
| @ig88 | Autonomous trading agent. 24/7 crypto futures markets. Signal-to-decision pipeline. Structured output only. | Qwen3.5 4B (4-bit) | Yes |
| @boot | Project manager and operations agent. Task tracking, delegation, state management. | LFM2.5 1.2B (6-bit) | Yes |
| @nan | Meta-agent advisor with thinking intelligence. Strategic review, diagnosis, synthesis. On-demand only. | Qwen3.5 9B (6-bit) | No |
| @kelk | Personal assistant with emotional/spiritual intelligence. Conversational, tonal, contextual. | Qwen3 4B (6-bit) | No |
| @? | Future modular agents. Default 1B-9B unless role explicitly justifies more. | TBD | TBD |

### 3.2 Multimodal Capabilities

Two Liquid multimodal modules run as shared services accessible to all agents:

- **LFM2.5-VL-1.6B (Vision-Language):** Chart image analysis for @ig88, document/UI reading for @boot, multi-chart comparative reasoning for @nan. Native resolution up to 512×512, strong OCR, multi-image support.
- **LFM2.5-Audio-1.5B (Audio-Language):** Voice interface for @kelk, verbal strategy sessions with @nan, audio alerts from @ig88 (position opened, stop hit, P&L thresholds). Native speech-to-speech, 8× faster detokenizer than previous generation.

### 3.3 Inter-Agent Communication

Matrix protocol (via Element) as the messaging substrate. Typed event schemas (`com.bootindustries.agent.state`) for structured agent state. @coord manages routing, lifecycle, and human-in-the-loop rendering. Each agent exposes an OpenAI-compatible API endpoint via Ollama on a dedicated port.

### 3.4 Shared Memory / RAG

nomic-embed-text embedding model (~0.1GB, always resident) provides semantic search across all agent memory sources: trade history SQLite, news archive, Obsidian vault, memex-mcp email archive. All agents share this retrieval layer via @coord.

---

## 4. Fine-Tuning Strategy

### 4.1 Architecture Notes

Both primary model families support LoRA fine-tuning. MLX-LM supports LoRA natively on Apple Silicon — training a narrow task adapter on a 4B model with hundreds to low thousands of examples is feasible on M1 Max in hours, not days.

Fine-tuning objective: collapse output distribution onto specific task surface. Does not fix factual recall errors in pretraining weights. Most effective for: output format reliability, domain vocabulary, task-specific instruction following, reducing off-task drift.

### 4.2 Priority Order

| Priority | Agent | Rationale | Training focus |
|---|---|---|---|
| 1 | @ig88 | Directly tied to P&L. Highest leverage. | Signal schemas, KuCoin order vocabulary, risk parameter structured output, decision formatting |
| 2 | @kelk | Most sensitive to training data quality. Requires most care. | Personal vocabulary, communication style, tonal calibration, emotional/spiritual intelligence patterns |
| 3 | @nan | Least tuning needed — thinking mode does heavy lifting. | Domain vocabulary, strategic frameworks, decision review patterns |
| 4 | @boot | Simplest task surface. Tune last. | Operational schemas, task routing vocabulary, project state management |

### 4.3 Model Family Notes

- **Qwen3.5 small family (0.8B–9B):** Hybrid MoE architecture. Excellent tool-calling and structured output. Known hallucination weakness on factual recall (80–82% hallucination rate on factual benchmarks for 4B/9B). Use with RAG grounding for any factual tasks. Thinking mode available — reserve for @nan, disable for @ig88 (speed priority).
- **LFM2.5 family:** Linear recurrent architecture. Superior on sequential/temporal tasks, streaming, and long-context with flat memory cost. Less capable on complex multi-hop reasoning. Architecturally well-suited to @boot (state tracking) and @kelk (conversational continuity).
- **Qwen3 dense (non-.5):** More reliable factual recall than Qwen3.5 MoE at equivalent sizes. Preferred for @kelk interim until LFM2.5 3B releases.

---

## 5. Trading System — @ig88

### 5.1 Market & Exchange

Primary market: KuCoin Futures, BTC/USDT perpetual. Rationale: crypto markets are less efficient than equities at 1-minute timeframes, wider edges persist longer, KuCoin API is well-documented with CCXT support, no equities knowledge required.

| Parameter | Value | Notes |
|---|---|---|
| Exchange | KuCoin Futures | CCXT integration |
| Pair | BTC/USDT Perpetual | Deepest liquidity on KuCoin |
| Timeframe | 1-minute bars | Primary signal timeframe |
| Leverage | 2–3× maximum | Survival over aggression in Phase 1 |
| Maker fee | 0.02% | Use limit orders where possible |
| Taker fee | 0.06% | 0.12% round trip — significant at scale |
| Starting capital | <$1,000 CAD | Validation budget only |

### 5.2 Strategy: Momentum Continuation

Core thesis: price at 1-minute exhibits short-term momentum after volume-confirmed breakouts. Entry when all conditions met:

- Price breaks above/below recent swing high/low on 1-minute chart
- Volume on breakout bar >1.5× the 20-bar average
- 15-minute trend is aligned (no counter-trend trades)
- RSI on 1-minute not already overbought/oversold at entry

Exit conditions (mechanical, no discretion):

- **Stop loss:** 1.5× ATR below entry — set at order placement, never moved against position
- **Take profit:** 2× the stop distance (minimum 1:2 risk/reward ratio)
- **Time stop:** if neither target nor stop hit within 15 bars, exit at market

The time stop directly addresses the identified human failure mode: holding positions that aren't moving, waiting for a move that doesn't come.

### 5.3 LLM Filter Layer

The LLM stack operates as a pre-trade filter, not in the execution loop:

- **Pre-session:** LFM2.5 1.2B scans overnight news for trading pairs. Outputs catalyst flag (bullish / bearish / neutral / major event). Major events trigger stop widening or full standdown.
- **Real-time:** Sentiment score on 15-minute intervals from crypto news feeds. Used to weight position size: full size in clean trending conditions, half size in noisy/uncertain conditions.
- **VL module:** Optional chart image analysis — pattern recognition on rendered candlestick images as supplementary signal validation.

### 5.4 API Surface

KuCoin provides two complementary API surfaces:

- **REST API:** Historical OHLCV (up to 1500 bars per query, paginated by time), order placement with native take-profit/stop-loss, account balance, position queries, funding rate history. Used for backtesting data acquisition and order management.
- **WebSocket:** Real-time 1-minute bar feed (primary signal input — REST polling cannot keep up), live order book depth, position and order updates. Non-negotiable for 1-minute strategies.

CCXT wraps both surfaces with unified authentication handling. KuCoin Unified Trading Account API (launched Sept 2025) used from the start — consolidates spot and futures under single domain, future-proof.

### 5.5 Fee Management

At 0.12% round trip (taker both sides), fee drag is substantial at small capital. Mitigations:

- Use limit orders for entry where fill probability allows (reduces to 0.08% round trip)
- Target 3–5 high-quality setups per day maximum — quality over frequency
- Monitor KuCoin VIP tier thresholds as volume grows

**Minimum edge threshold:** a strategy needs >0.15% average profit per trade to remain viable after fees at taker rates. This is the backtest pass/fail threshold.

### 5.6 Risk Management

Hard rules, no model involvement:

- Max position size: Kelly fraction (conservative — half-Kelly minimum)
- Per-trade stop loss: ATR-based, 1.5× ATR, set at entry
- Daily drawdown limit: halt all trading at -2% account value
- No correlated positions simultaneously
- Maximum exposure: never >X% in single asset

---

## 6. Data Architecture

### 6.1 Storage Layer

Dual-layer storage optimized for distinct access patterns:

- **SQLite:** Live operational data — current positions, open orders, trade log, signal history, bot state, agent memory. Fast writes, queryable, zero infrastructure, single file. Runtime database for all agents.
- **Parquet:** Historical OHLCV archives. Columnar, compressed, read natively by pandas and VectorBT at high speed. Write once, read many. Backtesting against Parquet is fast; against SQLite is slow for large datasets.

### 6.2 Historical Data Acquisition

KuCoin klines endpoint returns up to 1500 bars per query. At 1-minute resolution: 1500 bars = ~25 hours. Fetching 3–6 months requires ~2160–4320 paginated requests with rate limit respect. CCXT `fetch_ohlcv` handles pagination. Output: Parquet files partitioned by month.

Target history depth: 6 months minimum. Captures bull, bear, and sideways regimes for honest backtesting. More regimes = more honest backtest = more reliable live performance prediction.

### 6.3 Frontend

Custom React dashboard against local FastAPI endpoint reading SQLite state. Replaces Grafana (built for infrastructure monitoring, not trading). Displays: open positions, P&L, signal log, agent status, recent trades, drawdown meter. Claude Code builds this in Phase 2.

---

## 7. Four-Week Execution Plan

| Week | Goal | Deliverables |
|---|---|---|
| 1 | Backtest validation | Historical data acquisition (6 months BTC/USDT 1-min via CCXT → Parquet). VectorBT backtest of momentum continuation strategy. Pass threshold: >0.15% avg profit/trade after fees, positive expectancy over full dataset. |
| 2 | Paper trading | Live bot skeleton — CCXT WebSocket feed, signal detection, order simulation, full decision logging with reasoning. @ig88 first draft. No real capital. |
| 3 | LLM filter integration | Add news sentiment layer (LFM2.5 1.2B). Measure filter impact on backtest results. Cut if no measurable improvement. Add VL chart analysis as optional signal. @coord routing basic implementation. |
| 4 | Live trading — minimum size | Real positions, minimum contract size. Real fees, real fills, real slippage. Compare to paper results. Diagnose divergence before adding capital. First real P&L. |

### 7.1 Success Criteria — End of Week 4

- Live results within reasonable tolerance of paper trading results
- Fee drag accounted for and strategy remains positive expectancy
- No single trade exceeds 2% account drawdown
- Bot operates unattended for 24+ hours without intervention
- Trade log complete and auditable

### 7.2 Pre-Mortem

Most likely failure modes and mitigations:

- **Backtest overfitting:** Historical data captured only one market regime. Mitigation: test across minimum 6 months, require positive expectancy in each sub-period.
- **Fee drag underestimated:** Live fees exceed paper trading assumptions. Mitigation: model fees conservatively (full taker both sides) in backtest.
- **Slippage divergence:** Live fills worse than backtest prices. Mitigation: add 0.05% slippage assumption to backtest, compare to live fills in Week 4.
- **Signal decay:** Edge present in historical data but diminished in live market. Mitigation: treat Week 4 as validation, not deployment. Stop and diagnose before adding capital if live underperforms paper by >30%.

---

## 8. Canadian Tax Considerations

All trading activity subject to Canadian tax law. Key points:

- Crypto trading income in Canada is generally treated as **business income** (fully taxable) rather than capital gains (50% inclusion rate) when trading is frequent and systematic — which a bot by definition is.
- All trades must be logged with: date, asset, quantity, CAD value at time of trade, fees paid. SQLite trade log serves this function.
- Consult a Canadian tax professional before scaling capital. CRA has increased scrutiny of crypto trading income.
- Bot trading income reported in CAD at exchange rate on date of each trade.
- Trading losses are deductible against trading income in the same year.

> **Note:** This is not tax advice. Engage a qualified Canadian accountant before filing.

---

## 9. Future Considerations

### 9.1 Hardware Upgrade Path

- M2 MacBook Pro (current) → offload @kelk permanently once Mac Studio acquired
- M4 Max Mac Studio: unlocks RDMA over Thunderbolt 5, tensor parallelism, 64GB+ memory for larger models. Target when capital allows.
- LFM2 8B and 24B: Liquid's larger models become viable @nan candidates on memory upgrade

### 9.2 Strategy Expansion

- Additional pairs beyond BTC/USDT once BTC strategy validated
- Prediction markets (Polymarket, Kalshi): genuine inefficiencies, thin liquidity, position size limited — research phase only until BTC bot profitable
- Dexscreener new token launch patterns: high-risk, high-reward, requires separate risk allocation

### 9.3 Agent Expansion (@?)

- Modular design principle: new agents default to 1B–9B unless role explicitly justifies more
- Candidate roles: dedicated RAG/research agent, social media monitoring agent, portfolio analytics agent
- LFM2.5 3B (anticipated): natural @kelk upgrade when released
- Liquid LFM2 8B: candidate for @nan upgrade, staying within Liquid architecture family

---

*Factory — Boot Industries — Living document — update as architecture evolves*
