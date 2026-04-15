#!/usr/bin/env python3
"""IG-88 Volatility Monitor — regime state updater.

Fetches 15m candles for monitored pairs, calculates volatility metrics,
detects flash crashes / correlated moves / volume spikes, and writes
the combined regime assessment to data/current_regime.json.

Designed to be called by cron or the scan loop. Uses only stdlib for
network calls (same pattern as regime.py).
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IG88_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IG88_ROOT))

from src.quant.regime import (
    assess_regime,
    RegimeAssessment,
    RegimeState,
    MarketDataCollector,
)
from src.trading.config import load_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pairs to monitor for volatility (Binance symbols)
VOLATILITY_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT",
    "DOGEUSDT", "AVAXUSDT", "INJUSDT", "ARBUSDT", "FILUSDT",
]

# Thresholds
FLASH_CRASH_PCT = -5.0          # 15m candle drops >5%
VOLUME_SPIKE_MULT = 3.0         # Volume >3x recent average
CORRELATED_MOVE_PCT = 3.0       # >70% of pairs move >3% same direction
HIGH_VOL_PERCENTILE = 80        # ATR percentile considered "high vol"

DATA_DIR = IG88_ROOT / "data"
OUTPUT_PATH = DATA_DIR / "current_regime.json"


# ---------------------------------------------------------------------------
# Binance public API (no auth needed)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> Any | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IG88/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  [WARN] fetch failed: {url[:80]}... — {e}", file=sys.stderr)
        return None


def fetch_klines(symbol: str, interval: str = "15m", limit: int = 96) -> list[dict] | None:
    """Fetch OHLCV candles from Binance public API.

    Returns list of dicts with keys: time, open, high, low, close, volume.
    96 x 15m candles = 24 hours of data.
    """
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )
    raw = _fetch_json(url)
    if not raw:
        return None

    candles = []
    for row in raw:
        candles.append({
            "time": row[0],           # open time ms
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return candles


# ---------------------------------------------------------------------------
# Volatility analysis
# ---------------------------------------------------------------------------

@dataclass
class PairVolatility:
    symbol: str
    last_price: float
    pct_change_15m: float        # Most recent candle % move
    pct_change_1h: float         # Last 4 candles cumulative
    pct_change_24h: float        # All 96 candles cumulative
    atr_14: float                # 14-period ATR (absolute)
    atr_pct: float               # ATR as % of price
    volume_ratio: float          # Last candle vol / 20-candle avg
    is_flash_crash: bool
    is_volume_spike: bool


def compute_atr(candles: list[dict], period: int = 14) -> float:
    """Average True Range over the last `period` candles."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # Use last `period` true ranges
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def analyze_pair(symbol: str, candles: list[dict]) -> PairVolatility | None:
    """Compute volatility metrics for a single pair."""
    if not candles or len(candles) < 20:
        return None

    last = candles[-1]
    prev_15m = candles[-2] if len(candles) >= 2 else last
    idx_1h = max(0, len(candles) - 4)
    idx_24h = 0

    pct_15m = ((last["close"] - prev_15m["close"]) / prev_15m["close"]) * 100 if prev_15m["close"] else 0
    pct_1h = ((last["close"] - candles[idx_1h]["close"]) / candles[idx_1h]["close"]) * 100 if candles[idx_1h]["close"] else 0
    pct_24h = ((last["close"] - candles[idx_24h]["close"]) / candles[idx_24h]["close"]) * 100 if candles[idx_24h]["close"] else 0

    atr = compute_atr(candles, 14)
    atr_pct = (atr / last["close"]) * 100 if last["close"] else 0

    # Volume ratio: last candle vs 20-candle average
    vol_candles = candles[-21:-1] if len(candles) >= 21 else candles[:-1]
    avg_vol = sum(c["volume"] for c in vol_candles) / len(vol_candles) if vol_candles else 1
    vol_ratio = last["volume"] / avg_vol if avg_vol > 0 else 1.0

    return PairVolatility(
        symbol=symbol,
        last_price=last["close"],
        pct_change_15m=round(pct_15m, 3),
        pct_change_1h=round(pct_1h, 3),
        pct_change_24h=round(pct_24h, 3),
        atr_14=round(atr, 6),
        atr_pct=round(atr_pct, 3),
        volume_ratio=round(vol_ratio, 2),
        is_flash_crash=pct_15m <= FLASH_CRASH_PCT,
        is_volume_spike=vol_ratio >= VOLUME_SPIKE_MULT,
    )


# ---------------------------------------------------------------------------
# Market-wide analysis
# ---------------------------------------------------------------------------

@dataclass
class MarketVolatilityState:
    flash_crashes: list[str]         # Symbols with flash crash
    volume_spikes: list[str]         # Symbols with volume spike
    correlated_dump: bool            # >70% of pairs down >3% in 1h
    correlated_pump: bool            # >70% of pairs up >3% in 1h
    avg_atr_pct: float               # Average ATR% across pairs
    max_atr_pct: float               # Highest single-pair ATR%
    volatility_regime: str           # LOW / NORMAL / ELEVATED / EXTREME
    fear_greed: int | None           # FGI if available


def assess_market_state(pairs: list[PairVolatility], fgi: int | None) -> MarketVolatilityState:
    """Aggregate pair-level metrics into a market-wide volatility assessment."""
    if not pairs:
        return MarketVolatilityState(
            flash_crashes=[], volume_spikes=[],
            correlated_dump=False, correlated_pump=False,
            avg_atr_pct=0, max_atr_pct=0,
            volatility_regime="NORMAL", fear_greed=fgi,
        )

    flash = [p.symbol for p in pairs if p.is_flash_crash]
    spikes = [p.symbol for p in pairs if p.is_volume_spike]

    # Correlated moves: 1h timeframe
    n = len(pairs)
    down_1h = sum(1 for p in pairs if p.pct_change_1h <= -CORRELATED_MOVE_PCT)
    up_1h = sum(1 for p in pairs if p.pct_change_1h >= CORRELATED_MOVE_PCT)
    corr_dump = (down_1h / n) >= 0.7
    corr_pump = (up_1h / n) >= 0.7

    atrs = [p.atr_pct for p in pairs]
    avg_atr = sum(atrs) / len(atrs)
    max_atr = max(atrs)

    # Classify volatility regime
    if len(flash) >= 2 or corr_dump or corr_pump:
        vol_regime = "EXTREME"
    elif len(flash) >= 1 or avg_atr > 3.0:
        vol_regime = "ELEVATED"
    elif avg_atr < 0.8:
        vol_regime = "LOW"
    else:
        vol_regime = "NORMAL"

    return MarketVolatilityState(
        flash_crashes=flash,
        volume_spikes=spikes,
        correlated_dump=corr_dump,
        correlated_pump=corr_pump,
        avg_atr_pct=round(avg_atr, 3),
        max_atr_pct=round(max_atr, 3),
        volatility_regime=vol_regime,
        fear_greed=fgi,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Volatility monitor starting...")

    # 1. Load config for regime weights
    cfg = load_config()

    # 2. Fetch regime macro inputs (FGI, BTC trend, market cap, etc.)
    collector = MarketDataCollector()
    live_inputs = collector.get_regime_inputs()
    fgi = int(live_inputs.get("fear_greed_index", 0)) or None

    # 3. Assess regime from macro signals
    regime = assess_regime(
        inputs=live_inputs,
        weights=cfg.regime.weights,
        risk_off_max=cfg.regime.risk_off_max,
        neutral_max=cfg.regime.neutral_max,
    )
    print(f"  Regime: {regime.state.value} (score={regime.score:.2f}, conf={regime.confidence:.0%})")

    # 4. Fetch 15m candles and compute per-pair volatility
    pair_results: list[PairVolatility] = []
    for sym in VOLATILITY_PAIRS:
        candles = fetch_klines(sym, "15m", 96)
        if candles:
            pv = analyze_pair(sym, candles)
            if pv:
                pair_results.append(pv)
                if pv.is_flash_crash or pv.is_volume_spike:
                    print(f"  ⚠ {sym}: 15m={pv.pct_change_15m:+.2f}% vol_ratio={pv.volume_ratio:.1f}x"
                          f"{' [FLASH CRASH]' if pv.is_flash_crash else ''}"
                          f"{' [VOL SPIKE]' if pv.is_volume_spike else ''}")
        else:
            print(f"  [SKIP] {sym}: no candle data")

    # 5. Assess market-wide volatility state
    vol_state = assess_market_state(pair_results, fgi)
    print(f"  Volatility: {vol_state.volatility_regime} (avg_ATR={vol_state.avg_atr_pct:.2f}%)")
    if vol_state.flash_crashes:
        print(f"  🚨 Flash crashes: {', '.join(vol_state.flash_crashes)}")
    if vol_state.correlated_dump:
        print(f"  🚨 CORRELATED DUMP detected across pairs")
    if vol_state.correlated_pump:
        print(f"  📈 Correlated pump detected across pairs")

    # 6. Build combined output
    # Determine circuit breaker: trip if EXTREME vol + RISK_OFF regime
    circuit_breaker = (
        vol_state.volatility_regime == "EXTREME"
        and regime.state == RegimeState.RISK_OFF
    )

    # Adjust regime score down if extreme vol (penalize high vol in scoring)
    vol_penalty = 0
    if vol_state.volatility_regime == "EXTREME":
        vol_penalty = 2.0
    elif vol_state.volatility_regime == "ELEVATED":
        vol_penalty = 1.0

    adjusted_score = max(0, regime.score - vol_penalty)
    if adjusted_score <= cfg.regime.risk_off_max:
        effective_state = RegimeState.RISK_OFF
    elif adjusted_score <= cfg.regime.neutral_max:
        effective_state = RegimeState.NEUTRAL
    else:
        effective_state = RegimeState.RISK_ON

    output = {
        "timestamp": now.isoformat(),
        "regime": {
            "state": regime.state.value,
            "score": round(regime.score, 2),
            "confidence": round(regime.confidence, 2),
            "signals": [s.name for s in regime.signals],
        },
        "effective_regime": {
            "state": effective_state.value,
            "score": round(adjusted_score, 2),
            "vol_penalty": vol_penalty,
            "note": "Regime adjusted for volatility" if vol_penalty > 0 else "No vol adjustment",
        },
        "volatility": {
            "regime": vol_state.volatility_regime,
            "avg_atr_pct": vol_state.avg_atr_pct,
            "max_atr_pct": vol_state.max_atr_pct,
            "flash_crashes": vol_state.flash_crashes,
            "volume_spikes": vol_state.volume_spikes,
            "correlated_dump": vol_state.correlated_dump,
            "correlated_pump": vol_state.correlated_pump,
            "fear_greed_index": vol_state.fear_greed,
        },
        "circuit_breaker": {
            "active": circuit_breaker,
            "reason": "EXTREME volatility + RISK_OFF regime" if circuit_breaker else None,
        },
        "pairs": [
            {
                "symbol": p.symbol,
                "price": p.last_price,
                "change_15m": p.pct_change_15m,
                "change_1h": p.pct_change_1h,
                "change_24h": p.pct_change_24h,
                "atr_pct": p.atr_pct,
                "vol_ratio": p.volume_ratio,
                "flags": (
                    (["FLASH_CRASH"] if p.is_flash_crash else [])
                    + (["VOL_SPIKE"] if p.is_volume_spike else [])
                ),
            }
            for p in pair_results
        ],
    }

    # 7. Write to disk
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Written to {OUTPUT_PATH}")

    # 8. Summary
    action = "HALT" if circuit_breaker else ("CAUTION" if effective_state != RegimeState.RISK_ON else "NORMAL")
    print(f"\n  ▸ Effective regime: {effective_state.value} ({action})")
    print(f"  ▸ Pairs analyzed: {len(pair_results)}/{len(VOLATILITY_PAIRS)}")
    print(f"  ▸ Alerts: {len(vol_state.flash_crashes)} flash crashes, {len(vol_state.volume_spikes)} vol spikes")

    return output


if __name__ == "__main__":
    result = main()
    print("\n" + json.dumps(result, indent=2))
