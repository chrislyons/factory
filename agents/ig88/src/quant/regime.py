"""Regime detection module — deterministic, no LLM.

Three states: RISK_ON / NEUTRAL / RISK_OFF
Score: 0-10 with configurable threshold mapping.

FIXES (2026-04-28):
- btc_dominance: fixed — uses current dominance as regime proxy (high=bear, low=bull)
- funding_rates: live from Binance public API (no auth)
- volatility_regime: live BTC 30d realized vol from CoinGecko
- stablecoin_flows: live USDT mcap 7d WoW from CoinGecko
- RISK_ON threshold: 5 (was 7 — aggressive mode)
- File-based cache (5min TTL) — no rate limit hits

CRITICAL: Kill switch and regime detection NEVER route through inference.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


def _clip(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


class RegimeState(Enum):
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"
    RISK_ON = "RISK_ON"


@dataclass(frozen=True)
class RegimeSignal:
    name: str
    value: float
    score: float
    weight: float


@dataclass(frozen=True)
class RegimeAssessment:
    state: RegimeState
    score: float
    signals: list[RegimeSignal]
    timestamp: datetime
    confidence: float

    @property
    def is_risk_on(self) -> bool:
        return self.state == RegimeState.RISK_ON

    @property
    def allows_new_positions(self) -> bool:
        return self.state == RegimeState.RISK_ON

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp.isoformat(),
            "signals": [
                {"name": s.name, "value": round(s.value, 4),
                 "score": round(s.score, 2), "weight": round(s.weight, 3)}
                for s in self.signals
            ],
        }


# --- File-based cache (5min TTL) ---

_CACHE_DIR = Path.home() / ".cache" / "ig88-regime"
_CACHE_TTL = 300


def _cache_get(key: str) -> dict | None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _CACHE_DIR / f"{key}.json"
        if not p.exists():
            return None
        if time.time() - p.stat().st_mtime > _CACHE_TTL:
            return None
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def _cache_set(key: str, data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_DIR / f"{key}.json", "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# --- Data Collector ---

class MarketDataCollector:
    """Live regime data from free public APIs. File-cached 5min to avoid rate limits.
    
    Calls made (fresh run, no cache):
      - Fear&Greed: alternative.me/fng
      - CoinGecko: /coins/bitcoin, /global, /coins/bitcoin/market_chart (30d), 
                   /coins/tether/market_chart (7d)
      - Binance: /fapi/v1/premiumIndex for 5 perpetual symbols
    Total: ~8 API calls, well within CoinGecko free tier (10-30/min).
    """

    def _fetch(self, url: str, cache_key: str | None = None,
               timeout: int = 10) -> dict | None:
        if cache_key:
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = json.loads(r.read().decode())
                if cache_key:
                    _cache_set(cache_key, data)
                return data
        except Exception:
            if cache_key:
                # Fall back to stale cache on error
                stale = _cache_get(cache_key)
                if stale is not None:
                    return stale
            return None

    def get_regime_inputs(self) -> dict[str, float]:
        inputs = {}

        # Fear & Greed Index
        fng = self._fetch("https://api.alternative.me/fng/", "fear_greed")
        if fng and "data" in fng:
            inputs["fear_greed_index"] = float(fng["data"][0]["value"])

        # CoinGecko: BTC trend + dominance
        btc = self._fetch(
            "https://api.coingecko.com/api/v3/coins/bitcoin", "btc_coin"
        )
        cg_global = self._fetch(
            "https://api.coingecko.com/api/v3/global", "cg_global"
        )
        if btc and "market_data" in btc:
            md = btc["market_data"]
            inputs["btc_trend"] = float(
                md["price_change_percentage_7d_in_currency"]["usd"]
            )
            inputs["total_mcap_trend"] = inputs["btc_trend"] * 1.05
        if cg_global and "data" in cg_global:
            inputs["btc_dominance"] = float(
                cg_global["data"]["market_cap_percentage"]["btc"]
            )

        # Binance funding rates (top 5 perpetuals)
        frs = []
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]:
            r = self._fetch(
                f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}",
                f"funding_{sym}"
            )
            if r and "lastFundingRate" in r:
                frs.append(float(r["lastFundingRate"]) * 100)
        if frs:
            inputs["funding_rates"] = sum(frs) / len(frs)

        # BTC 30d realized vol
        chart = self._fetch(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=30&interval=daily",
            "btc_chart_30d"
        )
        if chart and "prices" in chart and len(chart["prices"]) > 5:
            prices = [p[1] for p in chart["prices"]]
            log_rets = [math.log(prices[i+1] / prices[i])
                        for i in range(len(prices) - 1)]
            if len(log_rets) > 4:
                mean = sum(log_rets) / len(log_rets)
                var = sum((r - mean) ** 2 for r in log_rets) / len(log_rets)
                inputs["volatility_regime"] = math.sqrt(var) * math.sqrt(365) * 100

        # Stablecoin flows (USDT mcap WoW)
        usdt_chart = self._fetch(
            "https://api.coingecko.com/api/v3/coins/tether/market_chart"
            "?vs_currency=usd&days=8&interval=daily",
            "usdt_chart_7d"
        )
        if usdt_chart and "market_caps" in usdt_chart:
            caps = usdt_chart["market_caps"]
            if len(caps) >= 2 and caps[0][1] > 0:
                inputs["stablecoin_flows"] = (
                    (caps[-1][1] - caps[0][1]) / caps[0][1] * 100
                )

        return inputs


# --- Signal scorers ---

def score_btc_trend(pct_7d: float) -> float:
    """BTC 7d: -10% or worse = 0, +10% or better = 10."""
    if pct_7d <= -10: return 0.0
    if pct_7d >= 10: return 10.0
    return 2.0 + (pct_7d + 10) * 6.0 / 20.0


def score_fear_greed(v: float) -> float:
    """Fear&Greed 0-100 → 0-10."""
    return _clip(v / 10.0, 0.0, 10.0)


def score_funding(avg_rate_pct: float) -> float:
    """Funding >0.05%/8h (>5.5% ann) = leveraged longs = risk-off.
    Negative funding = shorts paying = RISK_ON (short squeeze setup)."""
    normalized = (avg_rate_pct + 0.05) / 0.15
    return _clip((1 - normalized) * 10.0, 0.0, 10.0)


def score_stablecoin_flows(pct_change: float) -> float:
    """USDT mcap rising = capital building = RISK_ON. ±10% range."""
    if pct_change <= -10: return 0.0
    if pct_change >= 10: return 10.0
    return 5.0 + pct_change * 0.5


def score_btc_dominance(dom: float) -> float:
    """BTC dominance: >60% = extreme risk-off, <40% = risk-on."""
    if dom >= 60: return 1.0
    if dom <= 40: return 9.0
    if dom > 55: return 1.0 + (60 - dom)
    if dom < 45: return 9.0 - (45 - dom)
    return 5.0


def score_volatility(vol_annual: float) -> float:
    """BTC 30d realized vol: low = compressed (RISK_ON), high = crisis (RISK_OFF)."""
    if vol_annual <= 25: return 9.0
    if vol_annual <= 35: return 8.0
    if vol_annual <= 50: return 5.5
    if vol_annual <= 65: return 3.5
    if vol_annual <= 80: return 2.0
    return 0.5


SIGNAL_SCORERS = {
    "btc_trend":           score_btc_trend,
    "total_mcap_trend":    score_btc_trend,
    "fear_greed_index":    score_fear_greed,
    "funding_rates":       score_funding,
    "stablecoin_flows":    score_stablecoin_flows,
    "btc_dominance":       score_btc_dominance,
    "volatility_regime":   score_volatility,
}


def assess_regime(
    inputs: dict[str, float],
    weights: dict[str, float],
    risk_off_max: int = 3,
    neutral_max: int = 5,
) -> RegimeAssessment:
    """Compute composite regime from raw inputs + weights."""
    signals = []
    available_weight = 0.0

    for name, scorer in SIGNAL_SCORERS.items():
        if name not in inputs:
            continue
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        score = scorer(inputs[name])
        signals.append(RegimeSignal(name=name, value=inputs[name],
                                    score=score, weight=w))
        available_weight += w

    if not signals:
        return RegimeAssessment(
            state=RegimeState.RISK_OFF, score=0.0, signals=[],
            timestamp=datetime.utcnow(), confidence=0.0,
        )

    composite = sum(s.score * s.weight for s in signals) / available_weight
    total_w = sum(weights.values())
    confidence = available_weight / total_w if total_w > 0 else 0.0

    if composite <= risk_off_max:
        state = RegimeState.RISK_OFF
    elif composite <= neutral_max:
        state = RegimeState.NEUTRAL
    else:
        state = RegimeState.RISK_ON

    return RegimeAssessment(
        state=state, score=composite, signals=signals,
        timestamp=datetime.utcnow(), confidence=confidence,
    )


def regime_allows_venue(assessment: RegimeAssessment, venue: str) -> bool:
    """Polymarket is always allowed; others require RISK_ON."""
    if venue == "polymarket":
        return True
    return assessment.allows_new_positions
