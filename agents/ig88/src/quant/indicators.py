"""Technical indicator library for IG-88 trading system.

Pure numpy implementations of technical indicators used across backtesting,
signal generation, and live trading. No external dependencies beyond numpy.

Indicator sources:
- Ichimoku Cloud: Chris's TradingView indicator (priority)
- Klinger Oscillator: TradingView volume oscillator
- KAMA (Kaufman Adaptive MA): from TradingView POC Bands indicator
- VWAP: TradingView Volume Weighted Average Price
- Fibonacci Retracement/Extension: from TradingView Auto Fib Extension
- Kagi: TradingView Kagi Overlay (trend filter)
- Standard helpers: RSI, EMA, SMA, ATR, MACD, Bollinger Bands

All functions accept numpy arrays and return numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


# ---------------------------------------------------------------------------
# Ichimoku Cloud (priority indicator)
# ---------------------------------------------------------------------------

class CloudDirection(Enum):
    """Ichimoku cloud color / trend direction."""
    BULLISH = "bullish"     # Senkou A > Senkou B
    BEARISH = "bearish"     # Senkou A < Senkou B
    NEUTRAL = "neutral"     # Senkou A == Senkou B


@dataclass
class IchimokuCloud:
    """Bundle of all five Ichimoku lines plus derived cloud state.

    The Ichimoku Kinko Hyo ("one glance equilibrium chart") provides
    support/resistance, trend direction, momentum, and trade signals
    from a single indicator system.

    Lines:
        tenkan_sen: Conversion Line -- (9-period high + 9-period low) / 2.
            Short-term trend and momentum signal. Fastest line.
        kijun_sen: Base Line -- (26-period high + 26-period low) / 2.
            Medium-term trend. Acts as support/resistance.
        senkou_span_a: Leading Span A -- (Tenkan + Kijun) / 2, plotted 26
            periods ahead. Forms one edge of the cloud (kumo).
        senkou_span_b: Leading Span B -- (52-period high + 52-period low) / 2,
            plotted 26 periods ahead. Forms the other edge of the cloud.
        chikou_span: Lagging Span -- current close plotted 26 periods back.
            Confirms trend by comparing current price to historical price.

    Derived:
        cloud_direction: Per-bar CloudDirection based on Senkou A vs B.
            BULLISH when A > B (green cloud), BEARISH when A < B (red cloud).

    Note on displacement:
        senkou_span_a and senkou_span_b are forward-shifted by `displacement`
        periods (default 26). This means the last `displacement` values
        project into the future. The arrays are the same length as the input,
        with the first `displacement` values being NaN (shifted forward).

        chikou_span is backward-shifted by `displacement` periods, so the
        last `displacement` values are NaN.
    """
    tenkan_sen: np.ndarray
    kijun_sen: np.ndarray
    senkou_span_a: np.ndarray
    senkou_span_b: np.ndarray
    chikou_span: np.ndarray
    cloud_direction: np.ndarray  # Array of CloudDirection values

    @property
    def cloud_top(self) -> np.ndarray:
        """Upper edge of the cloud (max of Senkou A, Senkou B)."""
        return np.fmax(self.senkou_span_a, self.senkou_span_b)

    @property
    def cloud_bottom(self) -> np.ndarray:
        """Lower edge of the cloud (min of Senkou A, Senkou B)."""
        return np.fmin(self.senkou_span_a, self.senkou_span_b)

    @property
    def cloud_thickness(self) -> np.ndarray:
        """Absolute distance between Senkou A and B. Thicker = stronger trend."""
        return np.abs(self.senkou_span_a - self.senkou_span_b)

    def price_vs_cloud(self, close: np.ndarray) -> np.ndarray:
        """Classify price position relative to cloud.

        Returns:
            Array of strings: 'above', 'below', or 'inside' per bar.
        """
        n = len(close)
        result = np.full(n, "inside", dtype=object)
        top = self.cloud_top
        bot = self.cloud_bottom
        for i in range(n):
            if np.isnan(top[i]) or np.isnan(bot[i]):
                continue
            if close[i] > top[i]:
                result[i] = "above"
            elif close[i] < bot[i]:
                result[i] = "below"
        return result

    def tk_cross_signals(self) -> np.ndarray:
        """Tenkan/Kijun crossover signals.

        Returns:
            Array of int: +1 = bullish cross (Tenkan crosses above Kijun),
            -1 = bearish cross, 0 = no cross.
        """
        n = len(self.tenkan_sen)
        signals = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if (np.isnan(self.tenkan_sen[i]) or np.isnan(self.kijun_sen[i])
                    or np.isnan(self.tenkan_sen[i - 1])
                    or np.isnan(self.kijun_sen[i - 1])):
                continue
            prev_above = self.tenkan_sen[i - 1] > self.kijun_sen[i - 1]
            curr_above = self.tenkan_sen[i] > self.kijun_sen[i]
            if not prev_above and curr_above:
                signals[i] = 1
            elif prev_above and not curr_above:
                signals[i] = -1
        return signals


def _donchian_midpoint(high: np.ndarray, low: np.ndarray,
                       period: int) -> np.ndarray:
    """Donchian channel midpoint: (highest high + lowest low) / 2 over period.

    This is the core Ichimoku building block. First (period-1) values are NaN.
    """
    n = len(high)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        hh = np.max(high[i - period + 1:i + 1])
        ll = np.min(low[i - period + 1:i + 1])
        result[i] = (hh + ll) / 2.0
    return result


def ichimoku(high: np.ndarray, low: np.ndarray, close: np.ndarray,
             tenkan_period: int = 9, kijun_period: int = 26,
             senkou_b_period: int = 52,
             displacement: int = 26) -> IchimokuCloud:
    """Compute the full Ichimoku Cloud system.

    Implements the exact same calculation as Chris's TradingView indicator:
    each line is a Donchian midpoint (avg of highest high and lowest low).

    Args:
        high: Array of high prices.
        low: Array of low prices.
        close: Array of close prices.
        tenkan_period: Conversion Line lookback (default 9).
        kijun_period: Base Line lookback (default 26).
        senkou_b_period: Leading Span B lookback (default 52).
        displacement: Forward/backward shift for Senkou/Chikou (default 26).

    Returns:
        IchimokuCloud dataclass with all five lines and cloud direction.
    """
    n = len(high)

    # Core lines (unshifted)
    tenkan_sen = _donchian_midpoint(high, low, tenkan_period)
    kijun_sen = _donchian_midpoint(high, low, kijun_period)

    # Senkou Span A: average of Tenkan and Kijun, shifted forward
    senkou_a_raw = (tenkan_sen + kijun_sen) / 2.0
    senkou_span_a = np.full(n, np.nan)
    if displacement - 1 < n:
        shift = displacement - 1  # TradingView uses offset = displacement - 1
        end = min(n, n - shift + shift)  # just n
        senkou_span_a[shift:] = senkou_a_raw[:n - shift]

    # Senkou Span B: 52-period Donchian midpoint, shifted forward
    senkou_b_raw = _donchian_midpoint(high, low, senkou_b_period)
    senkou_span_b = np.full(n, np.nan)
    if displacement - 1 < n:
        shift = displacement - 1
        senkou_span_b[shift:] = senkou_b_raw[:n - shift]

    # Chikou Span: close shifted backward
    chikou_span = np.full(n, np.nan)
    back_shift = displacement - 1
    if back_shift < n:
        chikou_span[:n - back_shift] = close[back_shift:]

    # Cloud direction
    cloud_direction = np.full(n, CloudDirection.NEUTRAL, dtype=object)
    for i in range(n):
        if np.isnan(senkou_span_a[i]) or np.isnan(senkou_span_b[i]):
            continue
        if senkou_span_a[i] > senkou_span_b[i]:
            cloud_direction[i] = CloudDirection.BULLISH
        elif senkou_span_a[i] < senkou_span_b[i]:
            cloud_direction[i] = CloudDirection.BEARISH

    return IchimokuCloud(
        tenkan_sen=tenkan_sen,
        kijun_sen=kijun_sen,
        senkou_span_a=senkou_span_a,
        senkou_span_b=senkou_span_b,
        chikou_span=chikou_span,
        cloud_direction=cloud_direction,
    )


# ---------------------------------------------------------------------------
# Standard Moving Averages
# ---------------------------------------------------------------------------

def sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average.

    First (period-1) values are NaN. Uses cumulative sum for O(n) computation.

    Args:
        data: Input price array (typically close prices).
        period: Lookback window.

    Returns:
        SMA values as numpy array.
    """
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    cumsum = np.cumsum(data)
    result[period - 1:] = (
        cumsum[period - 1:] - np.concatenate(([0.0], cumsum[:-period]))
    ) / period
    return result


def ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average.

    Uses the standard smoothing factor alpha = 2 / (period + 1).
    First value is seeded with SMA of the first `period` values.
    Values before period are NaN.

    Args:
        data: Input price array.
        period: EMA period (span).

    Returns:
        EMA values as numpy array.
    """
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    alpha = 2.0 / (period + 1)
    # Seed with SMA
    result[period - 1] = np.mean(data[:period])
    for i in range(period, n):
        result[i] = alpha * data[i] + (1.0 - alpha) * result[i - 1]
    return result


def wma(data: np.ndarray, period: int) -> np.ndarray:
    """Weighted Moving Average.

    Linear weighting: most recent bar gets weight=period, oldest gets weight=1.
    First (period-1) values are NaN.

    Args:
        data: Input price array.
        period: Lookback window.

    Returns:
        WMA values as numpy array.
    """
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    weights = np.arange(1, period + 1, dtype=np.float64)
    weight_sum = weights.sum()
    for i in range(period - 1, n):
        result[i] = np.dot(data[i - period + 1:i + 1], weights) / weight_sum
    return result


def dema(data: np.ndarray, period: int) -> np.ndarray:
    """Double Exponential Moving Average.

    DEMA = 2 * EMA(data) - EMA(EMA(data)). Reduces lag compared to EMA.

    Args:
        data: Input price array.
        period: EMA period.

    Returns:
        DEMA values as numpy array.
    """
    ema1 = ema(data, period)
    # For EMA of EMA, we need to handle NaN values
    valid_start = period - 1
    ema2_input = ema1.copy()
    ema2 = ema(ema2_input[valid_start:], period)

    result = np.full(len(data), np.nan)
    offset = valid_start + period - 1
    if offset < len(data):
        end = min(len(ema2), len(data) - valid_start)
        for i in range(period - 1, end):
            idx = valid_start + i
            if idx < len(data) and not np.isnan(ema1[idx]):
                result[idx] = 2.0 * ema1[idx] - ema2[i]
    return result


# ---------------------------------------------------------------------------
# Kaufman Adaptive Moving Average (from POC Bands indicator)
# ---------------------------------------------------------------------------

def kama(data: np.ndarray, period: int = 6,
         fast_period: int = 2, slow_period: int = 30) -> np.ndarray:
    """Kaufman Adaptive Moving Average.

    Adapts smoothing speed based on market efficiency ratio (signal/noise).
    From Chris's TradingView POC Bands indicator.

    When the market is trending (high efficiency), KAMA moves quickly.
    When choppy (low efficiency), KAMA barely moves.

    Args:
        data: Input price array (POC Bands uses hlc3).
        period: Efficiency ratio lookback (default 6, matching POC Bands).
        fast_period: Fast EMA equivalent period (default 2).
        slow_period: Slow EMA equivalent period (default 30).

    Returns:
        KAMA values as numpy array.
    """
    n = len(data)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    fast_sc = 2.0 / (fast_period + 1)   # ~0.666 (matches POC Bands nfastend)
    slow_sc = 2.0 / (slow_period + 1)   # ~0.0645 (matches POC Bands nslowend)

    # Noise: sum of absolute bar-to-bar changes over period
    abs_changes = np.abs(np.diff(data))

    result[period] = data[period]  # Seed

    for i in range(period + 1, n):
        # Signal: absolute change over the full period
        signal = abs(data[i] - data[i - period])
        # Noise: sum of absolute changes
        noise = np.sum(abs_changes[i - period:i])
        if noise != 0:
            er = signal / noise  # Efficiency ratio: 0 (choppy) to 1 (trending)
        else:
            er = 0.0
        # Smoothing constant: scales between fast and slow
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result[i] = result[i - 1] + sc * (data[i] - result[i - 1])

    return result


def kama_bands(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               kama_period: int = 6, atr_period: int = 11,
               band_mult: float = 3.0,
               shift: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """KAMA with ATR bands, matching Chris's POC Bands indicator.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        kama_period: KAMA efficiency period (default 6).
        atr_period: ATR period for band width (default 11).
        band_mult: ATR multiplier for bands (default 3.0).
        shift: Bars to shift the basis backward (default 3).

    Returns:
        (basis, upper_band, lower_band) as numpy arrays.
    """
    hlc3_data = (high + low + close) / 3.0
    basis_raw = kama(hlc3_data, period=kama_period)
    atr_vals = atr(high, low, close, period=atr_period, use_ema=True)

    n = len(close)
    basis = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(shift, n):
        if not np.isnan(basis_raw[i - shift]) and not np.isnan(atr_vals[i]):
            basis[i] = basis_raw[i - shift]
            upper[i] = basis[i] + band_mult * atr_vals[i]
            lower[i] = basis[i] - band_mult * atr_vals[i]

    return basis, upper, lower


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index.

    Uses Wilder's smoothing method (exponential moving average with
    alpha = 1/period). Values range from 0 to 100.

    Interpretation:
        > 70: Overbought
        < 30: Oversold
        50: Neutral

    Args:
        close: Close price array.
        period: RSI lookback (default 14).

    Returns:
        RSI values as numpy array. First `period` values are NaN.
    """
    n = len(close)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return result


def stoch_rsi(close: np.ndarray, rsi_period: int = 14,
              stoch_period: int = 14, k_smooth: int = 3,
              d_smooth: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic RSI.

    Applies the stochastic formula to RSI values for more sensitive
    overbought/oversold detection.

    Args:
        close: Close price array.
        rsi_period: RSI calculation period.
        stoch_period: Stochastic lookback on RSI values.
        k_smooth: %K smoothing period.
        d_smooth: %D smoothing period (SMA of %K).

    Returns:
        (%K, %D) as numpy arrays.
    """
    rsi_vals = rsi(close, rsi_period)
    n = len(close)

    raw_k = np.full(n, np.nan)
    for i in range(rsi_period + stoch_period - 1, n):
        window = rsi_vals[i - stoch_period + 1:i + 1]
        if np.any(np.isnan(window)):
            continue
        rsi_min = np.min(window)
        rsi_max = np.max(window)
        if rsi_max - rsi_min == 0:
            raw_k[i] = 50.0
        else:
            raw_k[i] = 100.0 * (rsi_vals[i] - rsi_min) / (rsi_max - rsi_min)

    k_line = sma(raw_k, k_smooth)
    d_line = sma(k_line, d_smooth)
    return k_line, d_line


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------

def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14, use_ema: bool = False) -> np.ndarray:
    """Average True Range.

    True Range = max(H-L, |H-prevC|, |L-prevC|).
    Default uses Wilder's smoothing (RMA). Set use_ema=True for EMA smoothing
    (as used in POC Bands).

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: ATR lookback (default 14).
        use_ema: If True, use EMA instead of Wilder's smoothing.

    Returns:
        ATR values as numpy array. First `period` values are NaN (approximately).
    """
    n = len(high)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)

    if use_ema:
        return ema(tr, period)

    # Wilder's smoothing (RMA): same as EMA with alpha = 1/period
    result = np.full(n, np.nan)
    if n >= period:
        result[period - 1] = np.mean(tr[:period])
        alpha = 1.0 / period
        for i in range(period, n):
            result[i] = result[i - 1] * (1 - alpha) + tr[i] * alpha
    return result


def true_range(high: np.ndarray, low: np.ndarray,
               close: np.ndarray) -> np.ndarray:
    """True Range without smoothing.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.

    Returns:
        Per-bar true range values.
    """
    n = len(high)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
    return tr


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

@dataclass
class MACDResult:
    """MACD indicator result bundle."""
    macd_line: np.ndarray       # Fast EMA - Slow EMA
    signal_line: np.ndarray     # EMA of MACD line
    histogram: np.ndarray       # MACD - Signal

    def crossover_signals(self) -> np.ndarray:
        """MACD/Signal crossover signals.

        Returns:
            +1 = bullish (MACD crosses above signal),
            -1 = bearish (MACD crosses below signal),
             0 = no cross.
        """
        n = len(self.macd_line)
        signals = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if (np.isnan(self.macd_line[i]) or np.isnan(self.signal_line[i])
                    or np.isnan(self.macd_line[i - 1])
                    or np.isnan(self.signal_line[i - 1])):
                continue
            prev_above = self.macd_line[i - 1] > self.signal_line[i - 1]
            curr_above = self.macd_line[i] > self.signal_line[i]
            if not prev_above and curr_above:
                signals[i] = 1
            elif prev_above and not curr_above:
                signals[i] = -1
        return signals


def macd(close: np.ndarray, fast_period: int = 12, slow_period: int = 26,
         signal_period: int = 9) -> MACDResult:
    """Moving Average Convergence Divergence.

    Classic momentum/trend indicator. MACD line is the difference between
    fast and slow EMA. Signal line is an EMA of the MACD line. Histogram
    visualizes the divergence between MACD and signal.

    Args:
        close: Close price array.
        fast_period: Fast EMA period (default 12).
        slow_period: Slow EMA period (default 26).
        signal_period: Signal line EMA period (default 9).

    Returns:
        MACDResult with macd_line, signal_line, and histogram.
    """
    fast_ema = ema(close, fast_period)
    slow_ema = ema(close, slow_period)
    macd_line = fast_ema - slow_ema

    # Signal line: EMA of MACD, but only from where MACD is valid
    # Find first valid MACD index
    first_valid = slow_period - 1
    macd_valid = macd_line[first_valid:]
    signal_valid = ema(macd_valid, signal_period)

    signal_line = np.full(len(close), np.nan)
    signal_line[first_valid:first_valid + len(signal_valid)] = signal_valid

    histogram = macd_line - signal_line

    return MACDResult(
        macd_line=macd_line,
        signal_line=signal_line,
        histogram=histogram,
    )


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

@dataclass
class BollingerResult:
    """Bollinger Bands result bundle."""
    middle: np.ndarray          # SMA (basis)
    upper: np.ndarray           # SMA + mult * StdDev
    lower: np.ndarray           # SMA - mult * StdDev
    bandwidth: np.ndarray       # (upper - lower) / middle
    percent_b: np.ndarray       # (close - lower) / (upper - lower)


def bollinger_bands(close: np.ndarray, period: int = 20,
                    mult: float = 2.0) -> BollingerResult:
    """Bollinger Bands.

    Volatility bands placed above and below a moving average. Band width
    adapts to volatility (wider in volatile markets, narrower in calm).

    Args:
        close: Close price array.
        period: SMA/StdDev lookback (default 20).
        mult: Standard deviation multiplier (default 2.0).

    Returns:
        BollingerResult with middle, upper, lower, bandwidth, and %B.
    """
    n = len(close)
    middle = sma(close, period)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    bandwidth = np.full(n, np.nan)
    percent_b = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = close[i - period + 1:i + 1]
        std = np.std(window, ddof=0)  # Population std (TradingView default)
        upper[i] = middle[i] + mult * std
        lower[i] = middle[i] - mult * std
        if middle[i] != 0:
            bandwidth[i] = (upper[i] - lower[i]) / middle[i]
        band_range = upper[i] - lower[i]
        if band_range != 0:
            percent_b[i] = (close[i] - lower[i]) / band_range

    return BollingerResult(
        middle=middle,
        upper=upper,
        lower=lower,
        bandwidth=bandwidth,
        percent_b=percent_b,
    )


# ---------------------------------------------------------------------------
# VWAP (from Chris's TradingView indicator)
# ---------------------------------------------------------------------------

def vwap(close: np.ndarray, volume: np.ndarray,
         high: np.ndarray | None = None,
         low: np.ndarray | None = None,
         anchor_indices: np.ndarray | None = None) -> np.ndarray:
    """Volume Weighted Average Price.

    VWAP = cumulative(typical_price * volume) / cumulative(volume).
    Resets at each anchor point (session start, etc.).

    If high and low are provided, uses typical price (H+L+C)/3.
    Otherwise uses close as the price source.

    Args:
        close: Close prices.
        volume: Volume array.
        high: High prices (optional, for typical price).
        low: Low prices (optional, for typical price).
        anchor_indices: Bar indices where VWAP resets (e.g., session starts).
            If None, computes a single continuous VWAP over all data.

    Returns:
        VWAP values as numpy array.
    """
    n = len(close)
    if high is not None and low is not None:
        src = (high + low + close) / 3.0
    else:
        src = close.copy()

    result = np.full(n, np.nan)

    if anchor_indices is None or len(anchor_indices) == 0:
        # Single continuous VWAP
        cum_pv = np.cumsum(src * volume)
        cum_v = np.cumsum(volume)
        mask = cum_v > 0
        result[mask] = cum_pv[mask] / cum_v[mask]
        return result

    # Anchored VWAP with resets
    anchors = set(anchor_indices)
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(n):
        if i in anchors:
            cum_pv = 0.0
            cum_v = 0.0
        cum_pv += src[i] * volume[i]
        cum_v += volume[i]
        if cum_v > 0:
            result[i] = cum_pv / cum_v

    return result


def vwap_bands(close: np.ndarray, volume: np.ndarray,
               high: np.ndarray | None = None,
               low: np.ndarray | None = None,
               anchor_indices: np.ndarray | None = None,
               mult: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """VWAP with standard deviation bands.

    Matches Chris's TradingView VWAP indicator with band calculation.

    Args:
        close: Close prices.
        volume: Volume array.
        high: High prices (optional).
        low: Low prices (optional).
        anchor_indices: Reset points.
        mult: Band multiplier (default 1.0 = 1 standard deviation).

    Returns:
        (vwap_line, upper_band, lower_band) as numpy arrays.
    """
    n = len(close)
    if high is not None and low is not None:
        src = (high + low + close) / 3.0
    else:
        src = close.copy()

    vwap_line = np.full(n, np.nan)
    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)

    anchors = set(anchor_indices) if anchor_indices is not None else set()
    use_anchors = len(anchors) > 0

    cum_pv = 0.0
    cum_v = 0.0
    cum_pv2 = 0.0  # For variance: cumulative(price^2 * volume)

    for i in range(n):
        if use_anchors and i in anchors:
            cum_pv = 0.0
            cum_v = 0.0
            cum_pv2 = 0.0

        cum_pv += src[i] * volume[i]
        cum_v += volume[i]
        cum_pv2 += src[i] * src[i] * volume[i]

        if cum_v > 0:
            v = cum_pv / cum_v
            vwap_line[i] = v
            # Volume-weighted variance
            variance = cum_pv2 / cum_v - v * v
            if variance > 0:
                std = np.sqrt(variance)
                upper_band[i] = v + mult * std
                lower_band[i] = v - mult * std
            else:
                upper_band[i] = v
                lower_band[i] = v

    return vwap_line, upper_band, lower_band


# ---------------------------------------------------------------------------
# Klinger Oscillator (from Chris's TradingView indicator)
# ---------------------------------------------------------------------------

@dataclass
class KlingerResult:
    """Klinger Volume Oscillator result."""
    kvo: np.ndarray             # Klinger oscillator line
    signal: np.ndarray          # Signal line (EMA of KVO)

    def crossover_signals(self) -> np.ndarray:
        """KVO/Signal crossover signals.

        Returns:
            +1 = bullish, -1 = bearish, 0 = no cross.
        """
        n = len(self.kvo)
        signals = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if (np.isnan(self.kvo[i]) or np.isnan(self.signal[i])
                    or np.isnan(self.kvo[i - 1])
                    or np.isnan(self.signal[i - 1])):
                continue
            prev_above = self.kvo[i - 1] > self.signal[i - 1]
            curr_above = self.kvo[i] > self.signal[i]
            if not prev_above and curr_above:
                signals[i] = 1
            elif prev_above and not curr_above:
                signals[i] = -1
        return signals


def klinger(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            volume: np.ndarray, fast_period: int = 34,
            slow_period: int = 55,
            signal_period: int = 13) -> KlingerResult:
    """Klinger Volume Oscillator.

    Measures the difference between buying and selling volume pressure.
    From Chris's TradingView indicator.

    The sign of volume is determined by the direction of the typical
    price (hlc3): if hlc3 rises, volume is positive (accumulation);
    if hlc3 falls, volume is negative (distribution).

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        volume: Volume array.
        fast_period: Fast EMA period (default 34).
        slow_period: Slow EMA period (default 55).
        signal_period: Signal EMA period (default 13).

    Returns:
        KlingerResult with KVO line and signal line.
    """
    hlc3 = (high + low + close) / 3.0
    n = len(hlc3)

    # Signed volume: positive if hlc3 rises, negative if it falls
    sv = np.zeros(n)
    for i in range(1, n):
        if hlc3[i] >= hlc3[i - 1]:
            sv[i] = volume[i]
        else:
            sv[i] = -volume[i]
    sv[0] = volume[0]  # First bar: assume positive

    kvo_line = ema(sv, fast_period) - ema(sv, slow_period)

    # Signal line from valid KVO values
    first_valid = slow_period - 1
    kvo_valid = kvo_line[first_valid:]
    sig_valid = ema(kvo_valid, signal_period)
    signal_line = np.full(n, np.nan)
    signal_line[first_valid:first_valid + len(sig_valid)] = sig_valid

    return KlingerResult(kvo=kvo_line, signal=signal_line)


# ---------------------------------------------------------------------------
# Fibonacci Retracement / Extension (from Auto Fib Extension indicator)
# ---------------------------------------------------------------------------

# Standard Fibonacci levels used in Chris's Auto Fib Extension
FIBONACCI_LEVELS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0,
                    1.272, 1.414, 1.618, 2.618, 3.618, 4.236)


def fibonacci_retracement(swing_high: float, swing_low: float,
                          levels: tuple[float, ...] = FIBONACCI_LEVELS
                          ) -> dict[float, float]:
    """Compute Fibonacci retracement levels between two price points.

    In a retracement after an upswing, levels are measured from the high
    downward. 0.0 = the high, 1.0 = the low.

    Args:
        swing_high: The swing high price.
        swing_low: The swing low price.
        levels: Fibonacci ratios to compute (default: standard set).

    Returns:
        Dict mapping each Fibonacci ratio to its price level.
    """
    diff = swing_high - swing_low
    return {level: swing_high - diff * level for level in levels}


def fibonacci_extension(start: float, end: float, retracement: float,
                        levels: tuple[float, ...] = FIBONACCI_LEVELS
                        ) -> dict[float, float]:
    """Compute Fibonacci extension levels.

    Projects levels beyond the retracement point, based on the initial
    swing distance. Matches Auto Fib Extension indicator logic.

    Args:
        start: Initial swing start price.
        end: Initial swing end price (the extreme).
        retracement: The retracement price.
        levels: Fibonacci ratios to compute.

    Returns:
        Dict mapping each ratio to its price level.
    """
    diff = abs(start - end)
    is_upswing = end > start  # Original move was up
    result = {}
    for level in levels:
        if is_upswing:
            result[level] = retracement + diff * level
        else:
            result[level] = retracement - diff * level
    return result


def find_swing_points(high: np.ndarray, low: np.ndarray,
                      depth: int = 10) -> tuple[list[tuple[int, float]],
                                                 list[tuple[int, float]]]:
    """Detect pivot swing highs and lows.

    Implements the same pivot logic as the Auto Fib Extension indicator:
    a pivot high is a bar whose high is the highest in a window of
    `depth` bars on either side.

    Args:
        high: High prices.
        low: Low prices.
        depth: Minimum bars on each side for a pivot (default 10).

    Returns:
        (swing_highs, swing_lows) where each is a list of (index, price).
    """
    n = len(high)
    half = depth // 2
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(half, n - half):
        # Check swing high
        is_high = True
        for j in range(i - half, i + half + 1):
            if j == i:
                continue
            if j < 0 or j >= n:
                continue
            if high[j] > high[i]:
                is_high = False
                break
        if is_high:
            swing_highs.append((i, float(high[i])))

        # Check swing low
        is_low = True
        for j in range(i - half, i + half + 1):
            if j == i:
                continue
            if j < 0 or j >= n:
                continue
            if low[j] < low[i]:
                is_low = False
                break
        if is_low:
            swing_lows.append((i, float(low[i])))

    return swing_highs, swing_lows


def auto_fib_levels(high: np.ndarray, low: np.ndarray,
                    depth: int = 10) -> dict[float, float] | None:
    """Automatic Fibonacci level detection.

    Finds the most recent swing high and swing low, then computes
    retracement levels. Returns None if insufficient pivot data.

    Args:
        high: High prices.
        low: Low prices.
        depth: Pivot detection depth.

    Returns:
        Dict of Fibonacci level -> price, or None if no pivots found.
    """
    swing_highs, swing_lows = find_swing_points(high, low, depth)
    if not swing_highs or not swing_lows:
        return None

    # Use most recent pivots
    last_high_idx, last_high_price = swing_highs[-1]
    last_low_idx, last_low_price = swing_lows[-1]

    return fibonacci_retracement(last_high_price, last_low_price)


# ---------------------------------------------------------------------------
# Kagi (from Kagi Overlay indicator -- trend filter)
# ---------------------------------------------------------------------------

def kagi(close: np.ndarray,
         reversal_pct: float = 0.001) -> tuple[np.ndarray, np.ndarray]:
    """Kagi chart values as overlay.

    Kagi charts filter noise by only reversing direction when price moves
    by more than the reversal threshold. Useful as a trend filter: when
    price is above kagi, trend is up (bullish); below = bearish.

    From Chris's TradingView Kagi Overlay indicator.

    Args:
        close: Close price array.
        reversal_pct: Reversal threshold as a fraction of price
            (default 0.001 = 0.1%).

    Returns:
        (kagi_line, trend) where:
            kagi_line: The Kagi level at each bar.
            trend: +1.0 for bullish (price > kagi), -1.0 for bearish.
    """
    n = len(close)
    kagi_line = np.full(n, np.nan)
    trend = np.zeros(n)

    if n == 0:
        return kagi_line, trend

    kagi_line[0] = close[0]
    direction = 1.0  # 1 = up, -1 = down
    current_kagi = close[0]

    for i in range(1, n):
        reversal_amount = current_kagi * reversal_pct
        if direction > 0:
            if close[i] > current_kagi:
                current_kagi = close[i]
            elif close[i] < current_kagi - reversal_amount:
                direction = -1.0
                current_kagi = close[i]
        else:
            if close[i] < current_kagi:
                current_kagi = close[i]
            elif close[i] > current_kagi + reversal_amount:
                direction = 1.0
                current_kagi = close[i]

        kagi_line[i] = current_kagi
        trend[i] = 1.0 if close[i] > current_kagi else -1.0

    return kagi_line, trend


# ---------------------------------------------------------------------------
# Donchian Channel
# ---------------------------------------------------------------------------

def donchian_channel(high: np.ndarray, low: np.ndarray,
                     period: int = 20) -> tuple[np.ndarray, np.ndarray,
                                                np.ndarray]:
    """Donchian Channel (used internally by Ichimoku).

    Args:
        high: High prices.
        low: Low prices.
        period: Lookback window.

    Returns:
        (upper, lower, middle) where upper = highest high, lower = lowest low,
        middle = midpoint.
    """
    n = len(high)
    upper_ch = np.full(n, np.nan)
    lower_ch = np.full(n, np.nan)
    middle_ch = np.full(n, np.nan)

    for i in range(period - 1, n):
        hh = np.max(high[i - period + 1:i + 1])
        ll = np.min(low[i - period + 1:i + 1])
        upper_ch[i] = hh
        lower_ch[i] = ll
        middle_ch[i] = (hh + ll) / 2.0

    return upper_ch, lower_ch, middle_ch


# ---------------------------------------------------------------------------
# On-Balance Volume (OBV)
# ---------------------------------------------------------------------------

def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """On-Balance Volume.

    Cumulative volume with sign determined by close-to-close direction.
    Useful for confirming price trends with volume flow.

    Args:
        close: Close prices.
        volume: Volume array.

    Returns:
        OBV values as numpy array.
    """
    n = len(close)
    result = np.zeros(n)
    result[0] = volume[0]
    for i in range(1, n):
        if close[i] > close[i - 1]:
            result[i] = result[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            result[i] = result[i - 1] - volume[i]
        else:
            result[i] = result[i - 1]
    return result


# ---------------------------------------------------------------------------
# ADX (Average Directional Index)
# ---------------------------------------------------------------------------

@dataclass
class ADXResult:
    """ADX indicator result."""
    adx: np.ndarray         # Average Directional Index
    plus_di: np.ndarray     # +DI (positive directional indicator)
    minus_di: np.ndarray    # -DI (negative directional indicator)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
        period: int = 14) -> ADXResult:
    """Average Directional Index.

    Measures trend strength (not direction). ADX > 25 indicates a strong
    trend; ADX < 20 indicates a weak/ranging market.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Smoothing period (default 14).

    Returns:
        ADXResult with ADX, +DI, and -DI arrays.
    """
    n = len(high)
    adx_vals = np.full(n, np.nan)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)

    if n < period + 1:
        return ADXResult(adx=adx_vals, plus_di=plus_di, minus_di=minus_di)

    # True Range
    tr = true_range(high, low, close)

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Wilder's smoothing for TR, +DM, -DM
    alpha = 1.0 / period
    sm_tr = np.full(n, np.nan)
    sm_plus = np.full(n, np.nan)
    sm_minus = np.full(n, np.nan)

    sm_tr[period] = np.sum(tr[1:period + 1])
    sm_plus[period] = np.sum(plus_dm[1:period + 1])
    sm_minus[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        sm_tr[i] = sm_tr[i - 1] - sm_tr[i - 1] / period + tr[i]
        sm_plus[i] = sm_plus[i - 1] - sm_plus[i - 1] / period + plus_dm[i]
        sm_minus[i] = sm_minus[i - 1] - sm_minus[i - 1] / period + minus_dm[i]

    # DI calculations
    for i in range(period, n):
        if sm_tr[i] > 0:
            plus_di[i] = 100.0 * sm_plus[i] / sm_tr[i]
            minus_di[i] = 100.0 * sm_minus[i] / sm_tr[i]
        else:
            plus_di[i] = 0.0
            minus_di[i] = 0.0

    # DX and ADX
    dx = np.full(n, np.nan)
    for i in range(period, n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # First ADX = SMA of first `period` DX values
    first_adx_idx = 2 * period
    if first_adx_idx < n:
        dx_slice = dx[period:first_adx_idx]
        valid_dx = dx_slice[~np.isnan(dx_slice)]
        if len(valid_dx) > 0:
            adx_vals[first_adx_idx - 1] = np.mean(valid_dx)
            for i in range(first_adx_idx, n):
                if not np.isnan(dx[i]) and not np.isnan(adx_vals[i - 1]):
                    adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period

    return ADXResult(adx=adx_vals, plus_di=plus_di, minus_di=minus_di)


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------

def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               period: int = 10,
               multiplier: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """Supertrend indicator.

    Trend-following overlay that flips between support (bullish) and
    resistance (bearish) based on ATR volatility bands.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: ATR period (default 10).
        multiplier: ATR multiplier (default 3.0).

    Returns:
        (supertrend_line, direction) where direction is +1 (bullish) or
        -1 (bearish).
    """
    n = len(high)
    atr_vals = atr(high, low, close, period)

    hl2 = (high + low) / 2.0
    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.ones(n)

    for i in range(period - 1, n):
        if np.isnan(atr_vals[i]):
            continue
        upper_band[i] = hl2[i] + multiplier * atr_vals[i]
        lower_band[i] = hl2[i] - multiplier * atr_vals[i]

    # Adjust bands based on previous values
    for i in range(period, n):
        if np.isnan(upper_band[i]) or np.isnan(lower_band[i]):
            continue

        if not np.isnan(upper_band[i - 1]):
            if upper_band[i] > upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
                pass
            else:
                upper_band[i] = upper_band[i - 1]

        if not np.isnan(lower_band[i - 1]):
            if lower_band[i] < lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
                pass
            else:
                lower_band[i] = lower_band[i - 1]

        # Direction
        if not np.isnan(st[i - 1]):
            if st[i - 1] == upper_band[i - 1]:
                direction[i] = -1.0 if close[i] > upper_band[i] else 1.0
                # Correction: if close crosses above upper, flip to bullish
                if close[i] > upper_band[i]:
                    direction[i] = 1.0
                else:
                    direction[i] = -1.0
            else:
                if close[i] < lower_band[i]:
                    direction[i] = -1.0
                else:
                    direction[i] = 1.0

        st[i] = lower_band[i] if direction[i] > 0 else upper_band[i]

    # Fill initial
    for i in range(period - 1, n):
        if not np.isnan(st[i]):
            break
        if not np.isnan(lower_band[i]):
            st[i] = lower_band[i]

    return st, direction


# ---------------------------------------------------------------------------
# Composite signal helpers
# ---------------------------------------------------------------------------

def ichimoku_composite_score(ichi: IchimokuCloud,
                             close: np.ndarray) -> np.ndarray:
    """Score Ichimoku setup strength from -5 (max bearish) to +5 (max bullish).

    Five components, each contributing +1 or -1:
        1. Price vs Cloud: above cloud = +1, below = -1
        2. Cloud direction: bullish (A > B) = +1, bearish = -1
        3. Tenkan vs Kijun: Tenkan > Kijun = +1, else -1
        4. Chikou vs price (26 bars ago): above = +1, below = -1
        5. Cloud thickness trend: thickening bullish cloud = +1, etc.

    Args:
        ichi: IchimokuCloud result.
        close: Close price array.

    Returns:
        Array of integer scores from -5 to +5.
    """
    n = len(close)
    score = np.zeros(n, dtype=np.int8)

    position = ichi.price_vs_cloud(close)
    cloud_top = ichi.cloud_top
    cloud_bot = ichi.cloud_bottom

    for i in range(n):
        s = 0

        # 1. Price vs cloud
        if position[i] == "above":
            s += 1
        elif position[i] == "below":
            s -= 1

        # 2. Cloud direction
        if ichi.cloud_direction[i] == CloudDirection.BULLISH:
            s += 1
        elif ichi.cloud_direction[i] == CloudDirection.BEARISH:
            s -= 1

        # 3. Tenkan vs Kijun
        if (not np.isnan(ichi.tenkan_sen[i])
                and not np.isnan(ichi.kijun_sen[i])):
            if ichi.tenkan_sen[i] > ichi.kijun_sen[i]:
                s += 1
            elif ichi.tenkan_sen[i] < ichi.kijun_sen[i]:
                s -= 1

        # 4. Chikou vs historical price
        if not np.isnan(ichi.chikou_span[i]):
            # Chikou at bar i represents current close plotted 26 bars back.
            # We compare current close to the close that was 26 bars ago.
            lookback = 25  # displacement - 1
            if i >= lookback:
                if close[i] > close[i - lookback]:
                    s += 1
                elif close[i] < close[i - lookback]:
                    s -= 1

        # 5. Cloud thickness trend
        thickness = ichi.cloud_thickness
        if i >= 1 and not np.isnan(thickness[i]) and not np.isnan(thickness[i - 1]):
            if ichi.cloud_direction[i] == CloudDirection.BULLISH:
                if thickness[i] > thickness[i - 1]:
                    s += 1
                else:
                    s -= 1
            elif ichi.cloud_direction[i] == CloudDirection.BEARISH:
                if thickness[i] > thickness[i - 1]:
                    s -= 1
                else:
                    s += 1

        score[i] = s

    return score


def multi_indicator_confluence(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
) -> np.ndarray:
    """Compute a multi-indicator confluence score.

    Combines Ichimoku, RSI, MACD, and Bollinger %B into a single
    normalized score from -1.0 (max bearish) to +1.0 (max bullish).

    Weights:
        Ichimoku composite: 40% (Chris's priority)
        MACD histogram sign: 20%
        RSI zone: 20%
        Bollinger %B: 20%

    Args:
        close: Close prices.
        high: High prices.
        low: Low prices.
        volume: Volume array.

    Returns:
        Confluence score array, normalized to [-1.0, +1.0].
    """
    n = len(close)
    result = np.full(n, np.nan)

    # Components
    ichi = ichimoku(high, low, close)
    ichi_score = ichimoku_composite_score(ichi, close)

    macd_result = macd(close)
    rsi_vals = rsi(close)
    bb = bollinger_bands(close)

    for i in range(n):
        components = 0
        total = 0.0

        # Ichimoku (40%)
        if ichi_score[i] != 0:
            total += 0.40 * (ichi_score[i] / 5.0)
            components += 1
        elif i > 0:
            # If score is 0, it's genuinely neutral
            components += 1

        # MACD (20%)
        if not np.isnan(macd_result.histogram[i]):
            if macd_result.histogram[i] > 0:
                total += 0.20
            elif macd_result.histogram[i] < 0:
                total -= 0.20
            components += 1

        # RSI (20%)
        if not np.isnan(rsi_vals[i]):
            # Map RSI to [-1, 1]: RSI 50 = 0, RSI 70+ = +1, RSI 30- = -1
            rsi_normalized = (rsi_vals[i] - 50.0) / 50.0
            rsi_normalized = max(-1.0, min(1.0, rsi_normalized))
            total += 0.20 * rsi_normalized
            components += 1

        # Bollinger %B (20%)
        if not np.isnan(bb.percent_b[i]):
            # %B: 0 = at lower band, 1 = at upper band, 0.5 = at middle
            bb_normalized = (bb.percent_b[i] - 0.5) * 2.0
            bb_normalized = max(-1.0, min(1.0, bb_normalized))
            total += 0.20 * bb_normalized
            components += 1

        if components > 0:
            result[i] = max(-1.0, min(1.0, total))

    return result
