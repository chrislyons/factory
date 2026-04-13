
"""
BaseVenueBacktester — Unified foundation for all IG-88 backtesting engines.
Eliminates duplication across Spot, Perps, and Prediction markets.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import numpy as np
from src.quant.backtest_engine import Trade, ExitReason

@dataclass
class BacktestConfig:
    initial_capital: float
    kelly_fraction: float = 0.25
    max_position_pct: float = 10.0
    default_slippage_bps: float = 10.0

class BaseVenueBacktester:
    """
    Abstract base class for venue-specific backtesters.
    Handles sizing, friction, and basic trade lifecycle management.
    """
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.wallet = config.initial_capital
        self.initial_capital = config.initial_capital
        
        # Running stats for Kelly sizing
        self._win_count = 0
        self._loss_count = 0
        self._total_win_pct = 0.0
        self._total_loss_pct = 0.0
        self._trade_counter = 0

    def _next_trade_id(self, prefix: str) -> str:
        self._trade_counter += 1
        return f"{prefix}-{self._trade_counter:05d}"

    def compute_position_size(self, current_wallet: float) -> float:
        """
        Standardized Quarter-Kelly position sizing.
        Returns the notional USD amount to risk.
        """
        total_trades = self._win_count + self._loss_count
        if total_trades < 10:
            # Conservative start: 2% of wallet
            return min(current_wallet * 0.02, current_wallet)
        
        win_rate = self._win_count / total_trades
        avg_win = self._total_win_pct / self._win_count if self._win_count > 0 else 0.01
        avg_loss = self._total_loss_pct / self._loss_count if self._loss_count > 0 else 0.01
        
        if avg_loss == 0 or win_rate <= 0:
            return 0.0
        
        b = avg_win / avg_loss
        q = 1.0 - win_rate
        f_kelly = (b * win_rate - q) / b
        
        if f_kelly <= 0:
            return 0.0
            
        f_sized = f_kelly * self.config.kelly_fraction
        position_usd = current_wallet * f_sized
        max_usd = current_wallet * (self.config.max_position_pct / 100.0)
        
        return min(position_usd, max_usd)

    def apply_friction(self, price: float, side: str) -> float:
        """
        Applies the standardized slippage haircut.
        Buy: Price increases. Sell: Price decreases.
        """
        bps_decimal = self.config.default_slippage_bps / 10000.0
        if side == "long" or side == "buy":
            return price * (1.0 + bps_decimal)
        else:
            return price * (1.0 - bps_decimal)

    def record_outcome(self, pnl_pct: float):
        """Updates running stats for Kelly sizing."""
        if pnl_pct > 0:
            self._win_count += 1
            self._total_win_pct += pnl_pct
        else:
            self._loss_count += 1
            self._total_loss_pct += abs(pnl_pct)

    def validate_trade_params(self, params: dict) -> bool:
        """Ensure mandatory parameters (TP/SL) are present."""
        required = ["stop_level", "target_level"]
        return all(k in params for k in required)
