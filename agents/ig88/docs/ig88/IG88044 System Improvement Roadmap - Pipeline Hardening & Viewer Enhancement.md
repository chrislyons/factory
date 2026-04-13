# IG88044: System Improvement Roadmap

**Date:** 2026-04-13
**Scope:** Paper Trading Pipeline, Data Pipeline, Viewer Enhancement, New Visualizations
**Excluded:** Strategy validation (deferred per Chris)

---

## Executive Summary

The IG-88 trading system has validated strategies (Mean Reversion, H3-A/B) but faces three blockers preventing graduation to live trading:

1. **Paper trading has generated 0 signals** - scanner runs but no entries fire
2. **OHLCV data is stale** - 21+ hours old, no refresh mechanism
3. **Visualizations lack utility** - static, not connected to real state

This roadmap addresses all three in four sequential phases.

---

## Phase 1: Paper Trading Pipeline Verification

**Goal:** Verify scanner finds entries on real data, debug why 0 signals so far.

### Root Cause Analysis (Pre-work)

The scanner has run 120+ cycles with 0 signals. Possible causes:
- Data too old (last bar 2026-04-13 00:00, now 2026-04-13 21:00)
- Entry thresholds too strict (RSI < 18-25, BB < 0.05-0.20)
- Market has been trending (MR strategy fails in trends)
- Friction filter blocking borderline signals

### Tasks

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| 1.1 Run manual scan with verbose output | Subagent A | 2h | Diagnostic log showing indicator values for each pair |
| 1.2 Check if market is in MR-friendly regime | Subagent A | 1h | ATR regime classification for all 12 pairs |
| 1.3 Relax thresholds temporarily and re-test | Subagent A | 2h | Document which thresholds are binding |
| 1.4 Run scanner against historical period that DID produce signals in backtest | Subagent A | 3h | Verify scanner logic matches backtest logic |
| 1.5 Implement diagnostic mode (log top candidates even if rejected) | Subagent A | 2h | `--verbose` flag for paper_scan.py |

### Success Criteria
- [ ] Scanner produces at least 1 signal when run against backtest-validated period
- [ ] Root cause of 0 live signals identified and documented
- [ ] Threshold adjustments (if needed) validated against backtest

### Risk
- Market may genuinely be in trend regime (MR unfriendly) - no action needed, just wait
- If scanner logic differs from backtest,修复 required

---

## Phase 2: Data Pipeline Hardening

**Goal:** Ensure OHLCV data is fresh, complete, and automatically updated.

### Current State
- 40 pairs of 240m (4h) data in parquet format
- Data last updated: 2026-04-13 00:00 UTC (21h stale)
- No automatic refresh mechanism
- No freshness validation

### Tasks

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| 2.1 Create data freshness checker | Subagent B | 2h | `scripts/check_data_freshness.py` - reports age of all parquet files |
| 2.2 Create OHLCV fetcher for Binance public API | Subagent B | 3h | `scripts/fetch_ohlcv.py` - fetches latest candles for all pairs |
| 2.3 Create data update cron job | Subagent B | 1h | Cron at :15 past each 4h (00:15, 04:15, etc.) |
| 2.4 Add data validation (OHLC sanity, gaps, duplicates) | Subagent B | 2h | `scripts/validate_parquet.py` |
| 2.5 Create in-memory aggregation from 1m to 4h | Subagent B | 2h | Function in `data_loader.py` - fallback when 4h parquet stale |
| 2.6 Wire data freshness into scanner (warn if >4h old) | Subagent B | 1h | Warning in scan output |

### Data Flow (Target)
```
Binance API (1m candles)
    ↓ fetch_ohlcv.py (cron :15)
Parquet cache (data/binance_*_1m.parquet)
    ↓ In-memory resample
4h OHLCV (for scanner/backtest)
```

### Success Criteria
- [ ] All parquet files updated within 4 hours of current time
- [ ] Scanner warns if data >4 hours old
- [ ] Missing data handled gracefully (not silent failure)

---

## Phase 3: New Visualization Scenes

**Goal:** Add high-value visualizations that inform trading decisions.

### Scene 1: Regime Detection

**Purpose:** Show current market regime (trending vs mean-reverting) per pair.

**Metrics displayed:**
- ATR percentage (current vs 20-day average)
- ADX value (trend strength)
- Regime classification (LOW_VOL / NORMAL / HIGH_VOL / TRENDING)
- Recommended action per regime (MR trades / wait / reduce size)

**Layout:** 25/75 (left: regime stats table, right: ATR time series with regime bands)

### Scene 2: Correlation Matrix

**Purpose:** Ensure portfolio diversification, detect when pairs move together.

**Metrics displayed:**
- 12x12 correlation matrix (30-day rolling)
- Highlight pairs with correlation > 0.7
- Effective diversification score
- Cluster identification

**Layout:** Full-width heatmap with cluster annotations

### Scene 3: Walk-Forward Decay

**Purpose:** Visualize if strategy edge is decaying over time.

**Metrics displayed:**
- PF by training window (rolling 50 trades)
- OOS/IS ratio over time
- Degradation slope
- Alert when ratio < 0.6

**Layout:** 25/75 (left: decay stats, right: time series of PF with train/test overlay)

### Scene 4: Performance Attribution

**Purpose:** Identify which pairs and market conditions drive PnL.

**Metrics displayed:**
- PnL by pair (bar chart)
- PnL by regime (stacked bar)
- PnL by day of week (seasonality)
- Win rate by tier (STRONG/MEDIUM/WEAK)

**Layout:** 2x2 grid of mini-charts

### Tasks

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| 3.1 Implement RegimeDetectionScene | Subagent C | 4h | `src/viz/regime_detection.py` |
| 3.2 Implement CorrelationMatrixScene | Subagent C | 4h | `src/viz/correlation_matrix.py` |
| 3.3 Implement WalkForwardDecayScene | Subagent C | 4h | `src/viz/walkforward_decay.py` |
| 3.4 Implement PerformanceAttributionScene | Subagent C | 3h | `src/viz/performance_attribution.py` |
| 3.5 Update render_viz.py with new scenes | Subagent C | 1h | Add all 4 scenes to SCENES dict |
| 3.6 Generate initial renders | Subagent C | 2h | GIFs for viewer |

### Success Criteria
- [ ] All 4 scenes render without errors
- [ ] Scenes load real data from parquet/JSON files
- [ ] GIFs generated and viewable

---

## Phase 4: Viewer Enhancement

**Goal:** Make viewer.html production-quality for daily monitoring.

### Features

| Feature | Priority | Description |
|---------|----------|-------------|
| Auto-refresh | HIGH | Poll for new renders every 60s, animate card swap |
| Timestamps | HIGH | Show "Rendered X minutes ago" per card |
| Click-to-expand | MEDIUM | Click card to see full 1920x1080 in modal |
| Keyboard nav | MEDIUM | Arrow keys to move between cards, Enter to expand |
| Status indicator | HIGH | Green dot if data <4h old, red if stale |
| Card descriptions | LOW | Expandable text section with strategy details |
| Mobile layout | LOW | Single column on narrow screens |

### Tasks

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| 4.1 Add auto-refresh JS | Subagent D | 2h | Fetch manifest.json, animate card updates |
| 4.2 Add render timestamps | Subagent D | 1h | Read file mtime, display relative time |
| 4.3 Implement click-to-expand modal | Subagent D | 2h | Full-res GIF in centered overlay |
| 4.4 Add keyboard navigation | Subagent D | 1h | Arrow keys + Enter + Escape |
| 4.5 Add data freshness indicator | Subagent D | 1h | Read data_freshness.json, show status dot |
| 4.6 Create manifest.json generator | Subagent D | 1h | Script that scans renders/, outputs manifest |
| 4.7 Update viewer.html CSS for modal | Subagent D | 1h | Modal styles, backdrop, animations |

### Success Criteria
- [ ] Viewer auto-updates when new renders appear
- [ ] Clicking a card shows full-resolution GIF
- [ ] Data freshness visible at a glance
- [ ] Works on mobile (single column)

---

## Delegation Plan

### Subagent A: Paper Trading Debugger
**Skills:** Backtesting, indicator calculation, scanner logic
**Output:** Diagnostic report + fixed scanner (if needed)

### Subagent B: Data Engineer
**Skills:** Binance API, parquet, cron jobs
**Output:** Working data pipeline with auto-refresh

### Subagent C: Visualization Developer
**Skills:** Manim, data visualization, theming
**Output:** 4 new scenes, all rendering correctly

### Subagent D: Frontend Developer
**Skills:** HTML/CSS/JS, UX
**Output:** Enhanced viewer.html with all features

---

## Execution Order

```
Phase 1 (Paper Trading) ──→ Phase 2 (Data Pipeline) ──→ Phase 3 (Viz) ──→ Phase 4 (Viewer)
     │                            │                           │                   │
     │                            │                           │                   │
     ▼                            ▼                           ▼                   ▼
 Subagent A                   Subagent B                  Subagent C          Subagent D
   2 days                       2 days                      3 days              2 days
```

**Total estimated duration:** 9 days (can overlap Phases 3-4)

---

## Dependencies

| Phase | Depends On | Blocker |
|-------|-----------|---------|
| Phase 1 | Nothing | None |
| Phase 2 | Phase 1 (know what data format scanner needs) | None |
| Phase 3 | Phase 2 (fresh data for real renders) | None (scenes use fallback) |
| Phase 4 | Phase 3 (new scenes to display) | None (viewer works without) |

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Market in permanent MR-unfriendly regime | No signals generated | Implement trend-following as secondary strategy |
| Binance API rate limits | Data refresh fails | Implement retry with exponential backoff |
| Parquet corruption | Scanner fails silently | Add validation step to data pipeline |
| Manim render failures | No visualizations | Ensure fallback synthetic data works |
| Viewer JS errors | Blank page | Add error boundaries, fallback to static list |

---

## Appendix: File Manifest

### New Files to Create
```
scripts/check_data_freshness.py
scripts/fetch_ohlcv.py
scripts/validate_parquet.py
src/viz/regime_detection.py
src/viz/correlation_matrix.py
src/viz/walkforward_decay.py
src/viz/performance_attribution.py
state/data_freshness.json  (generated)
renders/manifest.json  (generated)
```

### Files to Modify
```
scripts/paper_scan.py  (add --verbose flag)
src/viz/data_loader.py  (add freshness check, aggregation)
scripts/render_viz.py  (add new scenes)
renders/viewer.html  (all enhancements)
```

---

**Next Action:** Launch Subagent A to begin Phase 1 (Paper Trading Debugger).
