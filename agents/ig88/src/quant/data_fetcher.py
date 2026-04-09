"""
data_fetcher.py — Live OHLCV and macro data sourcing for IG-88.

Primary: Kraken REST API (public, no key) for OHLCV
Secondary: CoinGecko (public) for macro regime signals
Tertiary: alternative.me for Fear & Greed Index

All data is cached to disk in parquet format to avoid redundant API calls.
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Try pandas/numpy — required for parquet cache
try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Kraken pair name mapping (IG-88 config names -> Kraken API names)
KRAKEN_PAIR_MAP = {
    "BTC/USD":  "XBTUSD",
    "ETH/USDT": "ETHUSD",   # Kraken uses USD not USDT
    "SOL/USDT": "SOLUSD",
    "LINK/USD": "LINKUSD",
    "NEAR/USD": "NEARUSD",
    "AVAX/USD": "AVAXUSD",
    "XRP/USD":  "XRPUSD",
    "DOGE/USD": "XDGUSD",
    "ATOM/USD": "ATOMUSD",
    "FIL/USD":  "FILUSD",
    "INJ/USD":  "INJUSD",
    "JUP/USD":  "JUPUSD",
    "WIF/USD":  "WIFUSD",
    "BONK/USD": "BONKUSD",
    "GRT/USD":  "GRTUSD",
}

# Interval mapping: minutes -> Kraken interval code
KRAKEN_INTERVALS = {
    1: 1, 5: 5, 15: 15, 30: 30, 60: 60, 240: 240, 1440: 1440
}


def _http_get(url: str, timeout: int = 15, retries: int = 3) -> dict:
    """Simple HTTP GET with JSON parsing and exponential backoff on 429."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IG-88-TradingBot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 ** (attempt + 1)  # 2, 4 seconds
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code} fetching {url}: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {url}: {e}")
    raise RuntimeError(f"Max retries exceeded for {url}")


def fetch_kraken_ohlcv(pair: str, interval_min: int = 1440, since: Optional[int] = None) -> list[dict]:
    """
    Fetch OHLCV candles from Kraken public API.

    pair: Kraken pair name e.g. 'XBTUSD'
    interval_min: candle interval in minutes (1, 5, 15, 30, 60, 240, 1440)
    since: Unix timestamp to fetch from (default: last 720 candles)

    Returns list of dicts with keys: time, open, high, low, close, volume
    """
    if interval_min not in KRAKEN_INTERVALS:
        raise ValueError(f"Invalid interval {interval_min}. Valid: {list(KRAKEN_INTERVALS.keys())}")

    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval_min}"
    if since:
        url += f"&since={since}"

    data = _http_get(url)
    if data.get("error"):
        raise RuntimeError(f"Kraken API error for {pair}: {data['error']}")

    # Response key is the pair name (sometimes differs slightly)
    result_key = [k for k in data["result"] if k != "last"][0]
    raw = data["result"][result_key]

    candles = []
    for c in raw:
        candles.append({
            "time":   int(c[0]),
            "open":   float(c[1]),
            "high":   float(c[2]),
            "low":    float(c[3]),
            "close":  float(c[4]),
            "vwap":   float(c[5]),
            "volume": float(c[6]),
            "count":  int(c[7]),
        })
    return candles


def fetch_and_cache_ohlcv(symbol: str, interval_min: int = 1440, force_refresh: bool = False) -> "pd.DataFrame":
    """
    Fetch OHLCV for a symbol, using disk cache if recent enough.

    symbol: IG-88 config name e.g. 'BTC/USD'
    interval_min: candle interval
    force_refresh: bypass cache

    Returns DataFrame with columns: time, open, high, low, close, volume (indexed by time)
    """
    if not HAS_PANDAS:
        raise RuntimeError("pandas required for fetch_and_cache_ohlcv")

    pair = KRAKEN_PAIR_MAP.get(symbol)
    if not pair:
        raise ValueError(f"No Kraken mapping for symbol: {symbol}")

    safe_sym = symbol.replace("/", "_")
    cache_path = DATA_DIR / f"{safe_sym}_{interval_min}m.parquet"

    # Check cache freshness: stale if > interval_min minutes old
    cache_age_minutes = float("inf")
    if cache_path.exists() and not force_refresh:
        mtime = cache_path.stat().st_mtime
        cache_age_minutes = (time.time() - mtime) / 60
        if cache_age_minutes < interval_min * 0.5:
            df = pd.read_parquet(cache_path)
            print(f"  [cache] {symbol} {interval_min}m — {len(df)} candles (age: {cache_age_minutes:.0f}m)")
            return df

    print(f"  [fetch] {symbol} ({pair}) {interval_min}m candles...")
    candles = fetch_kraken_ohlcv(pair, interval_min)
    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()

    df.to_parquet(cache_path)
    print(f"  [saved] {len(df)} candles -> {cache_path.name}")
    return df


# ---------------------------------------------------------------------------
# Macro / Regime Data
# ---------------------------------------------------------------------------

def fetch_fear_and_greed() -> dict:
    """
    Fetch Fear & Greed Index from alternative.me.
    Returns: {value: int, classification: str, timestamp: int}
    """
    url = "https://api.alternative.me/fng/?limit=1&format=json"
    data = _http_get(url)
    entry = data["data"][0]
    return {
        "value": int(entry["value"]),
        "classification": entry["value_classification"],
        "timestamp": int(entry["timestamp"]),
    }


def fetch_btc_dominance() -> float:
    """
    Fetch BTC dominance % from CoinGecko.
    Returns: float (e.g. 54.3)
    """
    url = "https://api.coingecko.com/api/v3/global"
    data = _http_get(url)
    return float(data["data"]["market_cap_percentage"].get("btc", 0.0))


def fetch_btc_7d_trend() -> dict:
    """
    Fetch BTC price change over 7 days from CoinGecko.
    Uses market_chart endpoint for accurate 7d delta (simple/price 7d field unreliable on free tier).
    Returns: {price_usd: float, change_7d_pct: float, change_24h_pct: float}
    """
    # 7-day chart for accurate 7d delta
    url7 = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=7&interval=daily"
    data7 = _http_get(url7)
    prices = data7["prices"]
    p0 = float(prices[0][1])
    p_now = float(prices[-1][1])
    change_7d = (p_now - p0) / p0 * 100 if p0 else 0.0

    # 24h via simple endpoint
    url24 = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
    data24 = _http_get(url24)
    btc24 = data24["bitcoin"]

    return {
        "price_usd":      float(btc24.get("usd", p_now)),
        "change_24h_pct": float(btc24.get("usd_24h_change", 0)),
        "change_7d_pct":  change_7d,
    }


def fetch_total_market_cap() -> dict:
    """
    Fetch total crypto market cap and 24h change from CoinGecko.
    Returns: {total_mcap_usd: float, change_24h_pct: float}
    """
    url = "https://api.coingecko.com/api/v3/global"
    data = _http_get(url)
    g = data["data"]
    return {
        "total_mcap_usd": float(g.get("total_market_cap", {}).get("usd", 0)),
        "change_24h_pct": float(g.get("market_cap_change_percentage_24h_usd", 0)),
    }


def fetch_sol_funding_rate() -> dict:
    """
    Fetch SOL-PERP funding rate from Jupiter's on-chain stats via Birdeye public endpoint.
    Falls back to 0.0 if unavailable (Jupiter doesn't expose a dead-simple public REST endpoint yet).

    Returns: {rate_8h: float, annualized_pct: float}
    """
    # Jupiter Perps doesn't have a trivial public REST funding endpoint yet.
    # Use a known public aggregator. Falling back gracefully.
    try:
        # Coinglass has SOL funding — try their public endpoint
        url = "https://open-api.coinglass.com/public/v2/funding?symbol=SOL"
        data = _http_get(url, timeout=8)
        if data.get("success"):
            rates = data.get("data", [])
            for entry in rates:
                if entry.get("exchangeName", "").lower() == "jupiter":
                    rate = float(entry.get("fundingRate", 0))
                    return {"rate_8h": rate, "annualized_pct": rate * 3 * 365 * 100}
    except Exception:
        pass

    # Fallback: neutral funding
    return {"rate_8h": 0.0, "annualized_pct": 0.0, "source": "fallback"}


def fetch_all_regime_signals() -> dict:
    """
    Aggregate all regime signals into a single dict for regime.py consumption.
    Tolerates individual failures — marks failed signals as None.

    Strategy: fetch non-CoinGecko sources first, then batch CoinGecko calls
    with explicit spacing to avoid 429s on the free tier.
    """
    signals = {}

    # 1. Fear & Greed (alternative.me — not CoinGecko, no rate limit concern)
    try:
        signals["fear_greed"] = fetch_fear_and_greed()
        print(f"  [ok] fear_greed")
    except Exception as e:
        signals["fear_greed"] = None
        print(f"  [fail] fear_greed: {e}")

    # 2. Funding (Coinglass / fallback — separate domain)
    try:
        signals["sol_funding"] = fetch_sol_funding_rate()
        print(f"  [ok] sol_funding")
    except Exception as e:
        signals["sol_funding"] = None
        print(f"  [fail] sol_funding: {e}")

    # 3. CoinGecko: BTC 7d trend (uses market_chart + simple/price — 2 calls)
    time.sleep(1.5)
    try:
        signals["btc_trend"] = fetch_btc_7d_trend()
        print(f"  [ok] btc_trend")
    except Exception as e:
        signals["btc_trend"] = None
        print(f"  [fail] btc_trend: {e}")

    # 4. CoinGecko: global (dominance + mcap) — shares same /global endpoint, 1 call
    time.sleep(2.0)
    try:
        url = "https://api.coingecko.com/api/v3/global"
        data = _http_get(url)
        g = data["data"]
        signals["btc_dominance"] = float(g["market_cap_percentage"].get("btc", 50.0))
        signals["market_cap"] = {
            "total_mcap_usd": float(g.get("total_market_cap", {}).get("usd", 0)),
            "change_24h_pct": float(g.get("market_cap_change_percentage_24h_usd", 0)),
        }
        print(f"  [ok] btc_dominance + market_cap (batched)")
    except Exception as e:
        signals["btc_dominance"] = None
        signals["market_cap"] = None
        print(f"  [fail] coingecko_global: {e}")

    signals["fetched_at"] = int(time.time())
    return signals


def regime_signals_to_inputs(signals: dict) -> tuple[dict, dict]:
    """
    Convert raw fetched signals into the format expected by regime.assess_regime().
    Returns: (market_data, macro_data)
    """
    market_data = {}
    macro_data = {}

    # BTC trend
    btc = signals.get("btc_trend") or {}
    market_data["btc_change_7d"] = btc.get("change_7d_pct", 0.0)
    market_data["btc_change_24h"] = btc.get("change_24h_pct", 0.0)
    market_data["btc_price"] = btc.get("price_usd", 0.0)

    # Fear & Greed
    fg = signals.get("fear_greed") or {}
    macro_data["fear_greed_index"] = fg.get("value", 50)
    macro_data["fear_greed_class"] = fg.get("classification", "Neutral")

    # BTC dominance
    dom = signals.get("btc_dominance")
    macro_data["btc_dominance"] = dom if dom is not None else 50.0

    # Market cap
    mcap = signals.get("market_cap") or {}
    macro_data["mcap_change_24h"] = mcap.get("change_24h_pct", 0.0)

    # Funding
    funding = signals.get("sol_funding") or {}
    macro_data["sol_funding_8h"] = funding.get("rate_8h", 0.0)

    return market_data, macro_data


if __name__ == "__main__":
    print("=== IG-88 Data Fetcher Test ===")
    print()

    # Test OHLCV fetch
    print("-- OHLCV: BTC/USD daily --")
    df_btc = fetch_and_cache_ohlcv("BTC/USD", interval_min=1440)
    print(f"   Shape: {df_btc.shape}")
    print(f"   Date range: {df_btc.index[0].date()} -> {df_btc.index[-1].date()}")
    print(f"   Latest close: ${df_btc['close'].iloc[-1]:,.2f}")
    print()

    print("-- OHLCV: SOL/USDT daily --")
    df_sol = fetch_and_cache_ohlcv("SOL/USDT", interval_min=1440)
    print(f"   Shape: {df_sol.shape}")
    print(f"   Latest close: ${df_sol['close'].iloc[-1]:,.2f}")
    print()

    print("-- Regime Signals --")
    signals = fetch_all_regime_signals()
    print()
    for k, v in signals.items():
        if k != "fetched_at":
            print(f"   {k}: {v}")
    print()

    market_data, macro_data = regime_signals_to_inputs(signals)
    print("-- Regime Inputs --")
    print(f"   market_data: {market_data}")
    print(f"   macro_data:  {macro_data}")
