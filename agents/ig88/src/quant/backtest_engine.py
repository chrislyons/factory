"""Unified backtesting engine for IG-88 multi-venue trading system.

Supports: Polymarket, Kraken spot, Jupiter Perps, Solana DEX.
Provides: expectancy, Sharpe, max drawdown, p-values, variance drag,
Kelly sizing, regime filtering, and walk-forward validation.

Usage:
    from src.quant.backtest_engine import BacktestEngine, Trade
    from src.trading.config import load_config

    cfg = load_config()
    engine = BacktestEngine(cfg)
    engine.add_trade(trade)
    stats = engine.compute_stats()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import math

import numpy as np

from src.quant.regime import RegimeState


def _ttest_1samp(data: np.ndarray, popmean: float = 0) -> tuple[float, float]:
    """One-sample t-test without scipy dependency.
    Returns (t_statistic, two_sided_p_value).
    """
    n = len(data)
    if n < 2:
        return 0.0, 1.0
    mean = float(np.mean(data))
    se = float(np.std(data, ddof=1)) / math.sqrt(n)
    if se == 0:
        return 0.0, 1.0
    t = (mean - popmean) / se
    # Approximate p-value using normal distribution for large n,
    # or use the regularized incomplete beta function for small n.
    df = n - 1
    # Use the approximation: p ≈ erfc(|t|/sqrt(2)) for df > 30
    if df > 30:
        p = math.erfc(abs(t) / math.sqrt(2))
    else:
        # For smaller samples, use a conservative approximation
        # Based on Abramowitz and Stegun 26.2.17
        x = df / (df + t * t)
        # Rough p-value via normal approx adjusted for df
        z = abs(t) * (1 - 1 / (4 * df))
        p = math.erfc(z / math.sqrt(2))
    return float(t), float(p)


class TradeOutcome(Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


class ExitReason(Enum):
    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    TIME_STOP = "time_stop"
    VOLUME_STOP = "volume_stop"
    MANUAL = "manual"
    BORROW_FEE = "borrow_fee"
    REGIME_EXIT = "regime_exit"
    RESOLUTION = "resolution"  # Polymarket


@dataclass
class Trade:
    """A single trade record across any venue."""
    trade_id: str
    venue: str                          # polymarket | kraken_spot | jupiter_perps | solana_dex
    strategy: str
    pair: str                           # BTC/USD, SOL-PERP, market question, token address
    entry_timestamp: datetime
    entry_price: float
    position_size_usd: float
    regime_state: RegimeState
    side: str = "long"                  # long | short | buy_yes | buy_no | sell_yes | sell_no
    leverage: float = 1.0

    # Set on exit
    exit_timestamp: datetime | None = None
    exit_price: float | None = None
    outcome: TradeOutcome = TradeOutcome.OPEN
    exit_reason: ExitReason | None = None

    # Risk levels
    stop_level: float | None = None
    target_level: float | None = None

    # Venue-specific
    llm_estimate: float | None = None   # Polymarket: LLM probability
    market_price: float | None = None   # Polymarket: market price at entry
    narrative_category: str | None = None  # Solana DEX
    brier_score: float | None = None    # Polymarket: computed at resolution
    fees_paid: float = 0.0
    borrow_fees: float = 0.0           # Jupiter Perps

    # Computed
    r_multiple: float | None = None
    pnl_usd: float | None = None
    pnl_pct: float | None = None
    hold_duration_hours: float | None = None

    notes: str = ""

    def close(
        self,
        exit_price: float,
        exit_timestamp: datetime,
        exit_reason: ExitReason,
        fees: float = 0.0,
        borrow_fees: float = 0.0,
    ) -> None:
        """Close the trade and compute outcome metrics."""
        self.exit_price = exit_price
        self.exit_timestamp = exit_timestamp
        self.exit_reason = exit_reason
        self.fees_paid += fees
        self.borrow_fees += borrow_fees

        # P&L
        if self.side in ("long", "buy_yes"):
            raw_pnl = (exit_price - self.entry_price) / self.entry_price
        elif self.side in ("short", "sell_yes", "buy_no", "sell_no"):
            raw_pnl = (self.entry_price - exit_price) / self.entry_price
        else:
            raw_pnl = (exit_price - self.entry_price) / self.entry_price

        self.pnl_pct = (raw_pnl * self.leverage) - (
            (self.fees_paid + self.borrow_fees) / self.position_size_usd
        )
        self.pnl_usd = self.pnl_pct * self.position_size_usd

        # R-multiple
        if self.stop_level and self.entry_price != self.stop_level:
            risk_per_unit = abs(self.entry_price - self.stop_level)
            reward_per_unit = exit_price - self.entry_price
            if self.side in ("short", "sell_yes", "buy_no", "sell_no"):
                reward_per_unit = self.entry_price - exit_price
            self.r_multiple = reward_per_unit / risk_per_unit
        else:
            self.r_multiple = self.pnl_pct / 0.01 if self.pnl_pct else 0.0

        # Outcome
        if self.pnl_usd > 0.01:
            self.outcome = TradeOutcome.WIN
        elif self.pnl_usd < -0.01:
            self.outcome = TradeOutcome.LOSS
        else:
            self.outcome = TradeOutcome.BREAKEVEN

        # Duration
        if self.exit_timestamp and self.entry_timestamp:
            delta = self.exit_timestamp - self.entry_timestamp
            self.hold_duration_hours = delta.total_seconds() / 3600

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "venue": self.venue,
            "strategy": self.strategy,
            "pair": self.pair,
            "side": self.side,
            "leverage": self.leverage,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "entry_price": self.entry_price,
            "exit_timestamp": self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            "exit_price": self.exit_price,
            "position_size_usd": self.position_size_usd,
            "regime_state": self.regime_state.value,
            "outcome": self.outcome.value,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "r_multiple": self.r_multiple,
            "pnl_usd": self.pnl_usd,
            "pnl_pct": self.pnl_pct,
            "hold_duration_hours": self.hold_duration_hours,
            "fees_paid": self.fees_paid,
            "borrow_fees": self.borrow_fees,
            "llm_estimate": self.llm_estimate,
            "market_price": self.market_price,
            "brier_score": self.brier_score,
            "narrative_category": self.narrative_category,
            "notes": self.notes,
        }


@dataclass
class BacktestStats:
    """Statistical summary of a backtest run."""
    venue: str
    strategy: str
    n_trades: int
    n_wins: int
    n_losses: int
    n_breakeven: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy_per_trade: float         # E = (WR × AvgWin) - (LR × AvgLoss)
    expectancy_r: float                 # In R-multiples
    total_pnl_pct: float
    total_pnl_usd: float
    total_fees_usd: float
    sharpe_ratio: float                 # Annualized
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_hours: float
    avg_hold_hours: float
    profit_factor: float                # Gross wins / gross losses
    # Statistical tests
    p_value: float                      # Is expectancy significantly > 0?
    t_statistic: float
    # Variance drag
    arithmetic_return: float
    geometric_return: float
    variance_drag: float                # arithmetic - geometric
    geometric_positive: bool            # Pass/fail
    # Brier (Polymarket only)
    avg_brier_score: float | None = None
    # Per-pair breakdown
    per_pair: dict[str, dict[str, Any]] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"=== Backtest: {self.venue} / {self.strategy} ===",
            f"Trades: {self.n_trades} (W:{self.n_wins} L:{self.n_losses} BE:{self.n_breakeven})",
            f"Win Rate: {self.win_rate:.1%}",
            f"Expectancy: {self.expectancy_per_trade:.4f} per trade ({self.expectancy_r:.2f}R)",
            f"Total P&L: {self.total_pnl_pct:.2%} (${self.total_pnl_usd:,.2f})",
            f"Total Fees: ${self.total_fees_usd:,.2f}",
            f"Sharpe: {self.sharpe_ratio:.2f} | Sortino: {self.sortino_ratio:.2f}",
            f"Max DD: {self.max_drawdown_pct:.2%} ({self.max_drawdown_duration_hours:.1f}h)",
            f"Profit Factor: {self.profit_factor:.2f}",
            f"Avg Hold: {self.avg_hold_hours:.1f}h",
            f"p-value: {self.p_value:.4f} (t={self.t_statistic:.2f})",
            f"Variance Drag: {self.variance_drag:.6f}",
            f"  Arithmetic: {self.arithmetic_return:.6f}",
            f"  Geometric:  {self.geometric_return:.6f} ({'PASS' if self.geometric_positive else 'FAIL'})",
        ]
        if self.avg_brier_score is not None:
            lines.append(f"Brier Score: {self.avg_brier_score:.4f}")
        return "\n".join(lines)


class BacktestEngine:
    """Multi-venue backtesting engine with statistical analysis."""

    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.trades: list[Trade] = []

    def add_trade(self, trade: Trade) -> None:
        self.trades.append(trade)

    def add_trades(self, trades: list[Trade]) -> None:
        self.trades.extend(trades)

    def closed_trades(self, venue: str | None = None, strategy: str | None = None,
                      pair: str | None = None) -> list[Trade]:
        """Get closed trades, optionally filtered."""
        result = [t for t in self.trades if t.outcome != TradeOutcome.OPEN]
        if venue:
            result = [t for t in result if t.venue == venue]
        if strategy:
            result = [t for t in result if t.strategy == strategy]
        if pair:
            result = [t for t in result if t.pair == pair]
        return result

    def compute_stats(
        self,
        venue: str | None = None,
        strategy: str | None = None,
        annualization_factor: float = 252,  # Trading days per year
    ) -> BacktestStats:
        """Compute comprehensive statistics for closed trades."""
        trades = self.closed_trades(venue=venue, strategy=strategy)
        n = len(trades)

        if n == 0:
            return BacktestStats(
                venue=venue or "all",
                strategy=strategy or "all",
                n_trades=0, n_wins=0, n_losses=0, n_breakeven=0,
                win_rate=0, avg_win_pct=0, avg_loss_pct=0,
                expectancy_per_trade=0, expectancy_r=0,
                total_pnl_pct=0, total_pnl_usd=0, total_fees_usd=0,
                sharpe_ratio=0, sortino_ratio=0,
                max_drawdown_pct=0, max_drawdown_duration_hours=0,
                avg_hold_hours=0, profit_factor=0,
                p_value=1.0, t_statistic=0,
                arithmetic_return=0, geometric_return=0,
                variance_drag=0, geometric_positive=False,
            )

        # Counts
        wins = [t for t in trades if t.outcome == TradeOutcome.WIN]
        losses = [t for t in trades if t.outcome == TradeOutcome.LOSS]
        breakevens = [t for t in trades if t.outcome == TradeOutcome.BREAKEVEN]

        win_rate = len(wins) / n if n > 0 else 0

        # Returns
        returns = np.array([t.pnl_pct for t in trades if t.pnl_pct is not None])
        win_returns = np.array([t.pnl_pct for t in wins if t.pnl_pct is not None])
        loss_returns = np.array([t.pnl_pct for t in losses if t.pnl_pct is not None])

        avg_win = float(np.mean(win_returns)) if len(win_returns) > 0 else 0
        avg_loss = float(np.mean(np.abs(loss_returns))) if len(loss_returns) > 0 else 0

        # Expectancy
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # R-multiples
        r_multiples = np.array([t.r_multiple for t in trades if t.r_multiple is not None])
        expectancy_r = float(np.mean(r_multiples)) if len(r_multiples) > 0 else 0

        # P&L
        total_pnl_usd = sum(t.pnl_usd for t in trades if t.pnl_usd is not None)
        total_fees = sum(t.fees_paid + t.borrow_fees for t in trades)
        total_pnl_pct = float(np.sum(returns)) if len(returns) > 0 else 0

        # Sharpe ratio
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(annualization_factor)
        else:
            sharpe = 0.0

        # Sortino ratio (downside deviation)
        downside = returns[returns < 0]
        if len(downside) > 1 and np.std(downside) > 0:
            sortino = (np.mean(returns) / np.std(downside)) * np.sqrt(annualization_factor)
        else:
            sortino = sharpe  # Fall back to Sharpe if no downside

        # Max drawdown
        equity_curve = np.cumsum(returns)
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = running_max - equity_curve
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0

        # Max drawdown duration
        dd_duration = 0.0
        if max_dd > 0:
            peak_idx = int(np.argmax(drawdowns))
            # Find when peak was established
            peak_start = 0
            for i in range(peak_idx, -1, -1):
                if drawdowns[i] == 0:
                    peak_start = i
                    break
            # Sum hold durations in drawdown period
            for i in range(peak_start, min(peak_idx + 1, len(trades))):
                if trades[i].hold_duration_hours:
                    dd_duration += trades[i].hold_duration_hours

        # Avg hold
        holds = [t.hold_duration_hours for t in trades if t.hold_duration_hours]
        avg_hold = float(np.mean(holds)) if holds else 0

        # Profit factor
        gross_wins = float(np.sum(win_returns)) if len(win_returns) > 0 else 0
        gross_losses = float(np.sum(np.abs(loss_returns))) if len(loss_returns) > 0 else 0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

        # Statistical significance: one-sample t-test (H0: mean return = 0)
        if len(returns) > 1:
            t_stat, p_val = _ttest_1samp(returns, 0)
            # One-sided: we only care if expectancy > 0
            p_val = p_val / 2 if t_stat > 0 else 1 - p_val / 2
        else:
            t_stat, p_val = 0.0, 1.0

        # Variance drag: geometric_return = arithmetic_return - (sigma^2 / 2)
        arith_return = float(np.mean(returns)) if len(returns) > 0 else 0
        sigma = float(np.std(returns)) if len(returns) > 1 else 0
        var_drag = (sigma ** 2) / 2
        geo_return = arith_return - var_drag

        # Brier score (Polymarket)
        brier_scores = [t.brier_score for t in trades if t.brier_score is not None]
        avg_brier = float(np.mean(brier_scores)) if brier_scores else None

        # Per-pair breakdown
        per_pair: dict[str, dict[str, Any]] = {}
        pairs_seen = set(t.pair for t in trades)
        for p in pairs_seen:
            pair_trades = [t for t in trades if t.pair == p]
            pair_returns = [t.pnl_pct for t in pair_trades if t.pnl_pct is not None]
            pair_wins = [t for t in pair_trades if t.outcome == TradeOutcome.WIN]
            per_pair[p] = {
                "n_trades": len(pair_trades),
                "win_rate": len(pair_wins) / len(pair_trades) if pair_trades else 0,
                "total_pnl_pct": sum(pair_returns),
                "avg_pnl_pct": float(np.mean(pair_returns)) if pair_returns else 0,
            }

        return BacktestStats(
            venue=venue or "all",
            strategy=strategy or "all",
            n_trades=n,
            n_wins=len(wins),
            n_losses=len(losses),
            n_breakeven=len(breakevens),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            expectancy_per_trade=expectancy,
            expectancy_r=expectancy_r,
            total_pnl_pct=total_pnl_pct,
            total_pnl_usd=total_pnl_usd,
            total_fees_usd=total_fees,
            sharpe_ratio=float(sharpe),
            sortino_ratio=float(sortino),
            max_drawdown_pct=max_dd,
            max_drawdown_duration_hours=dd_duration,
            avg_hold_hours=avg_hold,
            profit_factor=profit_factor,
            p_value=float(p_val),
            t_statistic=float(t_stat),
            arithmetic_return=arith_return,
            geometric_return=geo_return,
            variance_drag=var_drag,
            geometric_positive=geo_return > 0,
            avg_brier_score=avg_brier,
            per_pair=per_pair,
        )

    def graduation_check(self, stats: BacktestStats, venue: str) -> dict[str, Any]:
        """Check if a strategy meets graduation criteria (paper → live).

        Returns a dict with each criterion and pass/fail status.
        """
        from src.trading.config import load_config
        cfg = load_config()
        grad = cfg.graduation

        checks = {
            "min_trades": {
                "required": grad.min_trades,
                "actual": stats.n_trades,
                "pass": stats.n_trades >= grad.min_trades,
            },
            "positive_expectancy": {
                "required": "E > 0",
                "actual": stats.expectancy_per_trade,
                "pass": stats.expectancy_per_trade > 0,
            },
            "statistical_significance": {
                "required": f"p < {grad.significance_p}",
                "actual": stats.p_value,
                "pass": stats.p_value < grad.significance_p,
            },
            "geometric_return_positive": {
                "required": "geometric > 0",
                "actual": stats.geometric_return,
                "pass": stats.geometric_return > 0,
            },
            "max_drawdown": {
                "required": f"< {grad.max_paper_drawdown_pct}%",
                "actual": stats.max_drawdown_pct * 100,
                "pass": stats.max_drawdown_pct < grad.max_paper_drawdown_pct / 100,
            },
            "chris_approval": {
                "required": True,
                "actual": False,
                "pass": False,  # Always requires manual approval
            },
        }

        if venue == "polymarket" and stats.avg_brier_score is not None:
            checks["brier_score"] = {
                "required": f"< {grad.brier_target}",
                "actual": stats.avg_brier_score,
                "pass": stats.avg_brier_score < grad.brier_target,
            }

        return {
            "venue": venue,
            "strategy": stats.strategy,
            "all_pass": all(c["pass"] for c in checks.values() if c != checks["chris_approval"]),
            "ready_for_review": all(
                c["pass"] for k, c in checks.items() if k != "chris_approval"
            ),
            "checks": checks,
        }

    def kelly_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.25,
        wallet_usd: float = 1000.0,
        max_position_pct: float = 10.0,
    ) -> float:
        """Calculate Kelly-criterion position size.

        Returns position size in USD, capped at max_position_pct of wallet.
        Uses fractional Kelly (default quarter-Kelly for first 200 trades).
        """
        if avg_loss == 0 or win_rate <= 0:
            return 0.0

        # Kelly fraction: f = (bp - q) / b
        # where b = avg_win/avg_loss, p = win_rate, q = 1-p
        b = avg_win / avg_loss
        q = 1 - win_rate
        f_kelly = (b * win_rate - q) / b

        if f_kelly <= 0:
            return 0.0  # No edge — don't trade

        f_sized = f_kelly * fraction
        position_usd = wallet_usd * f_sized
        max_usd = wallet_usd * (max_position_pct / 100)

        return min(position_usd, max_usd)
