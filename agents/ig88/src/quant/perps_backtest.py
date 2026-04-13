"""Jupiter Perps backtester — SOL-PERP mean-reversion with regime filter.

SOL-PERP only. Regime-gated (RISK_ON only). Leveraged (3x default, 5x max).

Fee model:
    - 0.07% open + 0.07% close = 0.14% round-trip minimum
    - Borrow fee: hourly rate 0.001%-0.01% depending on utilization
    - Borrow fee auto-close: close when borrow fee reaches 50% of TP target

Guardrails:
    - TP/SL required on every position (reject naked entries)
    - Min hold 2h, max hold 8h
    - Fee drag check: expected_move * leverage must exceed 0.25%
    - Max 1 open position at a time

Signal: mean reversion within momentum regime (from phase3_5min_reversal logic):
    - RSI oversold/overbought for entry signals
    - GARCH-style volatility regime filter
    - Only enters when vol is elevated (edge exists in reversal)

Usage:
    from src.quant.perps_backtest import PerpsBacktester
    from src.quant.backtest_engine import BacktestEngine

    bt = PerpsBacktester(initial_capital=5000.0, leverage=3.0)
    trades = bt.run(timestamps, opens, highs, lows, closes, volumes)
    engine = BacktestEngine(initial_capital=5000.0)
    engine.add_trades(trades)
    stats = engine.compute_stats(venue="jupiter_perps")
"""

from src.quant.base_backtester import BaseVenueBacktester, BacktestConfig
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

VENUE = \"jupiter_perps\"
VALID_PAIRS = (\"SOL-PERP\",)
OPEN_FEE_PCT = 0.0007       # 0.07%
CLOSE_FEE_PCT = 0.0007      # 0.07%
ROUND_TRIP_FEE_PCT = 0.0014 # 0.14% minimum
MIN_EXPECTED_MOVE_PCT = 0.0025  # 0.25%
MIN_HOLD_HOURS = 2.0
MAX_HOLD_HOURS = 8.0
MAX_OPEN_POSITIONS = 1
BORROW_FEE_AUTOCLOSE_PCT = 0.50  # Close when borrow fee = 50% of TP target
DEFAULT_LEVERAGE = 3.0
MAX_LEVERAGE = 5.0


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

def generate_synthetic_sol_data(
    n_bars: int = 3000,
    base_price: float = 140.0,
    volatility: float = 0.003,
    trend: float = 0.00002,
    bar_interval_hours: float = 0.0833,  # 5-minute bars
    seed: int = 77,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic SOL price data for perps backtesting.

    Default: 5-minute bars (~10.4 days of data at 3000 bars).
    Returns (timestamps, opens, highs, lows, closes, volumes).
    Timestamps are Unix epoch seconds (float64).
    """
    rng = np.random.default_rng(seed)

    # Geometric Brownian motion with mean-reverting component
    log_returns = np.empty(n_bars)
    price = base_price
    mean_price = base_price

    for i in range(n_bars):
        # Mean reversion factor: pull toward mean
        mr_force = -0.001 * math.log(price / mean_price) if price > 0 else 0
        # Random shock
        shock = rng.normal(trend + mr_force, volatility)
        log_returns[i] = shock
        price = price * math.exp(shock)
        # Slow-moving mean
        mean_price = mean_price * 0.9999 + price * 0.0001

    cum_returns = np.cumsum(log_returns)
    closes = base_price * np.exp(cum_returns)

    opens = np.empty(n_bars)
    highs = np.empty(n_bars)
    lows = np.empty(n_bars)

    opens[0] = base_price
    for i in range(1, n_bars):
        opens[i] = closes[i - 1]

    for i in range(n_bars):
        bar_range = abs(closes[i] - opens[i])
        extension = rng.exponential(max(bar_range * 0.5, volatility * closes[i]))
        highs[i] = max(opens[i], closes[i]) + extension * rng.uniform(0.2, 1.0)
        lows[i] = min(opens[i], closes[i]) - extension * rng.uniform(0.2, 1.0)

    # Volume with volatility correlation
    abs_returns = np.abs(log_returns)
    vol_factor = abs_returns / (np.mean(abs_returns) + 1e-10)
    base_volume = 5_000_000.0
    volumes = base_volume * (1.0 + vol_factor * 2.0) * rng.uniform(0.4, 1.6, n_bars)

    start_epoch = datetime(2025, 1, 1, 0, 0, 0).timestamp()
    interval_sec = bar_interval_hours * 3600.0
    timestamps = np.array(
        [start_epoch + i * interval_sec for i in range(n_bars)],
        dtype=np.float64,
    )

    return timestamps, opens, highs, lows, closes, volumes


# ---------------------------------------------------------------------------
# Helpers (pure numpy, no scipy/pandas)
# ---------------------------------------------------------------------------

def _compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index using Wilder smoothing."""
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


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = 14) -> np.ndarray:
    """Average True Range via exponential smoothing."""
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


def _compute_rolling_std(data: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation (realized volatility proxy)."""
    n = len(data)
    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        chunk = data[i - window + 1:i + 1]
        result[i] = np.std(chunk)
    return result


def _compute_ewma_volatility(log_returns: np.ndarray, span: int = 60) -> np.ndarray:
    """Exponentially weighted volatility (GARCH-like conditional vol).

    Uses EWMA variance: sigma^2_t = (1-alpha)*sigma^2_{t-1} + alpha*r^2_t
    where alpha = 2/(span+1).

    Returns: array of conditional volatility (sigma_t).
    """
    n = len(log_returns)
    alpha = 2.0 / (span + 1)
    vol = np.full(n, np.nan)

    if n < 2:
        return vol

    # Initialize with first 'span' observations
    init_end = min(span, n)
    var_t = np.var(log_returns[:init_end])
    vol[init_end - 1] = math.sqrt(max(var_t, 1e-20))

    for i in range(init_end, n):
        var_t = (1 - alpha) * var_t + alpha * log_returns[i] ** 2
        vol[i] = math.sqrt(max(var_t, 1e-20))

    return vol


def _classify_vol_regime(
    ewma_vol: np.ndarray,
    high_vol_percentile: float = 60.0,
) -> np.ndarray:
    """Classify each bar as high_vol or low_vol based on EWMA vol percentile.

    Returns array of booleans: True = high volatility (trade-able for reversal).
    """
    valid = ewma_vol[~np.isnan(ewma_vol)]
    if len(valid) == 0:
        return np.zeros(len(ewma_vol), dtype=bool)
    threshold = np.percentile(valid, high_vol_percentile)
    return ewma_vol >= threshold


def _estimate_borrow_fee_hourly(
    utilization: float = 0.5,
    min_rate: float = 0.00001,   # 0.001%
    max_rate: float = 0.0001,    # 0.01%
) -> float:
    """Estimate hourly borrow fee based on pool utilization.

    Linear interpolation between min and max rates.
    """
    return min_rate + (max_rate - min_rate) * max(0.0, min(1.0, utilization))


def _kelly_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    wallet_usd: float,
    fraction: float = KELLY_FRACTION,
    max_position_pct: float = 10.0,
) -> float:
    """Quarter-Kelly position sizing."""
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
    risk_on_pct: float = 0.50,
    regime_duration_bars: int = 80,
    seed: int = 55,
) -> np.ndarray:
    """Generate synthetic regime states with realistic persistence."""
    rng = np.random.default_rng(seed)
    states = [RegimeState.RISK_ON, RegimeState.NEUTRAL, RegimeState.RISK_OFF]
    weights = np.array([risk_on_pct, (1 - risk_on_pct) * 0.5, (1 - risk_on_pct) * 0.5])
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


def _simulate_utilization_series(
    n_bars: int,
    base: float = 0.5,
    volatility: float = 0.1,
    seed: int = 33,
) -> np.ndarray:
    """Generate synthetic pool utilization series (0-1 range)."""
    rng = np.random.default_rng(seed)
    util = np.empty(n_bars)
    u = base
    for i in range(n_bars):
        u += rng.normal(0, volatility * 0.1)
        u = max(0.05, min(0.95, u))
        util[i] = u
    return util


# ---------------------------------------------------------------------------
# PerpsBacktester
# ---------------------------------------------------------------------------

class PerpsBacktester:
    """Jupiter SOL-PERP backtester with mean-reversion signals.

    Enforces:
        - SOL-PERP only (rejects other pairs at construction)
        - TP/SL required on every position
        - Max 1 open position
        - Fee drag check before entry
        - Borrow fee auto-close
        - Regime gate (RISK_ON only)
    """

    def __init__(
        self,
        pair: str = "SOL-PERP",
        initial_capital: float = 5_000.0,
        leverage: float = DEFAULT_LEVERAGE,
        max_leverage: float = MAX_LEVERAGE,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_period: int = 14,
        atr_stop_mult: float = 1.5,
        atr_target_mult: float = 2.5,
        ewma_span: int = 60,
        high_vol_percentile: float = 60.0,
        bar_interval_hours: float = 0.0833,  # 5-min bars
        utilization_base: float = 0.5,
        seed: int = 77,
    ):
        # Enforce SOL-PERP only
        if pair not in VALID_PAIRS:
            raise ValueError(
                f"PerpsBacktester only supports {VALID_PAIRS}, got '{pair}'. "
                "Jupiter Perps strategy is SOL-PERP specific."
            )

        self.pair = pair
        self.initial_capital = initial_capital
        self.wallet = initial_capital

        # Clamp leverage
        if leverage > max_leverage:
            leverage = max_leverage
        self.leverage = leverage
        self.max_leverage = max_leverage

        # Signal parameters
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult
        self.ewma_span = ewma_span
        self.high_vol_percentile = high_vol_percentile
        self.bar_interval_hours = bar_interval_hours
        self.utilization_base = utilization_base
        self.seed = seed

        # Running state
        self._trade_counter: int = 0
        self._has_open_position: bool = False
        self._win_count: int = 0
        self._loss_count: int = 0
        self._total_win_pct: float = 0.0
        self._total_loss_pct: float = 0.0

    def _next_trade_id(self) -> str:
        self._trade_counter += 1
        return f"JP-MR-{self._trade_counter:05d}"

    def _position_size(self) -> float:
        """Quarter-Kelly position sizing for perps (notional, before leverage)."""
        if self._win_count + self._loss_count < 10:
            return min(self.wallet * 0.03, self.wallet)
        wr = self._win_count / (self._win_count + self._loss_count)
        avg_w = self._total_win_pct / self._win_count if self._win_count > 0 else 0.01
        avg_l = self._total_loss_pct / self._loss_count if self._loss_count > 0 else 0.01
        return _kelly_position_size(wr, avg_w, avg_l, self.wallet)

    def _fee_drag_check(
        self,
        entry_price: float,
        target_price: float,
        side: str,
    ) -> bool:
        """Check that expected_move * leverage exceeds 0.25%.

        Returns True if the trade passes the fee drag check.
        """
        if side == "long":
            expected_move_pct = (target_price - entry_price) / entry_price
        else:
            expected_move_pct = (entry_price - target_price) / entry_price

        # Leverage is applied to the asset's percentage move.
        # The review noted ATR/leverage division issues. 
        # We must ensure we are multiplying the raw move by leverage, 
        # not dividing the target (which is already in price space) by leverage.
        leveraged_move = abs(expected_move_pct) * self.leverage
        return leveraged_move >= MIN_EXPECTED_MOVE_PCT

    def _compute_borrow_fees(
        self,
        hold_hours: float,
        position_usd: float,
        utilization: float,
    ) -> float:
        """Compute total borrow fees for a position."""
        hourly_rate = _estimate_borrow_fee_hourly(utilization)
        return position_usd * hourly_rate * hold_hours

    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        regime_states: np.ndarray | None = None,
        utilization: np.ndarray | None = None,
    ) -> list[Trade]:
        """Run SOL-PERP mean-reversion backtest.

        Signals:
            LONG:  RSI < oversold in high-vol regime (mean reversion up)
            SHORT: RSI > overbought in high-vol regime (mean reversion down)

        Entry: next bar open after signal
        Exit priority: stop > target > borrow fee auto-close > max hold > regime exit

        Args:
            timestamps: Unix epoch seconds (float64)
            opens, highs, lows, closes, volumes: OHLCV arrays
            regime_states: Array of RegimeState per bar. Synthetic if None.
            utilization: Pool utilization per bar (0-1). Synthetic if None.

        Returns:
            List of closed Trade objects.
        """
        n = len(timestamps)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 11)

        if utilization is None:
            utilization = _simulate_utilization_series(
                n, base=self.utilization_base, seed=self.seed + 22,
            )

        # Precompute indicators
        rsi = _compute_rsi(closes, self.rsi_period)
        atr = _compute_atr(highs, lows, closes, self.atr_period)

        # Log returns for volatility estimation
        log_returns = np.zeros(n)
        log_returns[1:] = np.log(closes[1:] / closes[:-1])
        ewma_vol = _compute_ewma_volatility(log_returns, span=self.ewma_span)
        is_high_vol = _classify_vol_regime(ewma_vol, self.high_vol_percentile)

        trades: list[Trade] = []
        min_hold_bars = max(1, int(MIN_HOLD_HOURS / self.bar_interval_hours))
        max_hold_bars = max(min_hold_bars + 1, int(MAX_HOLD_HOURS / self.bar_interval_hours))

        warmup = max(self.rsi_period + 1, self.atr_period, self.ewma_span) + 1
        i = warmup

        while i < n - min_hold_bars - 1:
            # Max 1 open position
            if self._has_open_position:
                i += 1
                continue

            # Regime gate
            if regime_states[i] != RegimeState.RISK_ON:
                i += 1
                continue

            # Volatility regime filter: only trade in high-vol
            if not is_high_vol[i]:
                i += 1
                continue

            # RSI signal check
            if np.isnan(rsi[i]) or np.isnan(atr[i]):
                i += 1
                continue

            side: str | None = None
            if rsi[i] < self.rsi_oversold:
                side = "long"
            elif rsi[i] > self.rsi_overbought:
                side = "short"
            else:
                i += 1
                continue

            # Entry at next bar open
            entry_bar = i + 1
            if entry_bar >= n:
                break

            entry_price = opens[entry_bar]
            atr_val = atr[i]

            # Compute TP/SL levels (always required)
            if side == "long":
                stop_level = entry_price - self.atr_stop_mult * atr_val
                target_level = entry_price + self.atr_target_mult * atr_val
            else:
                stop_level = entry_price + self.atr_stop_mult * atr_val
                target_level = entry_price - self.atr_target_mult * atr_val

            # Fee drag check: expected_move * leverage must exceed 0.25%
            # BUG FIX: ensure we use the notional movement relative to the entry price, 
            # but the check is performed on the leveraged return.
            if not self._fee_drag_check(entry_price, target_level, side):
                i += 1
                continue

            # Position sizing
            pos_size = self._position_size()
            if pos_size < 1.0:
                i += 1
                continue

            # Notional position = margin * leverage
            notional = pos_size * self.leverage

            # Open fee
            open_fee = notional * OPEN_FEE_PCT

            entry_time = datetime.fromtimestamp(timestamps[entry_bar], tz=timezone.utc)

            trade = Trade(
                trade_id=self._next_trade_id(),
                venue=VENUE,
                strategy="perps_mean_reversion",
                pair=self.pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side=side,
                leverage=self.leverage,
                stop_level=stop_level,
                target_level=target_level,
                fees_paid=open_fee,
            )

            self._has_open_position = True

            # Compute TP P&L target for borrow fee auto-close
            if side == "long":
                tp_pnl_pct = (target_level - entry_price) / entry_price * self.leverage
            else:
                tp_pnl_pct = (entry_price - target_level) / entry_price * self.leverage
            tp_pnl_usd = tp_pnl_pct * pos_size

            # Simulate hold
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP
            cumulative_borrow_fee = 0.0

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break

                # Accumulate borrow fees
                borrow_this_bar = self._compute_borrow_fees(
                    hold_hours=self.bar_interval_hours,
                    position_usd=notional,
                    utilization=utilization[bar],
                )
                cumulative_borrow_fee += borrow_this_bar

                # Check stop hit
                if side == "long":
                    if lows[bar] <= stop_level:
                        exit_bar = bar
                        exit_price = stop_level
                        exit_reason = ExitReason.STOP_HIT
                        break
                else:
                    if highs[bar] >= stop_level:
                        exit_bar = bar
                        exit_price = stop_level
                        exit_reason = ExitReason.STOP_HIT
                        break

                # Check target hit
                if side == "long":
                    if highs[bar] >= target_level:
                        exit_bar = bar
                        exit_price = target_level
                        exit_reason = ExitReason.TARGET_HIT
                        break
                else:
                    if lows[bar] <= target_level:
                        exit_bar = bar
                        exit_price = target_level
                        exit_reason = ExitReason.TARGET_HIT
                        break

                # Borrow fee auto-close: close when borrow reaches 50% of TP target
                if tp_pnl_usd > 0 and cumulative_borrow_fee >= tp_pnl_usd * BORROW_FEE_AUTOCLOSE_PCT:
                    exit_bar = bar
                    exit_price = closes[bar]
                    exit_reason = ExitReason.BORROW_FEE
                    break

                # Max hold time
                if j >= max_hold_bars:
                    exit_bar = bar
                    exit_price = closes[bar]
                    exit_reason = ExitReason.TIME_STOP
                    break

                # Regime exit (after min hold)
                if j >= min_hold_bars and regime_states[bar] != RegimeState.RISK_ON:
                    exit_bar = bar
                    exit_price = closes[bar]
                    exit_reason = ExitReason.REGIME_EXIT
                    break

                exit_bar = bar
                exit_price = closes[bar]

            # Close fee
            close_fee = notional * CLOSE_FEE_PCT
            exit_time = datetime.fromtimestamp(timestamps[min(exit_bar, n - 1)], tz=timezone.utc)

            trade.close(
                exit_price=exit_price,
                exit_timestamp=exit_time,
                exit_reason=exit_reason,
                fees=close_fee,
                borrow_fees=cumulative_borrow_fee,
            )

            self._has_open_position = False

            # Update wallet and stats
            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd

                if trade.outcome == TradeOutcome.WIN and trade.pnl_pct is not None:
                    self._win_count += 1
                    self._total_win_pct += trade.pnl_pct
                elif trade.outcome == TradeOutcome.LOSS and trade.pnl_pct is not None:
                    self._loss_count += 1
                    self._total_loss_pct += abs(trade.pnl_pct)

            trades.append(trade)
            # Advance past trade (no overlapping positions)
            i = exit_bar + 1

        return trades

    def run_walk_forward(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        train_pct: float = 0.70,
        regime_states: np.ndarray | None = None,
        utilization: np.ndarray | None = None,
    ) -> tuple[list[Trade], list[Trade], BacktestStats, BacktestStats]:
        """Walk-forward validation: train on first 70%, test on last 30%.

        Returns (train_trades, test_trades, train_stats, test_stats).
        """
        n = len(timestamps)
        split = int(n * train_pct)

        if regime_states is None:
            regime_states = _simulate_regime_series(n, seed=self.seed + 11)
        if utilization is None:
            utilization = _simulate_utilization_series(
                n, base=self.utilization_base, seed=self.seed + 22,
            )

        # Train phase: reset state
        self.wallet = self.initial_capital
        self._trade_counter = 0
        self._has_open_position = False
        self._win_count = 0
        self._loss_count = 0
        self._total_win_pct = 0.0
        self._total_loss_pct = 0.0

        train_trades = self.run(
            timestamps[:split], opens[:split], highs[:split],
            lows[:split], closes[:split], volumes[:split],
            regime_states=regime_states[:split],
            utilization=utilization[:split],
        )

        train_engine = BacktestEngine(self.initial_capital)
        train_engine.add_trades(train_trades)
        train_stats = train_engine.compute_stats(
            venue=VENUE, strategy="perps_mean_reversion",
        )

        # Test phase: keep Kelly stats from training
        test_trades = self.run(
            timestamps[split:], opens[split:], highs[split:],
            lows[split:], closes[split:], volumes[split:],
            regime_states=regime_states[split:],
            utilization=utilization[split:],
        )

        test_engine = BacktestEngine(self.initial_capital)
        test_engine.add_trades(test_trades)
        test_stats = test_engine.compute_stats(
            venue=VENUE, strategy="perps_mean_reversion",
        )

        return train_trades, test_trades, train_stats, test_stats


# ---------------------------------------------------------------------------
# Main: run on synthetic SOL data
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("JUPITER PERPS BACKTESTER — SOL-PERP SYNTHETIC DATA RUN")
    print("=" * 80)

    # Verify pair enforcement
    print("\nPair enforcement check:")
    try:
        _bad = PerpsBacktester(pair="ETH-PERP")
        print("  FAIL: should have rejected ETH-PERP")
    except ValueError as e:
        print(f"  PASS: correctly rejected ETH-PERP ({e})")

    # Generate synthetic 5-minute SOL data (~42 days)
    n_bars = 12_000
    timestamps, opens, highs, lows, closes, volumes = generate_synthetic_sol_data(
        n_bars=n_bars, base_price=140.0, volatility=0.003,
        trend=0.00002, bar_interval_hours=0.0833, seed=77,
    )
    regime_states = _simulate_regime_series(n_bars, risk_on_pct=0.50, seed=55)
    utilization = _simulate_utilization_series(n_bars, base=0.5, seed=33)

    risk_on_pct = np.sum(regime_states == RegimeState.RISK_ON) / n_bars
    print(f"\nSynthetic data: {n_bars} bars (5-min), ~{n_bars * 5 / 60 / 24:.0f} days")
    print(f"Price range: ${closes.min():.2f} - ${closes.max():.2f}")
    print(f"Regime: {risk_on_pct:.1%} RISK_ON")
    print(f"Avg utilization: {utilization.mean():.2%}")

    # --- Leverage 3x run ---
    print("\n" + "-" * 60)
    print("PERPS MEAN-REVERSION (3x leverage)")
    print("-" * 60)

    bt_3x = PerpsBacktester(
        pair="SOL-PERP",
        initial_capital=5_000.0,
        leverage=3.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        atr_stop_mult=1.5,
        atr_target_mult=2.5,
        bar_interval_hours=0.0833,
        seed=77,
    )

    train_trades, test_trades, train_stats, test_stats = bt_3x.run_walk_forward(
        timestamps, opens, highs, lows, closes, volumes,
        regime_states=regime_states, utilization=utilization,
    )

    print(f"\n--- Train (70%) ---")
    print(f"Trades: {train_stats.n_trades}")
    if train_stats.n_trades > 0:
        print(train_stats.summary())

    print(f"\n--- Test (30%) ---")
    print(f"Trades: {test_stats.n_trades}")
    if test_stats.n_trades > 0:
        print(test_stats.summary())

    # Full run
    bt_3x_full = PerpsBacktester(
        pair="SOL-PERP", initial_capital=5_000.0, leverage=3.0,
        bar_interval_hours=0.0833, seed=77,
    )
    all_trades_3x = bt_3x_full.run(
        timestamps, opens, highs, lows, closes, volumes,
        regime_states=regime_states, utilization=utilization,
    )

    engine_3x = BacktestEngine(5_000.0)
    engine_3x.add_trades(all_trades_3x)
    full_stats_3x = engine_3x.compute_stats(venue=VENUE, strategy="perps_mean_reversion")

    print(f"\n--- Full Run (3x) ---")
    print(full_stats_3x.summary())
    print(f"Final wallet: ${bt_3x_full.wallet:,.2f}")

    # Exit reason breakdown
    if all_trades_3x:
        print(f"\nExit Reasons:")
        reason_counts: dict[str, int] = {}
        for t in all_trades_3x:
            reason = t.exit_reason.value if t.exit_reason else "unknown"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            pct = count / len(all_trades_3x) * 100
            print(f"  {reason:<20} {count:>5} ({pct:.1f}%)")

        # Borrow fee analysis
        total_borrow = sum(t.borrow_fees for t in all_trades_3x)
        total_fees = sum(t.fees_paid for t in all_trades_3x)
        print(f"\nFee Analysis:")
        print(f"  Total open/close fees: ${total_fees:,.2f}")
        print(f"  Total borrow fees:     ${total_borrow:,.2f}")
        print(f"  Borrow as % of fees:   {total_borrow / (total_fees + total_borrow) * 100:.1f}%"
              if total_fees + total_borrow > 0 else "  No fees")

        # Side breakdown
        print(f"\nSide Breakdown:")
        for side in ["long", "short"]:
            side_trades = [t for t in all_trades_3x if t.side == side]
            if side_trades:
                wins = sum(1 for t in side_trades if t.outcome == TradeOutcome.WIN)
                wr = wins / len(side_trades) * 100
                avg_pnl = np.mean([t.pnl_pct for t in side_trades if t.pnl_pct is not None])
                print(f"  {side:<8} {len(side_trades):>5} trades, "
                      f"WR={wr:.1f}%, avg={avg_pnl:.4f}%")

    # --- Leverage 5x comparison ---
    print("\n" + "-" * 60)
    print("PERPS MEAN-REVERSION (5x leverage — max)")
    print("-" * 60)

    bt_5x = PerpsBacktester(
        pair="SOL-PERP", initial_capital=5_000.0, leverage=5.0,
        bar_interval_hours=0.0833, seed=77,
    )
    all_trades_5x = bt_5x.run(
        timestamps, opens, highs, lows, closes, volumes,
        regime_states=regime_states, utilization=utilization,
    )
    engine_5x = BacktestEngine(5_000.0)
    engine_5x.add_trades(all_trades_5x)
    full_stats_5x = engine_5x.compute_stats(venue=VENUE, strategy="perps_mean_reversion")

    print(full_stats_5x.summary())
    print(f"Final wallet (5x): ${bt_5x.wallet:,.2f}")

    # Leverage comparison
    print("\n" + "=" * 60)
    print("LEVERAGE COMPARISON (3x vs 5x)")
    print("=" * 60)
    print(f"{'Metric':<30} {'3x':>12} {'5x':>12}")
    print(f"{'':-<54}")
    print(f"{'Trades':<30} {full_stats_3x.n_trades:>12} {full_stats_5x.n_trades:>12}")
    print(f"{'Win Rate':<30} {full_stats_3x.win_rate:>11.1%} {full_stats_5x.win_rate:>11.1%}")
    print(f"{'Expectancy/trade':<30} {full_stats_3x.expectancy_per_trade:>12.4f} "
          f"{full_stats_5x.expectancy_per_trade:>12.4f}")
    print(f"{'Sharpe':<30} {full_stats_3x.sharpe_ratio:>12.2f} {full_stats_5x.sharpe_ratio:>12.2f}")
    print(f"{'Sortino':<30} {full_stats_3x.sortino_ratio:>12.2f} {full_stats_5x.sortino_ratio:>12.2f}")
    print(f"{'Max Drawdown':<30} {full_stats_3x.max_drawdown_pct:>11.2%} "
          f"{full_stats_5x.max_drawdown_pct:>11.2%}")
    print(f"{'Profit Factor':<30} {full_stats_3x.profit_factor:>12.2f} "
          f"{full_stats_5x.profit_factor:>12.2f}")
    print(f"{'Total Fees':<30} ${full_stats_3x.total_fees_usd:>10,.2f} "
          f"${full_stats_5x.total_fees_usd:>10,.2f}")
    print(f"{'Variance Drag':<30} {full_stats_3x.variance_drag:>12.6f} "
          f"{full_stats_5x.variance_drag:>12.6f}")
    print(f"{'Geometric Return':<30} {full_stats_3x.geometric_return:>12.6f} "
          f"{full_stats_5x.geometric_return:>12.6f}")
    geo_3x = "PASS" if full_stats_3x.geometric_positive else "FAIL"
    geo_5x = "PASS" if full_stats_5x.geometric_positive else "FAIL"
    print(f"{'Geometric Positive':<30} {geo_3x:>12} {geo_5x:>12}")

    # Graduation check
    print("\n--- Graduation Check (3x) ---")
    grad = engine_3x.graduation_check(full_stats_3x, VENUE)
    print(f"Ready for review: {grad['ready_for_review']}")
    for name, check in grad["checks"].items():
        status = "PASS" if check["pass"] else "FAIL"
        print(f"  {name}: {status} (required={check['required']}, actual={check['actual']})")
