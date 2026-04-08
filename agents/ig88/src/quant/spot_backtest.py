"""Kraken Spot backtester — event-driven and regime-momentum strategies.

Two strategies for Kraken spot (no leverage, no shorts):

1. EventDrivenBacktester:
   - Regime-gated (RISK_ON only)
   - Catalyst events simulated as random signals with configurable hit rate
   - Config pair list from trading.yaml (36 pairs)
   - Fees: maker 0.16%, taker 0.26%, prefers limit orders
   - Min hold 4h, reentry cooldown 2h
   - Daily loss halt at 3% of wallet
   - Quarter-Kelly position sizing

2. RegimeMomentumBacktester:
   - Regime-gated (RISK_ON only)
   - Momentum: buys when price crosses above 20-period MA, sells when below
   - ATR-based stops instead of flat % stops
   - Same fee and guardrail structure

Both accept OHLCV data as numpy arrays and produce Trade objects
for the unified BacktestEngine.

Usage:
    from src.quant.spot_backtest import EventDrivenBacktester, RegimeMomentumBacktester
    from src.quant.backtest_engine import BacktestEngine

    bt = EventDrivenBacktester(initial_capital=10000.0)
    trades = bt.run(timestamps, opens, highs, lows, closes, volumes)
    engine = BacktestEngine(initial_capital=10000.0)
    engine.add_trades(trades)
    stats = engine.compute_stats(venue="kraken_spot")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from src.quant.backtest_engine import (
    BacktestEngine,
    BacktestStats,
    ExitReason,
    Trade,
    TradeOutcome,
)
from src.quant.regime import RegimeAssessment, RegimeState, regime_allows_venue


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENUE = "kraken_spot"
MAKER_FEE_PCT = 0.0016      # 0.16%
TAKER_FEE_PCT = 0.0026      # 0.26%
MIN_HOLD_HOURS = 4.0
REENTRY_COOLDOWN_HOURS = 2.0
DAILY_LOSS_HALT_PCT = 0.03   # 3% of wallet
KELLY_FRACTION = 0.25        # Quarter-Kelly

# Default pairs — loaded from config when available, fallback here
DEFAULT_PAIRS = [
    "BTC/USD", "ETH/USDT", "SOL/USDT", "JUP/USDT", "LINK/USDT",
    "RENDER/USDT", "POL/USDT", "HOT/USDT", "NEAR/USDT", "THETA/USDT",
    "AR/USDT", "FIL/USDT", "INJ/USDT", "SEI/USDT", "AKT/USDT",
    "IP/USDT", "DYM/USDT", "PYTH/USDT", "TIA/USDT", "UNI/USDT",
    "FET/USDT", "GRT/USDT", "W/USDT", "DOGE/USDT", "WIF/USDT",
    "BONK/USDT", "MOODENG/USDT", "KAS/USDT", "XRP/USDT", "AVAX/USDT",
    "ORDI/USDT", "TAO/USDT", "GTC/USDT", "ATOM/USDT", "OSMO/USDT",
    "AUDIO/USDT",
]


def _load_pairs() -> list[str]:
    """Try to load pairs from config; fall back to defaults."""
    try:
        from src.trading.config import load_config
        cfg = load_config()
        pairs = cfg.pairs_for_venue("kraken_spot")
        if pairs:
            return pairs
    except Exception:
        pass
    return DEFAULT_PAIRS


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

def generate_synthetic_ohlcv(
    n_bars: int = 2000,
    base_price: float = 150.0,
    volatility: float = 0.002,
    trend: float = 0.00005,
    bar_interval_hours: float = 1.0,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic OHLCV data for testing.

    Returns (timestamps, opens, highs, lows, closes, volumes) as numpy arrays.
    Timestamps are Unix epoch seconds (float64).
    """
    rng = np.random.default_rng(seed)

    # Generate close prices via geometric Brownian motion
    log_returns = rng.normal(trend, volatility, n_bars)
    cum_returns = np.cumsum(log_returns)
    closes = base_price * np.exp(cum_returns)

    # Derive OHLC from closes
    opens = np.empty(n_bars)
    highs = np.empty(n_bars)
    lows = np.empty(n_bars)

    opens[0] = base_price
    for i in range(1, n_bars):
        opens[i] = closes[i - 1]

    # Intra-bar range: random excursion around open-close range
    for i in range(n_bars):
        bar_range = abs(closes[i] - opens[i])
        extension = rng.exponential(max(bar_range * 0.5, volatility * base_price))
        mid = (opens[i] + closes[i]) / 2.0
        highs[i] = max(opens[i], closes[i]) + extension * rng.uniform(0.2, 1.0)
        lows[i] = min(opens[i], closes[i]) - extension * rng.uniform(0.2, 1.0)

    # Volume: base + noise, correlated with volatility
    abs_returns = np.abs(log_returns)
    vol_factor = abs_returns / (np.mean(abs_returns) + 1e-10)
    base_volume = 1_000_000.0
    volumes = base_volume * (1.0 + vol_factor) * rng.uniform(0.5, 1.5, n_bars)

    # Timestamps: starting from 2025-01-01 00:00 UTC
    start_epoch = datetime(2025, 1, 1, 0, 0, 0).timestamp()
    interval_sec = bar_interval_hours * 3600.0
    timestamps = np.array(
        [start_epoch + i * interval_sec for i in range(n_bars)],
        dtype=np.float64,
    )

    return timestamps, opens, highs, lows, closes, volumes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average. First (period-1) values are NaN."""
    sma = np.full(len(data), np.nan)
    if len(data) < period:
        return sma
    cumsum = np.cumsum(data)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))) / period
    return sma


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = 14) -> np.ndarray:
    """Average True Range from numpy arrays. First period values are NaN."""
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        alpha = 1.0 / period
        for i in range(period, n):
            atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
    return atr


def _compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index from numpy arrays."""
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n < period + 1:
        return rsi

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def _kelly_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    wallet_usd: float,
    fraction: float = KELLY_FRACTION,
    max_position_pct: float = 10.0,
) -> float:
    """Quarter-Kelly position sizing. Returns USD size."""
    if avg_loss == 0 or win_rate <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1.0 - win_rate
    f_kelly = (b * win_rate - q) / b
    if f_kelly <= 0:
        return 0.0
    f_sized = f_kelly * fraction
    position_usd = wallet_usd * f_sized
    max_usd = wallet_usd * (max_position_pct / 100.0)
    return min(position_usd, max_usd)


def _simulate_regime_series(
    n_bars: int,
    risk_on_pct: float = 0.55,
    regime_duration_bars: int = 50,
    seed: int = 99,
) -> np.ndarray:
    """Generate a synthetic regime state series.

    Returns array of RegimeState values with realistic persistence
    (regimes last regime_duration_bars on average).
    """
    rng = np.random.default_rng(seed)
    states = [RegimeState.RISK_ON, RegimeState.NEUTRAL, RegimeState.RISK_OFF]
    weights = np.array([risk_on_pct, (1 - risk_on_pct) * 0.6, (1 - risk_on_pct) * 0.4])
    weights /= weights.sum()

    regime_arr = np.empty(n_bars, dtype=object)
    current = rng.choice(states, p=weights)
    i = 0
    while i < n_bars:
        duration = max(1, int(rng.exponential(regime_duration_bars)))
        end = min(i + duration, n_bars)
        regime_arr[i:end] = current
        i = end
        current = rng.choice(states, p=weights)
    return regime_arr


# ---------------------------------------------------------------------------
# Strategy 1: Event-Driven Backtester
# ---------------------------------------------------------------------------

class EventDrivenBacktester:
    """Kraken spot backtester using catalyst event signals.

    In live trading, events come from news/sentiment analysis.
    In backtest, events are simulated as random signals with
    configurable hit rate and win probability.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        event_hit_rate: float = 0.03,
        event_win_rate: float = 0.55,
        event_avg_gain_pct: float = 2.5,
        event_avg_loss_pct: float = 1.5,
        pairs: list[str] | None = None,
        bar_interval_hours: float = 1.0,
        seed: int = 42,
    ):
        self.initial_capital = initial_capital
        self.wallet = initial_capital
        self.event_hit_rate = event_hit_rate
        self.event_win_rate = event_win_rate
        self.event_avg_gain_pct = event_avg_gain_pct
        self.event_avg_loss_pct = event_avg_loss_pct
        self.pairs = pairs or _load_pairs()
        self.bar_interval_hours = bar_interval_hours
        self.seed = seed

        # Running state
        self._daily_pnl: float = 0.0
        self._daily_halted: bool = False
        self._current_day: int = -1
        self._last_exit_bar: int = -999
        self._trade_counter: int = 0

        # Track historical win/loss for adaptive Kelly
        self._win_count: int = 0
        self._loss_count: int = 0
        self._total_win_pct: float = 0.0
        self._total_loss_pct: float = 0.0

    def _get_fee(self, use_limit: bool = True) -> float:
        """Return fee percentage as decimal."""
        return MAKER_FEE_PCT if use_limit else TAKER_FEE_PCT

    def _next_trade_id(self) -> str:
        self._trade_counter += 1
        return f"KS-EVT-{self._trade_counter:05d}"

    def _check_daily_halt(self, bar_idx: int, timestamps: np.ndarray) -> bool:
        """Reset daily tracking at day boundary; check halt."""
        day = int(timestamps[bar_idx] // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_pnl = 0.0
            self._daily_halted = False
        return self._daily_halted

    def _position_size(self) -> float:
        """Compute position size via quarter-Kelly, falling back to 2% of wallet."""
        if self._win_count + self._loss_count < 10:
            # Not enough history; use conservative fixed fraction
            return min(self.wallet * 0.02, self.wallet)

        wr = self._win_count / (self._win_count + self._loss_count)
        avg_w = self._total_win_pct / self._win_count if self._win_count > 0 else 0.01
        avg_l = self._total_loss_pct / self._loss_count if self._loss_count > 0 else 0.01
        return _kelly_position_size(wr, avg_w, avg_l, self.wallet)

    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        pair: str = "SOL/USDT",
        regime_states: np.ndarray | None = None,
    ) -> list[Trade]:
        """Run event-driven backtest on OHLCV data.

        Args:
            timestamps: Unix epoch seconds (float64)
            opens, highs, lows, closes, volumes: OHLCV arrays
            pair: Trading pair name
            regime_states: Array of RegimeState per bar.
                If None, generates synthetic regime series.

        Returns:
            List of closed Trade objects.
        """
        n = len(timestamps)
        rng = np.random.default_rng(self.seed)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 7)

        # Precompute ATR for stop placement
        atr = _compute_atr(highs, lows, closes, period=14)

        trades: list[Trade] = []
        min_hold_bars = max(1, int(MIN_HOLD_HOURS / self.bar_interval_hours))
        cooldown_bars = max(1, int(REENTRY_COOLDOWN_HOURS / self.bar_interval_hours))

        i = 20  # Skip warmup for ATR
        while i < n - min_hold_bars - 1:
            # Daily halt check
            if self._check_daily_halt(i, timestamps):
                i += 1
                continue

            # Regime gate: RISK_ON only
            if regime_states[i] != RegimeState.RISK_ON:
                i += 1
                continue

            # Cooldown check
            if i - self._last_exit_bar < cooldown_bars:
                i += 1
                continue

            # Event signal: random catalyst with configurable hit rate
            if rng.random() > self.event_hit_rate:
                i += 1
                continue

            # Signal fires — enter at next bar open
            entry_bar = i + 1
            if entry_bar >= n:
                break

            entry_price = opens[entry_bar]
            entry_time = datetime.fromtimestamp(timestamps[entry_bar])

            # Position sizing
            pos_size = self._position_size()
            if pos_size < 1.0:
                i += 1
                continue

            # Entry fee (limit order preferred)
            entry_fee = pos_size * self._get_fee(use_limit=True)

            # ATR-based stop: 2x ATR below entry
            atr_val = atr[i] if not np.isnan(atr[i]) else atr[entry_bar]
            if np.isnan(atr_val):
                i += 1
                continue
            stop_level = entry_price - 2.0 * atr_val

            # Target: 3x ATR above entry (1.5:1 reward/risk)
            target_level = entry_price + 3.0 * atr_val

            trade = Trade(
                trade_id=self._next_trade_id(),
                venue=VENUE,
                strategy="event_driven",
                pair=pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side="long",
                leverage=1.0,
                stop_level=stop_level,
                target_level=target_level,
                fees_paid=entry_fee,
            )

            # Simulate hold
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break

                # Check regime exit: if regime leaves RISK_ON, exit at close
                if regime_states[bar] != RegimeState.RISK_ON and j >= min_hold_bars:
                    exit_bar = bar
                    exit_price = closes[bar]
                    exit_reason = ExitReason.REGIME_EXIT
                    break

                # Check stop hit (intra-bar via low)
                if lows[bar] <= stop_level:
                    exit_bar = bar
                    exit_price = stop_level
                    exit_reason = ExitReason.STOP_HIT
                    break

                # Check target hit (intra-bar via high)
                if highs[bar] >= target_level:
                    exit_bar = bar
                    exit_price = target_level
                    exit_reason = ExitReason.TARGET_HIT
                    break

                # Time stop: exit after min hold if no signal persists
                if j >= min_hold_bars:
                    # Determine event outcome probabilistically
                    if rng.random() < self.event_win_rate:
                        # Winning catalyst: let it run a bit more
                        gain_mult = rng.uniform(0.5, 2.0)
                        simulated_exit = entry_price * (1.0 + self.event_avg_gain_pct / 100.0 * gain_mult)
                        exit_price = min(simulated_exit, highs[bar])
                    else:
                        loss_mult = rng.uniform(0.3, 1.5)
                        simulated_exit = entry_price * (1.0 - self.event_avg_loss_pct / 100.0 * loss_mult)
                        exit_price = max(simulated_exit, lows[bar])
                    exit_bar = bar
                    exit_reason = ExitReason.TIME_STOP
                    break

            # Exit fee
            exit_fee = pos_size * self._get_fee(use_limit=True)
            exit_time = datetime.fromtimestamp(timestamps[min(exit_bar, n - 1)])

            trade.close(
                exit_price=exit_price,
                exit_timestamp=exit_time,
                exit_reason=exit_reason,
                fees=exit_fee,
            )

            # Update wallet and daily tracking
            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd
                self._daily_pnl += trade.pnl_usd

                # Update win/loss stats for Kelly
                if trade.outcome == TradeOutcome.WIN and trade.pnl_pct is not None:
                    self._win_count += 1
                    self._total_win_pct += trade.pnl_pct
                elif trade.outcome == TradeOutcome.LOSS and trade.pnl_pct is not None:
                    self._loss_count += 1
                    self._total_loss_pct += abs(trade.pnl_pct)

            # Daily loss halt check
            if self._daily_pnl < -(self.initial_capital * DAILY_LOSS_HALT_PCT):
                self._daily_halted = True

            self._last_exit_bar = exit_bar
            trades.append(trade)

            # Advance past the trade
            i = exit_bar + cooldown_bars

        return trades

    def run_walk_forward(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        pair: str = "SOL/USDT",
        train_pct: float = 0.70,
        regime_states: np.ndarray | None = None,
    ) -> tuple[list[Trade], list[Trade], BacktestStats, BacktestStats]:
        """Run walk-forward validation: train on first 70%, test on last 30%.

        Returns (train_trades, test_trades, train_stats, test_stats).
        """
        n = len(timestamps)
        split = int(n * train_pct)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 7)

        # Train phase
        self.wallet = self.initial_capital
        self._daily_pnl = 0.0
        self._daily_halted = False
        self._current_day = -1
        self._last_exit_bar = -999
        self._win_count = 0
        self._loss_count = 0
        self._total_win_pct = 0.0
        self._total_loss_pct = 0.0

        train_trades = self.run(
            timestamps[:split], opens[:split], highs[:split],
            lows[:split], closes[:split], volumes[:split],
            pair=pair, regime_states=regime_states[:split],
        )

        train_engine = BacktestEngine(self.initial_capital)
        train_engine.add_trades(train_trades)
        train_stats = train_engine.compute_stats(venue=VENUE, strategy="event_driven")

        # Test phase: keep Kelly stats from training
        test_trades = self.run(
            timestamps[split:], opens[split:], highs[split:],
            lows[split:], closes[split:], volumes[split:],
            pair=pair, regime_states=regime_states[split:],
        )

        test_engine = BacktestEngine(self.initial_capital)
        test_engine.add_trades(test_trades)
        test_stats = test_engine.compute_stats(venue=VENUE, strategy="event_driven")

        return train_trades, test_trades, train_stats, test_stats


# ---------------------------------------------------------------------------
# Strategy 2: Regime-Momentum Backtester
# ---------------------------------------------------------------------------

class RegimeMomentumBacktester:
    """Kraken spot backtester using momentum with regime filter.

    Buys when price crosses above 20-period MA (momentum entry).
    Sells when price crosses below 20-period MA or ATR stop is hit.
    Only trades during RISK_ON regime.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        ma_period: int = 20,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
        pairs: list[str] | None = None,
        bar_interval_hours: float = 1.0,
        seed: int = 101,
    ):
        self.initial_capital = initial_capital
        self.wallet = initial_capital
        self.ma_period = ma_period
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult
        self.pairs = pairs or _load_pairs()
        self.bar_interval_hours = bar_interval_hours
        self.seed = seed

        self._daily_pnl: float = 0.0
        self._daily_halted: bool = False
        self._current_day: int = -1
        self._last_exit_bar: int = -999
        self._trade_counter: int = 0
        self._win_count: int = 0
        self._loss_count: int = 0
        self._total_win_pct: float = 0.0
        self._total_loss_pct: float = 0.0

    def _next_trade_id(self) -> str:
        self._trade_counter += 1
        return f"KS-MOM-{self._trade_counter:05d}"

    def _check_daily_halt(self, bar_idx: int, timestamps: np.ndarray) -> bool:
        day = int(timestamps[bar_idx] // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_pnl = 0.0
            self._daily_halted = False
        return self._daily_halted

    def _position_size(self) -> float:
        if self._win_count + self._loss_count < 10:
            return min(self.wallet * 0.02, self.wallet)
        wr = self._win_count / (self._win_count + self._loss_count)
        avg_w = self._total_win_pct / self._win_count if self._win_count > 0 else 0.01
        avg_l = self._total_loss_pct / self._loss_count if self._loss_count > 0 else 0.01
        return _kelly_position_size(wr, avg_w, avg_l, self.wallet)

    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        pair: str = "SOL/USDT",
        regime_states: np.ndarray | None = None,
    ) -> list[Trade]:
        """Run momentum backtest.

        Entry: price crosses above MA from below (bullish crossover).
        Exit: ATR stop, ATR target, MA crossdown, or regime exit.
        """
        n = len(timestamps)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 3)

        # Precompute indicators
        sma = _compute_sma(closes, self.ma_period)
        atr = _compute_atr(highs, lows, closes, self.atr_period)

        trades: list[Trade] = []
        min_hold_bars = max(1, int(MIN_HOLD_HOURS / self.bar_interval_hours))
        cooldown_bars = max(1, int(REENTRY_COOLDOWN_HOURS / self.bar_interval_hours))

        warmup = max(self.ma_period, self.atr_period) + 1
        i = warmup

        while i < n - min_hold_bars - 1:
            # Daily halt
            if self._check_daily_halt(i, timestamps):
                i += 1
                continue

            # Regime gate
            if regime_states[i] != RegimeState.RISK_ON:
                i += 1
                continue

            # Cooldown
            if i - self._last_exit_bar < cooldown_bars:
                i += 1
                continue

            # MA crossover: close[i] > sma[i] AND close[i-1] <= sma[i-1]
            if np.isnan(sma[i]) or np.isnan(sma[i - 1]):
                i += 1
                continue

            if not (closes[i] > sma[i] and closes[i - 1] <= sma[i - 1]):
                i += 1
                continue

            # Signal fires
            entry_bar = i + 1
            if entry_bar >= n:
                break

            entry_price = opens[entry_bar]
            entry_time = datetime.fromtimestamp(timestamps[entry_bar])

            pos_size = self._position_size()
            if pos_size < 1.0:
                i += 1
                continue

            entry_fee = pos_size * MAKER_FEE_PCT

            atr_val = atr[i] if not np.isnan(atr[i]) else atr[entry_bar]
            if np.isnan(atr_val):
                i += 1
                continue

            stop_level = entry_price - self.atr_stop_mult * atr_val
            target_level = entry_price + self.atr_target_mult * atr_val

            trade = Trade(
                trade_id=self._next_trade_id(),
                venue=VENUE,
                strategy="regime_momentum",
                pair=pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side="long",
                leverage=1.0,
                stop_level=stop_level,
                target_level=target_level,
                fees_paid=entry_fee,
            )

            # Simulate hold
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break

                # Stop hit
                if lows[bar] <= stop_level:
                    exit_bar = bar
                    exit_price = stop_level
                    exit_reason = ExitReason.STOP_HIT
                    break

                # Target hit
                if highs[bar] >= target_level:
                    exit_bar = bar
                    exit_price = target_level
                    exit_reason = ExitReason.TARGET_HIT
                    break

                # MA crossdown exit (only after min hold)
                if j >= min_hold_bars and not np.isnan(sma[bar]):
                    if closes[bar] < sma[bar]:
                        exit_bar = bar
                        exit_price = closes[bar]
                        exit_reason = ExitReason.TIME_STOP
                        break

                # Regime exit
                if regime_states[bar] != RegimeState.RISK_ON and j >= min_hold_bars:
                    exit_bar = bar
                    exit_price = closes[bar]
                    exit_reason = ExitReason.REGIME_EXIT
                    break

                exit_bar = bar
                exit_price = closes[bar]

            exit_fee = pos_size * MAKER_FEE_PCT
            exit_time = datetime.fromtimestamp(timestamps[min(exit_bar, n - 1)])

            trade.close(
                exit_price=exit_price,
                exit_timestamp=exit_time,
                exit_reason=exit_reason,
                fees=exit_fee,
            )

            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd
                self._daily_pnl += trade.pnl_usd

                if trade.outcome == TradeOutcome.WIN and trade.pnl_pct is not None:
                    self._win_count += 1
                    self._total_win_pct += trade.pnl_pct
                elif trade.outcome == TradeOutcome.LOSS and trade.pnl_pct is not None:
                    self._loss_count += 1
                    self._total_loss_pct += abs(trade.pnl_pct)

            if self._daily_pnl < -(self.initial_capital * DAILY_LOSS_HALT_PCT):
                self._daily_halted = True

            self._last_exit_bar = exit_bar
            trades.append(trade)
            i = exit_bar + cooldown_bars

        return trades

    def run_walk_forward(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        pair: str = "SOL/USDT",
        train_pct: float = 0.70,
        regime_states: np.ndarray | None = None,
    ) -> tuple[list[Trade], list[Trade], BacktestStats, BacktestStats]:
        """Walk-forward: train 70%, test 30%."""
        n = len(timestamps)
        split = int(n * train_pct)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 3)

        # Reset state for train
        self.wallet = self.initial_capital
        self._daily_pnl = 0.0
        self._daily_halted = False
        self._current_day = -1
        self._last_exit_bar = -999
        self._win_count = 0
        self._loss_count = 0
        self._total_win_pct = 0.0
        self._total_loss_pct = 0.0

        train_trades = self.run(
            timestamps[:split], opens[:split], highs[:split],
            lows[:split], closes[:split], volumes[:split],
            pair=pair, regime_states=regime_states[:split],
        )

        train_engine = BacktestEngine(self.initial_capital)
        train_engine.add_trades(train_trades)
        train_stats = train_engine.compute_stats(venue=VENUE, strategy="regime_momentum")

        test_trades = self.run(
            timestamps[split:], opens[split:], highs[split:],
            lows[split:], closes[split:], volumes[split:],
            pair=pair, regime_states=regime_states[split:],
        )

        test_engine = BacktestEngine(self.initial_capital)
        test_engine.add_trades(test_trades)
        test_stats = test_engine.compute_stats(venue=VENUE, strategy="regime_momentum")

        return train_trades, test_trades, train_stats, test_stats


# ---------------------------------------------------------------------------
# Main: run both strategies on synthetic data
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("KRAKEN SPOT BACKTESTER — SYNTHETIC DATA RUN")
    print("=" * 80)

    # Generate synthetic hourly data (~3 months)
    n_bars = 2200
    timestamps, opens, highs, lows, closes, volumes = generate_synthetic_ohlcv(
        n_bars=n_bars, base_price=150.0, volatility=0.003, trend=0.00003,
        bar_interval_hours=1.0, seed=42,
    )
    regime_states = _simulate_regime_series(n_bars, risk_on_pct=0.55, seed=99)

    pairs = _load_pairs()
    print(f"\nLoaded {len(pairs)} pairs from config")
    print(f"Synthetic data: {n_bars} hourly bars")
    risk_on_pct = np.sum(regime_states == RegimeState.RISK_ON) / n_bars
    print(f"Regime: {risk_on_pct:.1%} RISK_ON")

    # --- Strategy 1: Event-Driven ---
    print("\n" + "-" * 60)
    print("STRATEGY 1: EVENT-DRIVEN")
    print("-" * 60)

    evt_bt = EventDrivenBacktester(
        initial_capital=10_000.0,
        event_hit_rate=0.03,
        event_win_rate=0.55,
        event_avg_gain_pct=2.5,
        event_avg_loss_pct=1.5,
        bar_interval_hours=1.0,
        seed=42,
    )

    train_trades, test_trades, train_stats, test_stats = evt_bt.run_walk_forward(
        timestamps, opens, highs, lows, closes, volumes,
        pair="SOL/USDT", regime_states=regime_states,
    )

    print(f"\n--- Train (70%) ---")
    print(f"Trades: {train_stats.n_trades}")
    if train_stats.n_trades > 0:
        print(train_stats.summary())

    print(f"\n--- Test (30%) ---")
    print(f"Trades: {test_stats.n_trades}")
    if test_stats.n_trades > 0:
        print(test_stats.summary())

    # Full run for aggregate stats
    evt_bt2 = EventDrivenBacktester(
        initial_capital=10_000.0, event_hit_rate=0.03,
        event_win_rate=0.55, bar_interval_hours=1.0, seed=42,
    )
    all_evt_trades = evt_bt2.run(
        timestamps, opens, highs, lows, closes, volumes,
        pair="SOL/USDT", regime_states=regime_states,
    )
    engine = BacktestEngine(10_000.0)
    engine.add_trades(all_evt_trades)
    full_stats = engine.compute_stats(venue=VENUE, strategy="event_driven")
    print(f"\n--- Full Run ---")
    print(full_stats.summary())

    # --- Strategy 2: Regime-Momentum ---
    print("\n" + "-" * 60)
    print("STRATEGY 2: REGIME-MOMENTUM")
    print("-" * 60)

    mom_bt = RegimeMomentumBacktester(
        initial_capital=10_000.0,
        ma_period=20,
        atr_stop_mult=2.0,
        atr_target_mult=3.0,
        bar_interval_hours=1.0,
        seed=101,
    )

    train_t, test_t, train_s, test_s = mom_bt.run_walk_forward(
        timestamps, opens, highs, lows, closes, volumes,
        pair="SOL/USDT", regime_states=regime_states,
    )

    print(f"\n--- Train (70%) ---")
    print(f"Trades: {train_s.n_trades}")
    if train_s.n_trades > 0:
        print(train_s.summary())

    print(f"\n--- Test (30%) ---")
    print(f"Trades: {test_s.n_trades}")
    if test_s.n_trades > 0:
        print(test_s.summary())

    # Full run
    mom_bt2 = RegimeMomentumBacktester(
        initial_capital=10_000.0, ma_period=20,
        bar_interval_hours=1.0, seed=101,
    )
    all_mom_trades = mom_bt2.run(
        timestamps, opens, highs, lows, closes, volumes,
        pair="SOL/USDT", regime_states=regime_states,
    )
    engine2 = BacktestEngine(10_000.0)
    engine2.add_trades(all_mom_trades)
    full_mom = engine2.compute_stats(venue=VENUE, strategy="regime_momentum")
    print(f"\n--- Full Run ---")
    print(full_mom.summary())

    # --- Combined ---
    print("\n" + "=" * 60)
    print("COMBINED RESULTS")
    print("=" * 60)
    combined_engine = BacktestEngine(10_000.0)
    combined_engine.add_trades(all_evt_trades)
    combined_engine.add_trades(all_mom_trades)
    combined = combined_engine.compute_stats(venue=VENUE)
    print(combined.summary())
    print(f"\nFinal wallet (event-driven): ${evt_bt2.wallet:,.2f}")
    print(f"Final wallet (momentum):     ${mom_bt2.wallet:,.2f}")

    # Graduation check
    grad = combined_engine.graduation_check(combined, VENUE)
    print(f"\nGraduation check:")
    print(f"  Ready for review: {grad['ready_for_review']}")
    for name, check in grad["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        print(f"  {name}: {status} (required={check['required']}, actual={check['actual']})")
