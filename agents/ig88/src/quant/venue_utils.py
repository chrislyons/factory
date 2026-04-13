"""
venue_utils.py — Shared utilities for all IG-88 venue backtesters.

Consolidates:
- Technical indicator helpers (SMA, RSI, ATR, EWMA volatility)
- Synthetic OHLCV data generation
- Fee constants and common configurations
- Position sizing utilities

Eliminates duplication across spot_backtest.py, perps_backtest.py,
and polymarket_backtest.py.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
import math
import numpy as np


# ---------------------------------------------------------------------------
# Fee Constants (venue-specific overrides in individual backtests)
# ---------------------------------------------------------------------------

MAKER_FEE_PCT = 0.0016       # 0.16% (Kraken)
TAKER_FEE_PCT = 0.0026       # 0.26% (Kraken)
PERPS_OPEN_FEE_PCT = 0.0007  # 0.07% (Jupiter)
PERPS_CLOSE_FEE_PCT = 0.0007 # 0.07% (Jupiter)


# ---------------------------------------------------------------------------
# Technical Indicators (pure numpy, no scipy/pandas)
# ---------------------------------------------------------------------------

def compute_sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average. First (period-1) values are NaN."""
    sma = np.full(len(data), np.nan)
    n = len(data)
    if n < period:
        return sma
    cumsum = np.cumsum(data)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))) / period
    return sma


def compute_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
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


def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
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


def compute_rolling_std(data: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation (realized volatility proxy)."""
    n = len(data)
    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        chunk = data[i - window + 1:i + 1]
        result[i] = np.std(chunk)
    return result


def compute_ewma_volatility(log_returns: np.ndarray, span: int = 60) -> np.ndarray:
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


def classify_vol_regime(
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


# ---------------------------------------------------------------------------
# Synthetic Data Generation
# ---------------------------------------------------------------------------

def generate_synthetic_ohlcv(
    n_bars: int = 2000,
    base_price: float = 150.0,
    volatility: float = 0.002,
    trend: float = 0.00005,
    bar_interval_hours: float = 1.0,
    seed: int = 42,
    mean_reversion: float = 0.0,  # 0 = pure GBM, >0 = mean-reverting component
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic OHLCV data for testing.

    Returns (timestamps, opens, highs, lows, closes, volumes) as numpy arrays.
    Timestamps are Unix epoch seconds (float64).

    Args:
        mean_reversion: Strength of mean-reversion force (0.0 = pure GBM).
                        Higher values create more mean-reverting behavior.
    """
    rng = np.random.default_rng(seed)

    # Generate close prices via geometric Brownian motion (with optional mean-reversion)
    log_returns = np.empty(n_bars)
    price = base_price
    mean_price = base_price

    for i in range(n_bars):
        if mean_reversion > 0:
            mr_force = -mean_reversion * math.log(price / mean_price) if price > 0 else 0
        else:
            mr_force = 0.0
        shock = rng.normal(trend + mr_force, volatility)
        log_returns[i] = shock
        price = price * math.exp(shock)
        # Slow-moving mean (for mean-reversion target)
        mean_price = mean_price * 0.9999 + price * 0.0001

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
        extension = rng.exponential(max(bar_range * 0.5, volatility * closes[i]))
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
# Position Sizing Utilities
# ---------------------------------------------------------------------------

def kelly_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    wallet_usd: float,
    kelly_fraction: float = 0.25,
    max_position_pct: float = 10.0,
) -> float:
    """Quarter-Kelly position sizing.

    Returns the notional USD amount to risk.
    """
    if avg_loss == 0 or win_rate <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1.0 - win_rate
    f_kelly = (b * win_rate - q) / b
    if f_kelly <= 0:
        return 0.0
    f_sized = f_kelly * kelly_fraction
    position_usd = wallet_usd * f_sized
    max_usd = wallet_usd * (max_position_pct / 100.0)
    return min(position_usd, max_usd)


# ---------------------------------------------------------------------------
# Borrow Fee Estimation (Perps)
# ---------------------------------------------------------------------------

def estimate_borrow_fee_hourly(
    utilization: float = 0.5,
    min_rate: float = 0.00001,   # 0.001%
    max_rate: float = 0.0001,    # 0.01%
) -> float:
    """Estimate hourly borrow fee based on pool utilization.

    Linear interpolation between min and max rates.
    """
    return min_rate + (max_rate - min_rate) * max(0.0, min(1.0, utilization))


# ---------------------------------------------------------------------------
# Regime Simulation (for synthetic backtests)
# ---------------------------------------------------------------------------

def simulate_regime_series(
    n_bars: int,
    risk_on_pct: float = 0.50,
    regime_duration_bars: int = 80,
    seed: int = 55,
) -> np.ndarray:
    """Generate synthetic regime states with realistic persistence.

    Returns array of RegimeState objects.
    """
    from src.quant.regime import RegimeState

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


def simulate_utilization_series(
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
