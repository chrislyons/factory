# IG88 Documentation Index

**Agent:** IG-88 | **PREFIX:** IG88 | **Updated:** 2026-04-05

---

## Active Documents

| Doc | Title | Status | Summary |
|---|---|---|---|
| IG88001 | Multi-Venue Trading Action Plan | active | Strategic thesis, venue strategies (Polymarket, Solana DEX, Kraken), position sizing, risk guardrails, and implementation timeline |
| IG88002 | Senior Review of Multi-Venue Trading Action Plan | active | Senior review of IG88001: critical gaps, revised risk parameters, venue substitution rationale |
| IG88003 | Trading System Build Schedule and Instructions | active | Operational schedule: sequenced, owner-assigned build instructions for all venues; cloud inference architecture decision; Infisical migration requirement |
| IG88004 | Cloud Model Evaluation Framework for Trading Tasks | active | Evaluation framework for selecting cloud inference models for trading tasks; benchmark criteria and routing decisions |
| IG88005 | Cloud Model Bake-Off Design and Hermes Migration Plan | active | Bake-off methodology for comparing frontier models on financial reasoning tasks; Hermes migration planning |
| IG88006 | Polymarket Venue Setup Guide | active | Wallet setup, CLI installation (supply chain safe), CLOB API access, fee structure, paper trading constraints, key CLI commands |
| IG88007 | Kraken Venue Setup Guide | active | Account setup, API key generation, CLI installation (supply chain safe), MCP configuration, fee structure, spot strategy guardrails, Ontario regulatory status |

---

## Agent Notes

- IG88003 is the master operational schedule — all venue work references it for blockers and decision registry
- Decision D7 (Infisical migration) blocks graduation to live trading on all venues
- Futures trading on Kraken requires Ontario access verification before any non-paper work; see IG88007 §Kraken Futures
- IG88006 and IG88007 are the authoritative venue setup references for Boot's MCP build work
