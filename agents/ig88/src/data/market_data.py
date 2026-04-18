"""
Market Data
===========
Unified OHLCV data loader. Sources:
1. Local parquet files (cached historical data)
2. Binance public API (no key needed for klines)
3. Hyperliquid API

All sources return a standardized DataFrame with columns:
  timestamp, open, high, low, close, volume
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Binance interval mapping
INTERVAL_MAP = {
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1440m": "1d",
}

# Parquet file naming: binance_{symbol}_{tf}.parquet
# e.g., binance_BTC_USDT_240m.parquet


def load_ohlcv(
    symbol: str,
    timeframe: str = "4h",
    source: str = "auto",
    lookback_bars: int | None = None,
) -> Optional[pd.DataFrame]:
    """Load OHLCV data for a symbol.

    Args:
        symbol: Asset symbol (e.g., "BTC", "SOL", "BTC/USDT")
        timeframe: Candle timeframe ("15m", "1h", "4h", "1d")
        source: "local", "binance", or "auto" (try local first, then API)
        lookback_bars: Optional limit on number of bars to return

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        or None if data cannot be loaded.
    """
    # Normalize symbol
    clean_sym = symbol.replace("/", "_").replace("-", "_").split("USDT")[0].rstrip("_")

    if source == "auto" or source == "local":
        df = _load_local(clean_sym, timeframe)
        if df is not None and len(df) > 0:
            if lookback_bars:
                df = df.tail(lookback_bars)
            return df

    if source == "auto" or source == "binance":
        df = _fetch_binance(clean_sym, timeframe)
        if df is not None and len(df) > 0:
            # Cache to local
            _save_local(df, clean_sym, timeframe)
            if lookback_bars:
                df = df.tail(lookback_bars)
            return df

    return None


def _load_local(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Try to load from local parquet files."""
    tf_map = {"1h": "60m", "4h": "240m", "1d": "1440m", "15m": "15m"}
    tf_str = tf_map.get(timeframe, timeframe)

    candidates = [
        DATA_DIR / f"binance_{symbol}_USDT_{tf_str}.parquet",
        DATA_DIR / "ohlcv" / timeframe / f"binance_{symbol}_USDT_{tf_str}.parquet",
        DATA_DIR / "ohlcv" / "1h" / f"binance_{symbol}_USDT_{tf_str}.parquet",
    ]

    for path in candidates:
        if path.exists():
            try:
                df = pd.read_parquet(path)
                return _standardize(df)
            except Exception as e:
                logger.warning(f"Failed to read {path}: {e}")

    return None


def _save_local(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """Save DataFrame to local parquet cache."""
    tf_map = {"1h": "60m", "4h": "240m", "1d": "1440m", "15m": "15m"}
    tf_str = tf_map.get(timeframe, timeframe)

    out_dir = DATA_DIR / "ohlcv" / timeframe
    out_dir.mkdir(parents=True, exist_ok=True)

    path = out_dir / f"binance_{symbol}_USDT_{tf_str}.parquet"
    try:
        df.to_parquet(path, index=False)
    except Exception as e:
        logger.warning(f"Failed to cache {path}: {e}")


def _fetch_binance(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV from Binance public API."""
    interval = INTERVAL_MAP.get(timeframe, timeframe)
    pair = f"{symbol.upper()}USDT"

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={pair}&interval={interval}&limit=1000"
    )

    try:
        req = Request(url, headers={"User-Agent": "ig88-bot"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        if not data:
            return None

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])

        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        return df[["timestamp", "open", "high", "low", "close", "volume"]]

    except (URLError, json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to fetch Binance {pair} {interval}: {e}")
        return None


def _standardize(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame has standard columns."""
    # If it has a datetime index, reset it
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    # Rename columns if needed
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("datetime", "date", "time"):
            col_map[c] = "timestamp"
        elif cl in ("o",):
            col_map[c] = "open"
        elif cl in ("h",):
            col_map[c] = "high"
        elif cl in ("l",):
            col_map[c] = "low"
        elif cl in ("c",):
            col_map[c] = "close"
        elif cl in ("v", "vol"):
            col_map[c] = "volume"

    if col_map:
        df = df.rename(columns=col_map)

    # Ensure required columns exist
    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Ensure timestamp
    if "timestamp" not in df.columns:
        if "open_time" in df.columns:
            df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
        else:
            df["timestamp"] = pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq="4h")

    return df


def load_multiple(
    symbols: list[str],
    timeframe: str = "4h",
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for multiple symbols.

    Returns dict of {symbol: DataFrame}.
    """
    result = {}
    for sym in symbols:
        try:
            df = load_ohlcv(sym, timeframe)
            if df is not None:
                result[sym] = df
        except Exception as e:
            logger.warning(f"Failed to load {sym}: {e}")
    return result
