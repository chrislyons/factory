"""
Hyperliquid Perps Scanner
==========================
Scans Hyperliquid perpetual futures for trend-following and breakout signals.
Designed for the perps venue — uses higher leverage, needs ATR-based stops.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.scanner.base import (
    VenueScanner, Signal, SignalType, RegimeState, PositionInfo,
)

logger = logging.getLogger(__name__)


# ATR breakout parameters for perps
DEFAULT_ATR_BO_PARAMS = {
    "atr_period": 14,
    "atr_multiplier": 1.5,
    "lookback": 20,
    "volume_mult": 1.2,
    "min_atr_pct": 0.02,
    "stop_atr_mult": 2.0,
    "target_atr_mult": 3.0,
}


class HyperliquidScanner(VenueScanner):
    """Scanner for Hyperliquid perpetual futures."""

    venue_name = "hyperliquid"
    venue_type = "perps"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("api_url", "https://api.hyperliquid.xyz")
        self._regime_cache: Optional[RegimeState] = None

    def scan(self) -> list[Signal]:
        """Scan all Hyperliquid perps for ATR breakout and momentum signals."""
        signals: list[Signal] = []
        regime = self.get_regime()

        if regime.regime == "RISK_OFF":
            return []

        for symbol in self.symbols:
            try:
                df = self.load_ohlcv(symbol, "4h")
                if df is None or len(df) < 60:
                    continue

                sig = self._check_atr_breakout(symbol, df, regime)
                if sig:
                    signals.append(sig)

            except Exception as e:
                logger.warning(f"Error scanning HL {symbol}: {e}")
                continue

        return signals

    def _check_atr_breakout(
        self, symbol: str, df: pd.DataFrame, regime: RegimeState
    ) -> Optional[Signal]:
        """ATR breakout signal for perpetual futures."""
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        o = df["open"].values
        v = df["volume"].values

        params = DEFAULT_ATR_BO_PARAMS

        # ATR
        tr = np.maximum(h[1:] - l[1:], np.maximum(
            np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])
        ))
        atr = pd.Series(tr).rolling(params["atr_period"]).mean().values

        # Donchian channel (N-period high/low)
        lookback = params["lookback"]
        highest = pd.Series(h).rolling(lookback).max().values
        lowest = pd.Series(l).rolling(lookback).min().values

        # Volume
        vol_sma = pd.Series(v).rolling(20).mean().values
        vol_ratio = np.where(vol_sma > 0, v / vol_sma, 1.0)

        # Check latest closed bar
        i = len(c) - 2
        if i < max(lookback, params["atr_period"]) + 2:
            return None

        # ATR must be sufficient (avoid dead markets)
        atr_pct = atr[i - 1] / c[i] if c[i] > 0 else 0
        if atr_pct < params["min_atr_pct"]:
            return None

        # Long breakout: close above N-bar high
        if (
            c[i] > highest[i - 1]
            and vol_ratio[i] > params["volume_mult"]
        ):
            stop_dist = atr[i - 1] * params["stop_atr_mult"]
            target_dist = atr[i - 1] * params["target_atr_mult"]
            stop_pct = stop_dist / c[i]
            target_pct = target_dist / c[i]

            confidence = min(1.0, vol_ratio[i] / 2.0) * 0.7
            confidence *= min(1.0, atr_pct / 0.04)  # Higher vol = more confidence

            # Regime boost
            if regime.regime in ("BULLISH", "EUPHORIA"):
                confidence *= 1.1
            elif regime.regime == "BEARISH":
                confidence *= 0.6

            confidence = min(1.0, confidence)

            now = datetime.now(timezone.utc).isoformat()
            return Signal(
                signal_id=f"hyperliquid:{symbol}:{now}",
                venue="hyperliquid",
                symbol=symbol,
                signal_type=SignalType.ENTRY,
                direction="long",
                score=min(1.0, confidence + 0.2),
                conviction=confidence,
                size_fraction=0.05 * (self.max_leverage / 10) * (regime.score / 10),
                strategy_type="atr_breakout",
                price=float(c[i]),
                stop_pct=float(stop_pct),
                target_pct=float(target_pct),
                timeframe="4h",
                regime=regime.regime,
                timestamp=now,
                extra={
                    "atr_pct": float(atr_pct),
                    "vol_ratio": float(vol_ratio[i]),
                    "highest_n": float(highest[i - 1]),
                },
            )

        return None

    def get_regime(self) -> RegimeState:
        """Get current market regime — shares BTC data with Kraken."""
        if self._regime_cache is not None:
            return self._regime_cache

        try:
            from src.trading.regime import get_current_regime
            raw = get_current_regime()
            regime_name = raw["regime"].split("_")[0]
            regime_map = {
                "CRASH": "RISK_OFF", "BEARISH": "BEARISH",
                "RANGING": "RANGING", "BULLISH": "BULLISH",
                "EUPHORIA": "EUPHORIA",
            }
            mapped = regime_map.get(regime_name, "NEUTRAL")
            btc_ret = raw["metadata"].get("btc_20bar_return", 0)
            score_10 = max(0, min(10, (btc_ret + 0.10) / 0.20 * 10))

            self._regime_cache = RegimeState(
                regime=mapped,
                score=score_10,
                trend_strength=btc_ret,
                metadata=raw["metadata"],
            )
        except Exception as e:
            logger.warning(f"Failed to get HL regime: {e}")
            self._regime_cache = RegimeState()

        return self._regime_cache

    def get_positions(self) -> list[PositionInfo]:
        """Get current Hyperliquid positions."""
        return []

    def execute(self, signal: Signal) -> dict[str, Any]:
        """Execute on Hyperliquid."""
        now = datetime.now(timezone.utc).isoformat()

        if self.config.get("paper_mode", True):
            return {
                "status": "paper_filled",
                "signal_id": signal.signal_id,
                "venue": "hyperliquid",
                "symbol": signal.symbol,
                "direction": signal.direction,
                "price": signal.price,
                "size_fraction": signal.size_fraction,
                "leverage": self.config.get("default_leverage", 2),
                "timestamp": now,
            }

        return {
            "status": "not_implemented",
            "message": "Live Hyperliquid execution not yet wired",
            "signal_id": signal.signal_id,
        }
