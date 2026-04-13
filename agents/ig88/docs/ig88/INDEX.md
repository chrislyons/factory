# IG88 Documentation Index

**Agent:** IG-88 | **PREFIX:** IG88 | **Updated:** 2026-04-12

---

## 📂 Research & Strategy
| Doc | Title | Status | Summary |
| :--- | :--- | :--- | :--- |
| IG88016 | First Real-Data Backtest Results | active | Initial backtest results and integration of regime detection |
| IG88017 | Multi-Indicator Convergence Strategy | active | Refinement of signal convergence and portfolio weighting |
| IG88018 | Full Indicator Research Portfolio | active | Comprehensive library of analyzed indicators |
| IG88019 | Indicator Research Loop - Orthogonality | active | Analysis of indicator independence and portfolio diversity |
| IG88024 | H3-A and H3-B Strategy Validation | active | Validation report for H3-series trend strategies |
| IG88026 | Combinatorial Strategy Analysis | active | Systematic search for optimal indicator primitives (Trend+Mom+Vol) |
| IG88027 | Strategy Hardening & Ablation Report | active | Stress tests for slippage, exit sensitivity, and asset distribution |
| IG88028 | Battle Testing & Infrastructure Hardening | active | Friction model validation, Jupiter removal, shared utilities, Assumptions & Risks |
| IG88029 | Dual Stream Research - Jupiter Perps & H3 Optimization | active | Jupiter Perps validated (H3-A/B), H3-C optimization failed, cross-asset mixed, 2h marginal |
| IG88030 | Profit Maximization Research - Exit and Indicator Optimization | active | Exit optimization (H3-A PF 4.820 with time5), indicator expansion, ATR tuning |

## ⚙️ Infrastructure & Setup
| Doc | Title | Status | Summary |
| :--- | :--- | :--- | :--- |
| IG88006 | Polymarket Venue Setup Guide | active | Wallet, CLI, and CLOB API setup for Polymarket |
| IG88007 | Kraken Venue Setup Guide | active | API, MCP configuration, and spot guardrails for Kraken |
| IG88008 | Jupiter Perps Venue Setup Guide | active | On-chain perps setup and SOL-PERP mandates |
| IG88012 | Backtesting & Paper Trading Systems | active | Architecture of backtest engines, paper trader, and regime detection |
| IG88025 | Live Execution Pipeline & Graduation | active | Pipeline for transition from shadow to live trading (30-signal target) |

## 🗺️ Planning & Governance
| Doc | Title | Status | Summary |
| :--- | :--- | :--- | :--- |
| IG88001 | Multi-Venue Trading Action Plan | active | Strategic thesis, risk guardrails, and implementation timeline |
| IG88002 | Senior Review of Action Plan | active | Critical gaps and revised risk parameters from senior review |
| IG88003 | Trading System Build Schedule | active | Sequenced build instructions and owner assignments |
| IG88010 | Post-Compaction Roadmap | active | Consolidated roadmap: Infisical migration and strategy work |
| IG88015 | Proof & Validation Phase Init | active | Initialization of the real-data validation phase |
| IG88020 | Proof & Validation Progress Report | active | Summary of validation phase outcomes |
| IG88021 | Strategy Refinement Sprint | active | Focus on exits, perps, and timeframe optimization |
| IG88022 | Portfolio Finalization | active | Signal independence and infrastructure hardening |

## 🧪 Evaluations & Experiments
| Doc | Title | Status | Summary |
| :--- | :--- | :--- | :--- |
| IG88004 | Cloud Model Eval Framework | active | Benchmark criteria for selecting frontier LLMs |
| IG88005 | Cloud Model Bake-Off Design | active | Methodology for financial reasoning task comparison |
| IG88011 | Cloud Model Bake-Off Results | active | Tier assignments for T1/T2/T3 models based on Brier scores |
| IG88013 | Sprint Report - Build | active | Inventory of built components (10 files, ~6.6k lines) |
| IG88014 | Manim Visualization Skill | exploratory | Animated visualization plan for backtest results |
| IG88014b | Indicator Expansion: Squeeze, MeanRev, Chandelier | active | New indicator primitives: Squeeze (orthogonal), MeanRev (redundant), Chandelier (inferior to ATR trailing). Regime gate validated for H3-A (PF 4.4→5.6). |

---

## 🛠️ Operational Notes
- **Graduation**: See `IG88025` for the current 30-signal shadow monitoring target.
- **Strategy Baseline**: Current optimal composition is `trend_above_cloud + mom_rsi_55` (see `IG88026` and `IG88027`).
- **Secrets**: All API keys must be retrieved via Infisical `ig88` identity.
- **Interpretor**: Use `/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3`.
