"""
Indicator Cache
===============
Pre-computed indicators cached to parquet for fast re-scanning.
Instead of recomputing RSI, ATR, Bollinger Bands on every scan,
we compute once and cache the result.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indicator_cache"


def _cache_key(symbol: str, timeframe: str, indicators: list[str]) -> str:
    """Generate a deterministic cache key."""
    key_str = f"{symbol}:{timeframe}:{':'.join(sorted(indicators))}"
    return hashlib.md5(key_str.encode()).hexdigest()[:12]


def compute_and_cache(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "4h",
    indicators: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Compute standard indicators and cache the result.

    Args:
        df: OHLCV DataFrame with columns: timestamp, open, high, low, close, volume
        symbol: Asset symbol
        timeframe: Candle timeframe
        indicators: List of indicators to compute. Default: all standard ones.

    Returns:
        DataFrame with original OHLCV + indicator columns.
    """
    if indicators is None:
        indicators = ["rsi", "atr", "bb", "sma20", "sma200", "vol_ratio", "ichimoku"]

    # Check cache
    cached = _load_cache(symbol, timeframe, indicators)
    if cached is not None and len(cached) >= len(df) - 2:
        return cached

    # Compute
    result = df.copy()
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values

    if "rsi" in indicators:
        result["rsi"] = _compute_rsi(c, 14)

    if "atr" in indicators:
        result["atr"] = _compute_atr(h, l, c, 14)
        result["atr_pct"] = result["atr"] / c

    if "bb" in indicators:
        sma20 = pd.Series(c).rolling(20).mean().values
        std20 = pd.Series(c).rolling(20).std().values
        result["bb_upper"] = sma20 + std20 * 2
        result["bb_middle"] = sma20
        result["bb_lower"] = sma20 - std20 * 2
        result["bb_width"] = (result["bb_upper"] - result["bb_lower"]) / sma20
        result["bb_position"] = np.where(std20 > 0, (c - sma20) / std20, 0)

    if "sma20" in indicators:
        result["sma20"] = pd.Series(c).rolling(20).mean()

    if "sma200" in indicators:
        result["sma200"] = pd.Series(c).rolling(200).mean()

    if "vol_ratio" in indicators:
        vol_sma = pd.Series(v).rolling(20).mean().values
        result["vol_sma20"] = vol_sma
        result["vol_ratio"] = np.where(vol_sma > 0, v / vol_sma, 1.0)

    if "ichimoku" in indicators:
        tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
        kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26)
        result["tenkan"] = tenkan.values
        result["kijun"] = kijun.values
        result["senkou_a"] = senkou_a.values
        result["senkou_b"] = senkou_b.values

    # Save to cache
    _save_cache(result, symbol, timeframe, indicators)

    return result


def _compute_rsi(c: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute RSI using EMA method."""
    delta = np.diff(c, prepend=c[0])
    gain = np.clip(delta, 0, None)
    loss = np.clip(-delta, None, 0)
    gain_ema = pd.Series(gain).ewm(alpha=1 / period, min_periods=period).mean().values
    loss_ema = pd.Series(loss).ewm(alpha=1 / period, min_periods=period).mean().values
    rsi = np.where(loss_ema > 0, 100 - (100 / (1 + gain_ema / loss_ema)), 50.0)
    return rsi


def _compute_atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute Average True Range."""
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(period).mean().values
    return atr


def _load_cache(
    symbol: str, timeframe: str, indicators: list[str]
) -> Optional[pd.DataFrame]:
    """Load cached indicator data if it exists."""
    key = _cache_key(symbol, timeframe, indicators)
    path = CACHE_DIR / f"{symbol}_{timeframe}_{key}.parquet"

    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception as e:
            logger.warning(f"Failed to load cache {path}: {e}")

    return None


def _save_cache(
    df: pd.DataFrame, symbol: str, timeframe: str, indicators: list[str]
) -> None:
    """Save indicator data to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(symbol, timeframe, indicators)
    path = CACHE_DIR / f"{symbol}_{timeframe}_{key}.parquet"

    try:
        df.to_parquet(path, index=False)
    except Exception as e:
        logger.warning(f"Failed to save cache {path}: {e}")


def invalidate_cache(symbol: str | None = None, timeframe: str | None = None) -> int:
    """Clear cached indicators. Returns number of files removed."""
    count = 0
    if not CACHE_DIR.exists():
        return 0

    for path in CACHE_DIR.glob("*.parquet"):
        name = path.stem
        parts = name.split("_")

        if symbol and parts[0] != symbol:
            continue
        if timeframe and len(parts) > 1 and parts[1] != timeframe:
            continue

        try:
            path.unlink()
            count += 1
        except OSError:
            pass

    return count


def warm_cache(symbols: list[str], timeframe: str = "4h") -> dict[str, int]:
    """Pre-compute indicators for a list of symbols.

    Returns dict of {symbol: bar_count} for successfully cached symbols.
    """
    from src.data.market_data import load_ohlcv

    results = {}
    for sym in symbols:
        try:
            df = load_ohlcv(sym, timeframe)
            if df is not None and len(df) > 50:
                compute_and_cache(df, sym, timeframe)
                results[sym] = len(df)
        except Exception as e:
            logger.warning(f"Failed to warm cache for {sym}: {e}")

    return results
