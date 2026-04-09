#!/usr/bin/env python3
"""IG-88 Scan Loop — autonomous trading cycle bootstrap.

This script is called by IG-88's Hermes session to run a single scan cycle.
It checks regime, scans venues for opportunities, evaluates candidates,
and logs results. At the end, it writes the next timer to continue the loop.

Usage (from Hermes session or coordinator timer):
    python3 ~/dev/factory/agents/ig88/scripts/scan-loop.py

The script outputs a structured JSON report that IG-88 can post to Matrix.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add ig88 root to path
IG88_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IG88_ROOT))

from src.trading.config import load_config
from src.quant.regime import assess_regime, regime_allows_venue, RegimeState, MarketDataCollector


def run_scan_cycle() -> dict:
    """Execute a single scan cycle and return results."""
    cfg = load_config()
    now = datetime.now(timezone.utc)

    results = {
        "timestamp": now.isoformat(),
        "cycle_type": "scan",
        "regime": None,
        "venues": {},
        "actions": [],
        "next_scan_minutes": 5,
    }

    # Step 1: Regime assessment
    # In production, these values come from live API calls.
    # For now, output placeholder indicating what data sources are needed.
    regime_inputs_needed = {
        "btc_trend": "7-day BTC price change % (from CoinGecko or Kraken API)",
        "total_mcap_trend": "7-day total crypto market cap change % (from CoinGecko)",
        "fear_greed_index": "Current Fear & Greed Index (from api.alternative.me/fng/)",
        "funding_rates": "Avg perp funding rate across major pairs (from venue APIs)",
        "stablecoin_flows": "Net USDT/USDC mint/burn 7-day in millions (from DeFiLlama)",
        "btc_dominance_delta": "BTC dominance change 7-day in pp (from CoinGecko)",
        "volatility_regime": "GARCH vol percentile (from internal model)",
    }

    # Live regime assessment
    collector = MarketDataCollector()
    live_inputs = collector.get_regime_inputs()
    regime = assess_regime(
        inputs=live_inputs,
        weights=cfg.regime.weights,
        risk_off_max=cfg.regime.risk_off_max,
        neutral_max=cfg.regime.neutral_max,
    )

    results["regime"] = regime.to_dict()
    results["regime_data_sources"] = regime_inputs_needed

    # Step 2: Per-venue scan
    for venue_name, venue_cfg in cfg.enabled_venues().items():
        venue_result = {
            "enabled": True,
            "paper_mode": venue_cfg.paper_mode,
            "regime_allows": regime_allows_venue(regime, venue_name),
            "pairs": venue_cfg.pairs,
            "strategies": venue_cfg.strategies,
            "status": "ready" if regime_allows_venue(regime, venue_name) else "regime_blocked",
        }

        if venue_name == "polymarket":
            venue_result["scan_note"] = (
                f"Scan {venue_cfg.extra.get('max_markets_per_scan', 50)} markets, "
                f"edge threshold {venue_cfg.edge_threshold}, "
                f"confidence min {venue_cfg.confidence_min}"
            )
        elif venue_name == "kraken_spot":
            venue_result["scan_note"] = (
                f"{len(venue_cfg.pairs)} pairs loaded, "
                f"maker {venue_cfg.fees.maker_pct}% / taker {venue_cfg.fees.taker_pct}%"
            )
        elif venue_name == "jupiter_perps":
            venue_result["scan_note"] = (
                f"SOL-PERP only, {venue_cfg.leverage.get('default', 3)}x default leverage, "
                f"TP/SL required"
            )
        elif venue_name == "solana_dex":
            venue_result["scan_note"] = (
                f"Phase: {venue_cfg.phase}, "
                f"min liquidity ${venue_cfg.liquidity_min_usd:,.0f}"
            )

        results["venues"][venue_name] = venue_result

    # Step 3: Actions summary
    if regime.state == RegimeState.RISK_OFF:
        results["actions"].append("REGIME_HALT: No new positions on regime-gated venues")
        results["actions"].append("Polymarket scanning continues (regime-independent)")
    elif regime.state == RegimeState.NEUTRAL:
        results["actions"].append("REGIME_CAUTION: Reduced position sizing on regime-gated venues")
        results["actions"].append("Polymarket scanning continues")
    else:
        results["actions"].append("REGIME_GREEN: All venues open for scanning")

    if regime.confidence < 0.5:
        results["actions"].append(
            f"LOW_CONFIDENCE: Only {regime.confidence:.0%} of regime signals available. "
            "Connect data sources for accurate regime detection."
        )

    return results


def write_next_timer(scan_interval_minutes: int = 5) -> None:
    """Write the next scan cycle timer for the coordinator."""
    timer_dir = IG88_ROOT / "timers"
    timer_dir.mkdir(exist_ok=True)

    now_ms = int(time.time() * 1000)
    due_ms = now_ms + (scan_interval_minutes * 60 * 1000)

    timer = {
        "timer_id": f"ig88_scan_{due_ms}",
        "agent": "ig88",
        "due_at": due_ms,
        "message": (
            "Run scan cycle: "
            "python3 ~/dev/factory/agents/ig88/scripts/scan-loop.py"
        ),
        "room": "!zRnHwXlrVdCfdNbNOx:matrix.org",
    }

    timer_path = timer_dir / f"ig88_scan_{due_ms}.json"
    with open(timer_path, "w") as f:
        json.dump(timer, f, indent=2)


if __name__ == "__main__":
    results = run_scan_cycle()
    print(json.dumps(results, indent=2))

    # Write next timer (self-perpetuating loop)
    interval = results.get("next_scan_minutes", 5)
    write_next_timer(interval)
    print(f"\nNext scan in {interval} minutes.", file=sys.stderr)
