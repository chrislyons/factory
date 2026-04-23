"""
Venue Scanner Base
==================
Abstract base class and standardized data types for cross-venue scanning.
Every venue scanner implements the same interface, so the orchestrator
treats all venues uniformly.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standardized Types
# ---------------------------------------------------------------------------

class SignalType(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    REDUCE = "reduce"  # Partial position close
    HOLD = "hold"


@dataclass
class Signal:
    """Standardized trade signal across all venues.

    The orchestrator ranks and allocates based on these fields.
    Venue-specific details go in `extra`.
    """
    signal_id: str                          # Unique: "{venue}:{symbol}:{timestamp}"
    venue: str                              # hyperliquid, kraken, jupiter, polymarket
    symbol: str                             # Standardized symbol
    signal_type: SignalType = SignalType.ENTRY
    direction: str = "long"                 # long / short
    score: float = 0.0                      # Raw signal strength 0-1
    conviction: float = 0.0                 # Confidence in this specific signal 0-1
    size_fraction: float = 0.0              # Recommended size as fraction of venue capital
    strategy_type: str = ""                 # e.g., "atr_breakout", "mr_rsi_bb"
    strategy_id: str = ""                   # Registry strategy_id if matched
    price: float = 0.0                      # Current / reference price
    stop_pct: float = 0.0                   # Stop loss distance (%)
    target_pct: float = 0.0                 # Take profit distance (%)
    timeframe: str = "4h"
    regime: str = ""                        # Current market regime
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def combined_score(self) -> float:
        """Score * conviction for cross-venue ranking."""
        return self.score * self.conviction

    @property
    def expected_value(self) -> float:
        """Quick EV estimate based on score, conviction, and risk/reward."""
        if self.stop_pct == 0:
            return 0.0
        rr = self.target_pct / self.stop_pct if self.stop_pct > 0 else 0.0
        # Rough: EV = conviction * target - (1-conviction) * stop
        return self.conviction * self.target_pct - (1 - self.conviction) * self.stop_pct

    def __repr__(self) -> str:
        return (
            f"Signal({self.venue}:{self.symbol} {self.direction} "
            f"score={self.score:.2f} conv={self.conviction:.2f} "
            f"combined={self.combined_score:.3f})"
        )


@dataclass
class RegimeState:
    """Market regime state for a venue / asset."""
    regime: str = "NEUTRAL"                 # RISK_OFF, BEARISH, RANGING, BULLISH, EUPHORIA
    score: float = 5.0                      # 0-10 composite regime score
    trend_strength: float = 0.0            # -1 to 1
    volatility_regime: str = "normal"       # low, normal, high, extreme
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionInfo:
    """Current open position on a venue."""
    venue: str
    symbol: str
    direction: str                          # long / short
    size: float                             # Notional or base quantity
    entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    entry_time: str = ""
    strategy_id: str = ""
    stop_price: float = 0.0
    target_price: float = 0.0

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.direction == "long":
            return (self.current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.current_price) / self.entry_price


# ---------------------------------------------------------------------------
# Base Scanner
# ---------------------------------------------------------------------------

class VenueScanner(ABC):
    """Abstract base for all venue scanners.

    Each scanner:
    - Knows its venue's API, symbols, fee structure, and limits
    - Loads venue config from venues.yaml
    - Produces standardized Signal objects
    - Reports current positions and regime state
    """

    venue_name: str = "unknown"
    venue_type: str = "unknown"  # perps, spot, prediction

    def __init__(self, config: dict[str, Any]):
        """Initialize with venue-specific config dict from venues.yaml."""
        self.config = config
        self.enabled = config.get("enabled", False)
        self.symbols = config.get("symbols", [])
        self.fee_structure = config.get("fee_structure", {})
        self.risk_limits = config.get("risk_limits", {})
        self.max_leverage = config.get("max_leverage", 1)
        self._data_dir = Path(__file__).resolve().parent.parent.parent / "data"

    @abstractmethod
    def scan(self) -> list[Signal]:
        """Scan all configured symbols for trade signals.

        Returns a list of standardized Signal objects.
        Should be fast — load data from cache, compute indicators, check conditions.
        """
        ...

    @abstractmethod
    def get_regime(self) -> RegimeState:
        """Get current market regime for this venue."""
        ...

    @abstractmethod
    def get_positions(self) -> list[PositionInfo]:
        """Get current open positions on this venue."""
        ...

    @abstractmethod
    def execute(self, signal: Signal) -> dict[str, Any]:
        """Execute a trade based on a signal.

        In paper mode: record the trade.
        In live mode: send order to venue API.

        Returns execution result dict.
        """
        ...

    def get_fees(self, side: str = "taker") -> float:
        """Get fee percentage for a given side."""
        if side == "maker":
            return self.fee_structure.get("maker_pct", 0.0)
        return self.fee_structure.get("taker_pct", 0.0)

    def round_trip_fee(self) -> float:
        """Total fee for a round-trip trade (open + close)."""
        rt = self.fee_structure.get("round_trip_pct")
        if rt:
            return rt
        return self.get_fees("taker") * 2

    def max_positions(self) -> int:
        """Max open positions allowed."""
        return self.risk_limits.get("max_open_positions", 5)

    def daily_loss_limit_pct(self) -> float:
        """Daily loss limit as percentage."""
        return self.risk_limits.get("daily_loss_limit_pct", 5.0)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(enabled={self.enabled}, symbols={len(self.symbols)})"

    def load_ohlcv(self, symbol: str, timeframe: str = "4h") -> Optional[pd.DataFrame]:
        """Load OHLCV data from local parquet cache.

        Tries standard naming conventions:
          - binance_{symbol}_USDT_{timeframe_in_minutes}m.parquet
          - data/ohlcv/{timeframe}/binance_{symbol}_USDT_{tf}.parquet
        """
        tf_minutes = {"1h": "60m", "4h": "240m", "1d": "1440m", "15m": "15m"}
        tf_str = tf_minutes.get(timeframe, timeframe)

        # Clean symbol for file path
        clean_sym = symbol.replace("/", "_").replace("-", "_").split("USDT")[0].rstrip("_")

        candidates = [
            self._data_dir / f"binance_{clean_sym}_USDT_{tf_str}.parquet",
            self._data_dir / "ohlcv" / timeframe / f"binance_{clean_sym}_USDT_{tf_str}.parquet",
            self._data_dir / "ohlcv" / "1h" / f"binance_{clean_sym}_USDT_{tf_str}.parquet",
        ]

        for path in candidates:
            if path.exists():
                return pd.read_parquet(path)

        return None
