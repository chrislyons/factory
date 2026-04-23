"""
Kraken Spot Scanner
===================
Scans Kraken spot pairs for MR and momentum signals.
Reuses existing scanner logic from src/trading/scanner.py but wraps
it in the standardized VenueScanner interface.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.scanner.base import (
    VenueScanner, Signal, SignalType, RegimeState, PositionInfo,
)

logger = logging.getLogger(__name__)


# Default MR parameters (from validated scanner)
DEFAULT_MR_PARAMS = {
    "rsi_threshold": 30,
    "bb_std": 1.0,
    "vol_mult": 1.8,
    "entry_delay": 2,
    "stop_pct": 0.0075,
    "target_pct": 0.015,
    "exit_bars": 16,
}


class KrakenScanner(VenueScanner):
    """Scanner for Kraken spot pairs."""

    venue_name = "kraken"
    venue_type = "spot"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._regime_cache: Optional[RegimeState] = None

    def scan(self) -> list[Signal]:
        """Scan all Kraken pairs for mean-reversion and momentum signals."""
        signals: list[Signal] = []

        regime = self.get_regime()
        # In risk-off, no trading
        if regime.regime == "RISK_OFF":
            return []

        for symbol in self.symbols:
            try:
                df = self.load_ohlcv(symbol, "4h")
                if df is None or len(df) < 60:
                    continue

                sig = self._check_mr_signal(symbol, df, regime)
                if sig:
                    signals.append(sig)

            except Exception as e:
                logger.warning(f"Error scanning {symbol}: {e}")
                continue

        return signals

    def _check_mr_signal(
        self, symbol: str, df: pd.DataFrame, regime: RegimeState
    ) -> Optional[Signal]:
        """Check for mean-reversion signal on latest bars."""
        c = df["close"].values
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
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

        # Bollinger Bands
        sma20 = pd.Series(c).rolling(20).mean().values
        std20 = pd.Series(c).rolling(20).std().values

        # Volume ratio
        vol_sma = pd.Series(v).rolling(20).mean().values
        vol_ratio = np.where(vol_sma > 0, v / vol_sma, 1.0)

        # Check latest closed bar
        i = len(c) - 2
        if i < 20:
            return None

        params = DEFAULT_MR_PARAMS
        bb_lower = sma20[i] - std20[i] * params["bb_std"]

        if (
            rsi[i] < params["rsi_threshold"]
            and c[i] < bb_lower
            and vol_ratio[i] > params["vol_mult"]
        ):
            confidence = 1.0 - (rsi[i] / params["rsi_threshold"])
            # Regime adjustment
            if regime.regime == "BULLISH":
                confidence *= 1.0
            elif regime.regime == "BEARISH":
                confidence *= 0.8
            elif regime.regime == "RANGING":
                confidence *= 0.7

            now = datetime.now(timezone.utc).isoformat()
            return Signal(
                signal_id=f"kraken:{symbol}:{now}",
                venue="kraken",
                symbol=symbol,
                signal_type=SignalType.ENTRY,
                direction="long",
                score=min(1.0, confidence + 0.3),
                conviction=confidence,
                size_fraction=0.05 * regime.score / 10.0,
                strategy_type="mr_rsi_bb",
                price=float(c[i]),
                stop_pct=params["stop_pct"],
                target_pct=params["target_pct"],
                timeframe="4h",
                regime=regime.regime,
                timestamp=now,
                extra={
                    "rsi": float(rsi[i]),
                    "bb_position": float((c[i] - bb_lower) / std20[i]) if std20[i] > 0 else 0,
                    "vol_ratio": float(vol_ratio[i]),
                },
            )

        return None

    def get_regime(self) -> RegimeState:
        """Get current market regime using BTC data."""
        if self._regime_cache is not None:
            return self._regime_cache

        try:
            from src.trading.regime import get_current_regime
            raw = get_current_regime()
            regime_name = raw["regime"].split("_")[0]
            # Map to standard names
            regime_map = {
                "CRASH": "RISK_OFF",
                "BEARISH": "BEARISH",
                "RANGING": "RANGING",
                "BULLISH": "BULLISH",
                "EUPHORIA": "EUPHORIA",
            }
            mapped = regime_map.get(regime_name, "NEUTRAL")
            score = raw["metadata"].get("btc_20bar_return", 0)
            # Convert return to 0-10 scale
            score_10 = max(0, min(10, (score + 0.10) / 0.20 * 10))

            self._regime_cache = RegimeState(
                regime=mapped,
                score=score_10,
                trend_strength=score,
                metadata=raw["metadata"],
            )
        except Exception as e:
            logger.warning(f"Failed to get regime: {e}")
            self._regime_cache = RegimeState()

        return self._regime_cache

    def get_positions(self) -> list[PositionInfo]:
        """Get current open positions from Kraken.

        In paper mode, reads from state file.
        In live mode, would call Kraken API.
        """
        # Placeholder — in production, reads from paper_trader state or API
        return []

    def execute(self, signal: Signal) -> dict[str, Any]:
        """Execute a signal on Kraken.

        Paper mode: log the trade.
        Live mode: send to Kraken API via kraken_executor.
        """
        now = datetime.now(timezone.utc).isoformat()

        if self.config.get("paper_mode", True):
            return {
                "status": "paper_filled",
                "signal_id": signal.signal_id,
                "venue": "kraken",
                "symbol": signal.symbol,
                "direction": signal.direction,
                "price": signal.price,
                "size_fraction": signal.size_fraction,
                "timestamp": now,
            }

        # Live execution would call kraken_executor
        return {
            "status": "not_implemented",
            "message": "Live Kraken execution not yet wired",
            "signal_id": signal.signal_id,
        }
