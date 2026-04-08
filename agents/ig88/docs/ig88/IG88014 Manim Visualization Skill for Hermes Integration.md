---
prefix: IG88014
title: "Manim Visualization Skill for Hermes Integration"
status: exploratory
created: 2026-04-07
updated: 2026-04-07
author: Chris + Claude (Opus 4.6)
depends_on: IG88012, IG88013
---

# IG88014 Manim Visualization Skill for Hermes Integration

## Purpose

Explore integrating the Hermes Manim video skill into IG-88's trading system to produce animated visualizations of backtesting results, paper trading performance, and market analysis. This replaces the previously considered Grafana dashboard approach with a Hermes-native solution.

---

## 1. What Is Manim?

Manim (Mathematical Animation Engine) is the framework behind 3Blue1Brown's explanatory math videos. It generates programmatic animations from Python code — precise, reproducible, and scriptable.

**Hermes ships a built-in Manim skill** at `skills/creative/manim-video` [1] that wraps the full production pipeline: creative planning → Python code generation → rendering → scene stitching → iterative refinement. IG-88 already runs on Hermes runtime, making this a skill registration away from operational.

---

## 2. Why Manim Over Grafana

| Dimension | Grafana | Manim |
|-----------|---------|-------|
| **Runtime** | Separate service (InfluxDB/Prometheus + Grafana) | Native to IG-88's existing Hermes runtime |
| **Data model** | Requires time-series database ingestion | Reads directly from Python (numpy, JSONL, dataclasses) |
| **Output** | Static dashboards (web UI) | MP4 videos, GIFs, individual frames |
| **Narrative** | Shows what happened | Shows what happened *and explains why* |
| **Distribution** | Must access Grafana web UI | Posts directly to Matrix as video/image attachment |
| **Maintenance** | Another service to keep alive (ports, auth, data retention) | Zero infrastructure — runs in IG-88's Python environment |
| **Expressiveness** | Line charts, bar charts, gauges | Arbitrary 2D/3D animation, mathematical notation, camera movement |

**Key insight:** Grafana answers "is the system healthy right now?" Manim answers "here's what the backtest found and why you should care." Both have value, but Manim is the higher-leverage investment for a system that needs to *explain* its trading decisions to Chris.

Grafana remains useful for real-time monitoring (system health, position tracking) if needed later. This is not either/or.

---

## 3. Use Cases for IG-88

### 3.1 Backtest Result Presentations

**Equity curve animation with regime overlay:**
- X-axis: time. Y-axis: cumulative P&L.
- Background color shifts between green (RISK_ON), yellow (NEUTRAL), red (RISK_OFF)
- Trade entries appear as dots; winners in green, losers in red
- Camera tracks the equity curve as it builds
- Final frame: BacktestStats summary table

**Walk-forward validation:**
- Split screen: train period (left) vs test period (right)
- Strategy parameters learned on train data; applied on test
- Visual comparison of in-sample vs out-of-sample performance

### 3.2 Ichimoku Cloud Analysis

Chris's preferred indicator, and Manim's strongest match — the cloud is inherently visual.

**Animated Ichimoku walkthrough:**
- Price action enters from left, cloud forms ahead (Senkou displaced 26 periods forward)
- Tenkan/Kijun crossovers highlighted with annotations
- Cloud color transitions (bullish green / bearish red)
- Chikou span confirmation signals marked
- Composite score (-5 to +5) displayed as running gauge
- Camera zooms into key decision points

### 3.3 Brier Score Calibration

**Calibration curve animation:**
- X-axis: predicted probability bins (0-10%, 10-20%, ..., 90-100%)
- Y-axis: actual resolution rate
- Perfect calibration shown as diagonal reference line
- IG-88's calibration dots animate into position as trades resolve
- Running Brier score counter in corner
- Deviation from diagonal highlighted (overconfident / underconfident regions)

### 3.4 Kelly Position Sizing

**Position size evolution:**
- Animate how Kelly fraction changes as win rate and R:R evolve
- Show the relationship: f = (bp - q) / b
- Overlay quarter-Kelly vs half-Kelly vs full Kelly risk profiles
- Monte Carlo fan chart showing potential equity paths at each Kelly fraction

### 3.5 Multi-Venue Portfolio

**Parrondo's Paradox demonstration:**
- Three venue equity curves (Polymarket, Kraken, Jupiter) shown individually
- Each may show flat or negative expectancy in isolation
- Combined portfolio curve shown — potentially positive due to anti-correlation
- Shannon's Demon rebalancing premium visualized
- Correlation matrix heatmap animates as data accumulates

### 3.6 Daily/Weekly Reports

**Animated daily summary for Matrix:**
- Today's trades scroll in with P&L color coding
- Regime state indicator
- Open positions with unrealized P&L
- Running statistics (win rate, expectancy, Sharpe)
- 5-10 second GIF — compact enough for Matrix

---

## 4. Implementation Plan

### Phase 1: Prerequisites (Boot, ~30 minutes)

Install Manim CE and dependencies on Whitebox:

```bash
# Manim Community Edition
pip install manim

# LaTeX (for mathematical notation)
brew install --cask mactex-no-gui
# or: brew install basictex

# ffmpeg (for video encoding)
brew install ffmpeg

# Verify
python3 -c "import manim; print(manim.__version__)"
manim --version
```

### Phase 2: Skill Registration (Boot, ~15 minutes)

Option A — Use Hermes built-in skill:

```bash
# If IG-88's Hermes profile supports skill registration
hermes skill install creative/manim-video
```

Option B — Standalone integration (if Hermes skill system isn't wired):

Create a thin Python module at `src/viz/manim_charts.py` that imports from both Manim CE and IG-88's trading modules. IG-88 calls it via Bash tool:

```bash
python3 ~/dev/factory/agents/ig88/src/viz/render_backtest.py \
  --venue kraken_spot \
  --strategy event_driven \
  --output ~/dev/factory/agents/ig88/renders/backtest_kraken_spot.mp4
```

### Phase 3: Template Scenes (IG-88, ~2-4 hours)

Build reusable Manim scene templates:

| Scene | Input | Output |
|-------|-------|--------|
| `EquityCurveScene` | BacktestStats + trade list | Animated equity curve with regime overlay |
| `IchimokuScene` | OHLCV + IchimokuCloud | Price through cloud with crossover annotations |
| `CalibrationScene` | Brier scores + probability bins | Calibration curve animation |
| `KellyScene` | Win rate, R:R sequence | Position sizing evolution |
| `DailySummaryScene` | DailySummary dataclass | Compact GIF for Matrix |

Each scene reads from existing IG-88 dataclasses — no new data pipeline needed.

### Phase 4: Integration with Paper Trading Loop

After each daily summary, IG-88 optionally renders a visualization:

```python
# In scan-loop.py or paper_trader.py
if daily_summary.trades_closed_today > 0:
    render_daily_animation(daily_summary, output_path)
    # Post to Matrix as video attachment
```

---

## 5. Data Flow

```
BacktestEngine.compute_stats()
    → BacktestStats
        → EquityCurveScene.construct()
            → manim render
                → MP4/GIF
                    → Matrix attachment (IG-88 Training room)

PaperTrader.daily_summary()
    → DailySummary
        → DailySummaryScene.construct()
            → manim render
                → GIF
                    → Matrix attachment
```

All inputs are existing dataclasses from IG88012. No new data models required.

---

## 6. Resource Considerations

| Resource | Impact | Mitigation |
|----------|--------|------------|
| Render time | 10-60s per scene (Manim is CPU-bound) | Render asynchronously; don't block the scan loop |
| Disk space | ~5-50MB per video | Rotate renders older than 7 days |
| LaTeX | ~2GB install (MacTeX) | Use basictex (~100MB) if full MacTeX is too large |
| RAM | Manim uses ~500MB during render | Well within Whitebox's 32GB |
| Matrix upload | Videos up to 100MB supported | Keep renders under 30s / 720p for reasonable file size |

---

## 7. Comparison to Alternatives

| Tool | Pros | Cons | Verdict |
|------|------|------|---------|
| **Manim** | Hermes-native, narrative, beautiful, scriptable | Render time, LaTeX dependency | **Primary** — for explanatory content |
| **Grafana** | Real-time, standard tooling | Separate infra, static charts, no narrative | **Deferred** — add only if real-time monitoring needed |
| **matplotlib** | Already in pyproject.toml, fast | Static images, no animation | **Supplementary** — quick one-off charts |
| **Plotly** | Interactive, HTML output | External dependency, not Hermes-native | **Skip** — no clear advantage over Manim |
| **D3.js / Observable** | Web-native, interactive | Would need a web frontend | **Skip** — overengineered for this use case |

---

## 8. Open Questions

| Question | Impact | Who Decides |
|----------|--------|-------------|
| Hermes skill registration vs standalone module? | Determines integration depth | Boot (check Hermes v0.7 skill API) |
| LaTeX: full MacTeX or basictex? | 2GB vs 100MB install | Chris (disk space preference) |
| Default render quality: 720p or 1080p? | File size vs clarity | Chris |
| Render frequency: every daily summary or on-demand? | CPU budget | IG-88 (self-tune based on value) |
| Store rendered videos in git or gitignore? | Repo size | Boot (likely gitignore + retain 7 days) |

---

## 9. Decision Gate

**When to proceed:** After IG-88's first Hermes session produces real backtest data. Animated visualizations of synthetic random data have no value — the first real Polymarket paper trading results are the right trigger.

**Who proceeds:** Boot installs prerequisites (Phase 1-2). IG-88 builds scene templates (Phase 3) and integrates with its paper trading loop (Phase 4).

**Estimated effort:** 4-6 hours total across Boot and IG-88.

---

## References

[1] NousResearch, "Hermes Agent — Manim Video Skill," GitHub, 2026. Available: https://github.com/NousResearch/hermes-agent/tree/main/skills/creative/manim-video

[2] Manim Community, "Manim Community Edition," GitHub, 2026. Available: https://github.com/ManimCommunity/manim

[3] NousResearch, "Hermes Agent v0.7.0 Release Notes," GitHub, 2026. Available: https://github.com/NousResearch/hermes-agent/releases/tag/v2026.4.3

[4] IG88012, "Backtesting and Paper Trading Systems," 2026-04-07.

[5] IG88013, "Sprint Report — Backtesting and Paper Trading Build," 2026-04-07.
