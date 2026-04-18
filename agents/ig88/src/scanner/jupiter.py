"""
Jupiter Perps Scanner
=====================
Scans Jupiter perpetual futures on Solana for momentum and mean-reversion signals.
Lower leverage than Hyperliquid, tighter position limits.
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


# Volume ignition + RSI parameters
DEFAULT_VI_PARAMS = {
    "volume_threshold": 1.5,
    "price_gain_pct": 0.005,
    "rsi_cross_level": 50,
    "rsi_period": 14,
    "stop_pct": 0.015,
    "target_pct": 0.02,
    "exit_bars": 10,
}


class JupiterScanner(VenueScanner):
    """Scanner for Jupiter perpetual futures."""

    venue_name = "jupiter"
    venue_type = "perps"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.rpc_url = config.get("rpc_url", "")
        self.default_leverage = config.get("default_leverage", 2)
        self._regime_cache: Optional[RegimeState] = None

    def scan(self) -> list[Signal]:
        """Scan Jupiter perps for volume ignition and momentum signals."""
        signals: list[Signal] = []
        regime = self.get_regime()

        if regime.regime == "RISK_OFF":
            return []

        for symbol in self.symbols:
            try:
                # Jupiter uses standard symbols for data loading
                base_sym = symbol.replace("-PERP", "")
                df = self.load_ohlcv(base_sym, "4h")
                if df is None or len(df) < 60:
                    continue

                sig = self._check_volume_ignition(symbol, df, regime)
                if sig:
                    signals.append(sig)

            except Exception as e:
                logger.warning(f"Error scanning Jupiter {symbol}: {e}")
                continue

        return signals

    def _check_volume_ignition(
        self, symbol: str, df: pd.DataFrame, regime: RegimeState
    ) -> Optional[Signal]:
        """Volume ignition + RSI cross signal (H3-B style)."""
        c = df["close"].values
        o = df["open"].values
        v = df["volume"].values

        # RSI
        delta = np.diff(c, prepend=c[0])
        gain = np.clip(delta, 0, None)
        loss = np.clip(-delta, None, 0)
        gain_ema = pd.Series(gain).ewm(alpha=1 / 14, min_periods=14).mean().values
        loss_ema = pd.Series(loss).ewm(alpha=1 / 14, min_periods=14).mean().values
        rsi = np.where(
            loss_ema > 0,
            100 - (100 / (1 + np.where(loss_ema > 0, gain_ema / loss_ema, 0))),
            50.0,
        )
        rsi = np.nan_to_num(rsi, nan=50.0)

        # Volume
        vol_sma = pd.Series(v).rolling(20).mean().values
        vol_ratio = np.where(vol_sma > 0, v / vol_sma, 1.0)

        i = len(c) - 2
        if i < 20:
            return None

        params = DEFAULT_VI_PARAMS

        # Conditions
        vol_spike = vol_ratio[i] > params["volume_threshold"]
        price_gain = (c[i] - c[i - 1]) / c[i - 1] > params["price_gain_pct"]
        rsi_cross = rsi[i] > params["rsi_cross_level"] and rsi[i - 1] <= params["rsi_cross_level"]

        if vol_spike and price_gain and rsi_cross:
            confidence = min(1.0, vol_ratio[i] / 2.0)
            confidence *= 0.8  # Jupiter has higher friction

            # Regime filter
            if regime.regime in ("BULLISH", "EUPHORIA"):
                confidence *= 1.0
            elif regime.regime == "RANGING":
                confidence *= 0.6
            elif regime.regime == "BEARISH":
                confidence *= 0.4

            confidence = min(1.0, max(0.0, confidence))

            now = datetime.now(timezone.utc).isoformat()
            return Signal(
                signal_id=f"jupiter:{symbol}:{now}",
                venue="jupiter",
                symbol=symbol,
                signal_type=SignalType.ENTRY,
                direction="long",
                score=min(1.0, confidence + 0.1),
                conviction=confidence,
                size_fraction=0.03 * (self.default_leverage / 2) * (regime.score / 10),
                strategy_type="volume_ignition",
                price=float(c[i]),
                stop_pct=params["stop_pct"],
                target_pct=params["target_pct"],
                timeframe="4h",
                regime=regime.regime,
                timestamp=now,
                extra={
                    "vol_ratio": float(vol_ratio[i]),
                    "price_gain_pct": float((c[i] - c[i - 1]) / c[i - 1] * 100),
                    "rsi": float(rsi[i]),
                    "rsi_prev": float(rsi[i - 1]),
                },
            )

        return None

    def get_regime(self) -> RegimeState:
        """Shared regime detection."""
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
            logger.warning(f"Failed to get Jupiter regime: {e}")
            self._regime_cache = RegimeState()

        return self._regime_cache

    def get_positions(self) -> list[PositionInfo]:
        """Get current Jupiter positions."""
        return []

    def execute(self, signal: Signal) -> dict[str, Any]:
        """Execute on Jupiter."""
        now = datetime.now(timezone.utc).isoformat()

        if self.config.get("paper_mode", True):
            return {
                "status": "paper_filled",
                "signal_id": signal.signal_id,
                "venue": "jupiter",
                "symbol": signal.symbol,
                "direction": signal.direction,
                "price": signal.price,
                "size_fraction": signal.size_fraction,
                "leverage": self.default_leverage,
                "borrow_fee_hourly": True,
                "timestamp": now,
            }

        return {
            "status": "not_implemented",
            "message": "Live Jupiter execution not yet wired",
            "signal_id": signal.signal_id,
        }
