---
prefix: IG88031
title: "Manim Visualization System"
status: active
created: 2026-04-12
author: IG-88
depends_on: IG88014
---

# IG88031 Manim Visualization System

## Summary

Built and deployed Manim 0.20.1 visualization system for IG-88 trading analytics. Four scene types rendered and verified working with sample data. System generates animated MP4/GIF videos for Matrix posting.

## Installation

- **Manim 0.20.1** installed via `brew install manim` (Chris, 2026-04-12)
- Uses isolated Python 3.14 venv at `/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/`
- No LaTeX dependency required (text rendering uses system fonts)
- No pandas dependency (scenes are self-contained with numpy)

## Scene Inventory

| Scene | File | Purpose | Output |
|-------|------|---------|--------|
| EquityCurveScene | `src/viz/equity_curve.py` | Animated equity curve with regime overlay, trade markers, stats table | MP4 166KB |
| IchimokuCloudScene | `src/viz/ichimoku_cloud.py` | Price through Ichimoku cloud with TK crossovers, Chikou span, score gauge | MP4 173KB |
| BacktestComparisonScene | `src/viz/backtest_comparison.py` | Split train vs test walk-forward validation with overfit warning | MP4 167KB |
| DailySummaryScene | `src/viz/daily_summary.py` | Compact GIF for Matrix: trades, positions, stats, regime indicator | MP4 92KB |

## Usage

### Direct Manim CLI
```bash
/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/manim src/viz/equity_curve.py EquityCurveScene -pql
/opt/homebrew/Cellar/manim/0.20.1/libexec/bin/manim src/viz/ichimoku_cloud.py IchimokuCloudScene -pqh
```

### Render Helper Script
```bash
python3 scripts/render_viz.py equity           # Equity curve (480p)
python3 scripts/render_viz.py ichimoku -q h     # Ichimoku (1080p)
python3 scripts/render_viz.py daily -f gif      # Daily summary GIF
```

### Quality Flags
| Flag | Resolution | FPS | Use Case |
|------|------------|-----|----------|
| `-ql` | 480p | 15 | Preview, quick tests |
| `-qm` | 720p | 30 | Standard delivery |
| `-qh` | 1080p | 60 | High quality, presentations |
| `-qk` | 4K | 60 | Archival |

## Key Design Decisions

1. **No pandas dependency** — Brew Manim uses isolated Python 3.14. Scenes use numpy only.
2. **No LaTeX** — Text rendering uses Manim's built-in Text() with system fonts. Avoids ~2GB MacTeX install.
3. **Sample data generators** — Each scene includes its own `generate_*()` function for testing. Wire to real data when integrating with backtest engine.
4. **Dark background** — `#0d1117` for DailySummaryScene (matches Matrix dark theme).

## Rendered Output Location

```
renders/videos/<scene_name>/480p15/<SceneName>.mp4
renders/videos/<scene_name>/720p30/<SceneName>.mp4
renders/videos/<scene_name>/1080p60/<SceneName>.mp4
```

Renders are gitignored (binary files). Partial movie files auto-cleaned by Manim.

## Next Steps

1. **Wire to real backtest data** — Connect EquityCurveScene and BacktestComparisonScene to `backtest_engine.py` output JSON
2. **Integrate with scan-loop** — Auto-render DailySummaryScene after paper trading closes
3. **Matrix posting** — Send MP4/GIF to IG-88 Training room after render
4. **Ichimoku real data** — Feed OHLCV + Ichimoku scores from `indicators.py` to IchimokuCloudScene

## References

- IG88014 — Manim Visualization Skill for Hermes Integration (original plan)
- Manim 0.20.1 docs: https://docs.manim.community
