"""Regime detection module — deterministic, no LLM.

Three states: RISK_ON / NEUTRAL / RISK_OFF
Score: 0-10 with configurable threshold mapping.

CRITICAL: Kill switch and regime detection NEVER route through inference.
If the inference layer is down, the system defaults to RISK_OFF — not to
a cached LLM decision.

Inputs:
  - BTC 7-day price trend
  - Total crypto market cap trend
  - Crypto Fear & Greed Index (cfgi.io)
  - Aggregate perpetual funding rates
  - Stablecoin net flows (USDT/USDC mint/burn)
  - BTC dominance delta (rising = risk-off signal)
  - GARCH conditional volatility state
"""

from __future__ import annotations

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


# --- Signal scoring functions ---
# Each returns a score 0-10 where 10 = maximally risk-on.

def score_btc_trend(pct_change_7d: float) -> float:
    """BTC 7-day % change → score.
    <-10% → 0, -10% to +10% → linear 2-8, >+10% → 10.
    """
    if pct_change_7d <= -10:
        return 0.0
    if pct_change_7d >= 10:
        return 10.0
    return 2.0 + (pct_change_7d + 10) * (6.0 / 20.0)


def score_total_mcap_trend(pct_change_7d: float) -> float:
    """Total market cap 7-day % change → score. Same mapping as BTC."""
    return score_btc_trend(pct_change_7d)


def score_fear_greed(index_value: float) -> float:
    """Crypto Fear & Greed Index (0-100) → score (0-10).
    Direct linear mapping: 0 = extreme fear (risk-off), 100 = extreme greed (risk-on).
    Note: extreme greed (>80) is contrarian bearish, but we handle that
    in the composite rather than here — the signal is what the crowd feels.
    """
    return _clip(index_value / 10.0, 0.0, 10.0)


def score_funding_rates(avg_funding_rate: float) -> float:
    """Average perp funding rate across major pairs → score.
    Positive funding = longs pay shorts = bullish crowd.
    -0.05% → 0, 0% → 5, +0.05% → 10. Clamped.
    """
    # funding_rate is typically -0.1% to +0.1%
    normalized = (avg_funding_rate + 0.05) / 0.10
    return _clip(normalized * 10.0, 0.0, 10.0)


def score_stablecoin_flows(net_flow_millions: float) -> float:
    """Net stablecoin mint/burn in millions USD (7-day) → score.
    Net minting (positive) = capital entering crypto = bullish.
    <-500M → 0, 0 → 5, >+500M → 10.
    """
    normalized = (net_flow_millions + 500) / 1000
    return _clip(normalized * 10.0, 0.0, 10.0)


def score_btc_dominance_delta(delta_7d: float) -> float:
    """BTC dominance change (percentage points, 7-day) → score.
    Rising BTC dominance = capital fleeing alts = risk-off.
    +3pp → 0, 0 → 5, -3pp → 10. INVERTED — rising dom is bearish for alts.
    """
    normalized = (-delta_7d + 3) / 6
    return _clip(normalized * 10.0, 0.0, 10.0)


def score_volatility_regime(garch_percentile: float) -> float:
    """GARCH conditional volatility percentile (0-100) → score.
    Low vol = calm market = risk-on for momentum.
    High vol = uncertain = risk-off.
    <20th pctile → 8, 20-80 → linear 8-3, >80 → 1.
    """
    if garch_percentile <= 20:
        return 8.0
    if garch_percentile >= 80:
        return 1.0
    return 8.0 - (garch_percentile - 20) * (5.0 / 60.0)


# Signal name → scoring function mapping
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
    """Compute regime assessment from raw market data.

    Args:
        inputs: Signal name → raw value. Missing signals are skipped
            (score computed from available signals only).
        weights: Signal name → weight (from config). Must sum to ~1.0.
        risk_off_max: Score at or below this = RISK_OFF.
        neutral_max: Score at or below this = NEUTRAL. Above = RISK_ON.

    Returns:
        RegimeAssessment with state, composite score, and individual signals.
    """
    signals: list[RegimeSignal] = []
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

    # If no signals available, default to RISK_OFF (safe)
    if available_weight == 0 or not signals:
        return RegimeAssessment(
            state=RegimeState.RISK_OFF,
            score=0.0,
            signals=[],
            timestamp=datetime.utcnow(),
            confidence=0.0,
        )

    # Weighted average, renormalized to available signals
    composite = sum(s.score * s.weight for s in signals) / available_weight
    confidence = available_weight / sum(weights.values()) if weights else 0.0

    # Map to state
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
    """Check if the current regime allows trading on a venue.

    Polymarket runs in all regimes (event outcomes uncorrelated with crypto).
    All other venues require RISK_ON.
    """
    if venue == "polymarket":
        return True
    return assessment.allows_new_positions
