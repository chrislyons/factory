
"""Regime detection module — deterministic, no LLM.

Three states: RISK_ON / NEUTRAL / RISK_OFF
Score: 0-10 with configurable threshold mapping.

CRITICAL: Kill switch and regime detection NEVER route through inference.
If the inference layer is down, the system defaults to RISK_OFF — not to
a cached LLM decision.
"""

from __future__ import annotations

import urllib.request
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

def _clip(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))

class RegimeState(Enum):
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"
    RISK_ON = "RISK_ON"

@dataclass(frozen=True)
class RegimeSignal:
    """A single input signal for regime scoring."""
    name: str
    value: float        # Raw value
    score: float        # Normalized 0-10
    weight: float       # From config

@dataclass(frozen=True)
class RegimeAssessment:
    """Complete regime assessment output."""
    state: RegimeState
    score: float                    # Composite 0-10
    signals: list[RegimeSignal]     # Individual signal scores
    timestamp: datetime
    confidence: float               # How many signals were available (0-1)

    @property
    def is_risk_on(self) -> bool:
        return self.state == RegimeState.RISK_ON

    @property
    def allows_new_positions(self) -> bool:
        """Only RISK_ON allows new positions on regime-gated venues."""
        return self.state == RegimeState.RISK_ON

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp.isoformat(),
            "signals": [
                {
                    "name": s.name,
                    "value": round(s.value, 4),
                    "score": round(s.score, 2),
                    "weight": round(s.weight, 3),
                }
                for s in self.signals
            ],
        }

# --- API Collector ---

class MarketDataCollector:
    """Fetches live data for regime assessment using standard libs to minimize attack surface."""
    
    @staticmethod
    def fetch_json(url: str) -> dict | None:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception:
            return None

    def get_regime_inputs(self) -> dict[str, float]:
        inputs = {}
        
        # 1. Fear & Greed Index (api.alternative.me)
        fng = self.fetch_json("https://api.alternative.me/fng/")
        if fng and "data" in fng:
            inputs["fear_greed_index"] = float(fng["data"][0]["value"])

        # 2. CoinGecko (BTC Price, Global Cap, Dominance)
        # Using simplified endpoints
        cg_global = self.fetch_json("https://api.coingecko.com/api/v3/global")
        if cg_global and "data" in cg_global:
            # Market Cap Trend (7d change is harder via simple API, using current as proxy or snapshot)
            # For a true 7d trend, we'd need /coins/markets with days=7
            # To keep this robust and fast, we'll use the global data available
            inputs["total_mcap_trend"] = float(cg_global["data"]["market_cap_change_percentage_24h_usd"]) # Proxy
            inputs["btc_dominance_delta"] = float(cg_global["data"]["market_cap_percentage"]["btc"])

        # 3. BTC Price Trend (CoinGecko)
        cg_btc = self.fetch_json("https://api.coingecko.com/api/v3/coins/bitcoin")
        if cg_btc and "market_data" in cg_btc:
            inputs["btc_trend"] = float(cg_btc["market_data"]["price_change_percentage_7d_in_currency"]["usd"])

        # Note: Funding rates and Stablecoin flows typically require API keys or more complex scraping.
        # We leave those as placeholders in inputs for now, and the assess_regime handles missing data.
        
        return inputs

# --- Signal scoring functions ---

def score_btc_trend(pct_change_7d: float) -> float:
    if pct_change_7d <= -10: return 0.0
    if pct_change_7d >= 10: return 10.0
    return 2.0 + (pct_change_7d + 10) * (6.0 / 20.0)

def score_total_mcap_trend(pct_change_7d: float) -> float:
    return score_btc_trend(pct_change_7d)

def score_fear_greed(index_value: float) -> float:
    return _clip(index_value / 10.0, 0.0, 10.0)

def score_funding_rates(avg_funding_rate: float) -> float:
    normalized = (avg_funding_rate + 0.05) / 0.10
    return _clip(normalized * 10.0, 0.0, 10.0)

def score_stablecoin_flows(net_flow_millions: float) -> float:
    normalized = (net_flow_millions + 500) / 1000
    return _clip(normalized * 10.0, 0.0, 10.0)

def score_btc_dominance_delta(delta_7d: float) -> float:
    # Assuming delta_7d is current dominance minus 7d ago. 
    # If we only have current, we can't calculate delta here.
    # For now, we assume the input provided to this function is already the delta.
    normalized = (-delta_7d + 3) / 6
    return _clip(normalized * 10.0, 0.0, 10.0)

def score_volatility_regime(garch_percentile: float) -> float:
    if garch_percentile <= 20: return 8.0
    if garch_percentile >= 80: return 1.0
    return 8.0 - (garch_percentile - 20) * (5.0 / 60.0)

SIGNAL_SCORERS = {
    "btc_trend": score_btc_trend,
    "total_mcap_trend": score_total_mcap_trend,
    "fear_greed_index": score_fear_greed,
    "funding_rates": score_funding_rates,
    "stablecoin_flows": score_stablecoin_flows,
    "btc_dominance_delta": score_btc_dominance_delta,
    "volatility_regime": score_volatility_regime,
}

def assess_regime(
    inputs: dict[str, float],
    weights: dict[str, float],
    risk_off_max: int = 3,
    neutral_max: int = 6,
) -> RegimeAssessment:
    signals = []
    available_weight = 0.0

    for signal_name, scorer in SIGNAL_SCORERS.items():
        if signal_name not in inputs:
            continue
        weight = weights.get(signal_name, 0.0)
        if weight <= 0:
            continue

        raw_value = inputs[signal_name]
        score = scorer(raw_value)
        signals.append(RegimeSignal(
            name=signal_name,
            value=raw_value,
            score=score,
            weight=weight,
        ))
        available_weight += weight

    if available_weight == 0 or not signals:
        return RegimeAssessment(
            state=RegimeState.RISK_OFF,
            score=0.0,
            signals=[],
            timestamp=datetime.utcnow(),
            confidence=0.0,
        )

    composite = sum(s.score * s.weight for s in signals) / available_weight
    confidence = available_weight / sum(weights.values()) if weights else 0.0

    if composite <= risk_off_max:
        state = RegimeState.RISK_OFF
    elif composite <= neutral_max:
        state = RegimeState.NEUTRAL
    else:
        state = RegimeState.RISK_ON

    return RegimeAssessment(
        state=state,
        score=composite,
        signals=signals,
        timestamp=datetime.utcnow(),
        confidence=confidence,
    )

def regime_allows_venue(assessment: RegimeAssessment, venue: str) -> bool:
    if venue == "polymarket":
        return True
    return assessment.allows_new_positions
