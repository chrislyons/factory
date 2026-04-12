import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# IG-88 config name -> Binance symbol
BINANCE_SYMBOL_MAP: dict[str, str] = {
    "BTC/USD":   "BTCUSDT",
    "ETH/USDT":  "ETHUSDT",
    "SOL/USDT":  "SOLUSDT",
    "LINK/USD":  "LINKUSDT",
    "NEAR/USD":  "NEARUSDT",
    "AVAX/USD":  "AVAXUSDT",
}

# Binance klines interval codes
BINANCE_INTERVAL_MAP: dict[int, str] = {
    15:   "15m",
    60:   "1h",
    120:  "2h",
    240:  "4h",
    1440: "1d",
}

# Binance listing dates for each symbol
BINANCE_LISTING_DATES: dict[str, datetime] = {
    "BTCUSDT":    datetime(2017, 8, 17, tzinfo=timezone.utc),
    "ETHUSDT":    datetime(2017, 8, 17, tzinfo=timezone.utc),
    "SOLUSDT":    datetime(2020, 8, 11, tzinfo=timezone.utc),
    "LINKUSDT":   datetime(2019, 1, 16, tzinfo=timezone.utc),
    "NEARUSDT":   datetime(2020, 10, 16, tzinfo=timezone.utc),
    "AVAXUSDT":   datetime(2020, 9, 22, tzinfo=timezone.utc),
}

def _http_get_json(url: str, timeout: int = 15, retries: int = 4) -> object:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IG-88-DataVault/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code}: {url}")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            raise RuntimeError(f"Fetch failed: {url}: {e}")
    raise RuntimeError(f"Max retries: {url}")

BINANCE_BASE = "https://api.binance.com/api/v3/klines"

def fetch_binance_full(symbol: str, interval_min: int, start_dt: Optional[datetime] = None) -> pd.DataFrame:
    interval_code = BINANCE_INTERVAL_MAP[interval_min]
    listing_dt = BINANCE_LISTING_DATES.get(symbol, datetime(2019, 1, 1, tzinfo=timezone.utc))
    
    if start_dt is None:
        start_dt = max(datetime.now(timezone.utc) - timedelta(days=5 * 365), listing_dt)
    
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)
    interval_ms = interval_min * 60 * 1000
    
    all_candles = []
    cursor_ms = start_ms
    
    while cursor_ms < end_ms:
        url = f"{BINANCE_BASE}?symbol={symbol}&interval={interval_code}&startTime={cursor_ms}&limit=1000"
        raw = _http_get_json(url)
        if not raw or not isinstance(raw, list): break
        
        candles = [{"time": int(c[0])//1000, "open": float(c[1]), "high": float(c[2]), 
                    "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in raw]
        all_candles.extend(candles)
        
        if len(raw) < 1000: break
        cursor_ms = candles[-1]["time"] * 1000 + interval_ms
        time.sleep(0.12)
        
    if not all_candles: return pd.DataFrame()
    df = pd.DataFrame(all_candles)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("datetime").sort_index()

def run_vault_fill():
    print(f"Initiating Vault Fill: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    for ig88_sym, binance_sym in BINANCE_SYMBOL_MAP.items():
        for interval_min in BINANCE_INTERVAL_MAP.keys():
            print(f"Fetching {ig88_sym} {interval_min}m...", end=" ")
            try:
                df = fetch_binance_full(binance_sym, interval_min)
                if not df.empty:
                    safe = binance_sym 
                    path = DATA_DIR / f"binance_{safe}_{interval_min}m.parquet"
                    df.to_parquet(path)
                    print(f"Done ({len(df)} bars)")
                else:
                    print("No data found.")
            except Exception as e:
                print(f"FAILED: {e}")

if __name__ == "__main__":
    run_vault_fill()
