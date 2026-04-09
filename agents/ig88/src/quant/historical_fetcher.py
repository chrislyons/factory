"""
historical_fetcher.py — Deep historical OHLCV fetching for IG-88.

Sources:
  Primary:   Binance public klines API (no key, 1000 bars/page, back to 2017)
  Secondary: Kraken public OHLC API (no key, 720 bars max, used for cross-validation)

Design:
  - Full pagination via startTime/endTime windows
  - Parquet on disk, keyed by {exchange}_{symbol}_{interval}m.parquet
  - Incremental update: only fetches missing tail, never re-downloads full history
  - Symbol normalization: IG-88 config symbols -> exchange-specific pair names
  - Deduplication on timestamp before save
  - Progress reporting on long fetches

Usage:
  python3 src/quant/historical_fetcher.py           # fetch all configured symbols
  python3 src/quant/historical_fetcher.py --check   # print what's on disk
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Symbol maps
# ---------------------------------------------------------------------------

# IG-88 config name -> Binance symbol
BINANCE_SYMBOL_MAP: dict[str, str] = {
    "BTC/USD":   "BTCUSDT",
    "ETH/USDT":  "ETHUSDT",
    "SOL/USDT":  "SOLUSDT",
    "LINK/USD":  "LINKUSDT",
    "NEAR/USD":  "NEARUSDT",
    "AVAX/USD":  "AVAXUSDT",
    "XRP/USD":   "XRPUSDT",
    "DOGE/USD":  "DOGEUSDT",
    "ATOM/USD":  "ATOMUSDT",
    "FIL/USD":   "FILUSDT",
    "INJ/USD":   "INJUSDT",
    "JUP/USD":   "JUPUSDT",
    "WIF/USD":   "WIFUSDT",
    "BONK/USD":  "BONKUSDT",
    "GRT/USD":   "GRTUSDT",
    "TAO/USD":   "TAOUSDT",
    "RENDER/USD": "RENDERUSDT",
    "TIA/USD":   "TIAUSDT",
    "UNI/USD":   "UNIUSDT",
    "FET/USD":   "FETUSDT",
    "SEI/USD":   "SEIUSDT",
    "PYTH/USD":  "PYTHUSDT",
    "W/USD":     "WUSDT",
    "ORDI/USD":  "ORDIUSDT",
    "KAS/USD":   "KASUSDT",
    "GTC/USD":   "GTCUSDT",
    "POL/USD":   "POLUSDT",
}

# Binance klines interval codes
BINANCE_INTERVAL_MAP: dict[int, str] = {
    1:    "1m",
    5:    "5m",
    15:   "15m",
    30:   "30m",
    60:   "1h",
    240:  "4h",
    1440: "1d",
}

# Binance listing dates for each symbol (earliest reliable data)
# Used as fetch floor — no point requesting data before listing
BINANCE_LISTING_DATES: dict[str, datetime] = {
    "BTCUSDT":    datetime(2017, 8, 17, tzinfo=timezone.utc),
    "ETHUSDT":    datetime(2017, 8, 17, tzinfo=timezone.utc),
    "SOLUSDT":    datetime(2020, 8, 11, tzinfo=timezone.utc),
    "LINKUSDT":   datetime(2019, 1, 16, tzinfo=timezone.utc),
    "NEARUSDT":   datetime(2020, 10, 16, tzinfo=timezone.utc),
    "AVAXUSDT":   datetime(2020, 9, 22, tzinfo=timezone.utc),
    "XRPUSDT":    datetime(2019, 1, 29, tzinfo=timezone.utc),
    "DOGEUSDT":   datetime(2019, 7, 5, tzinfo=timezone.utc),
    "ATOMUSDT":   datetime(2019, 3, 14, tzinfo=timezone.utc),
    "FILUSDT":    datetime(2020, 10, 15, tzinfo=timezone.utc),
    "INJUSDT":    datetime(2020, 10, 26, tzinfo=timezone.utc),
    "JUPUSDT":    datetime(2024, 1, 31, tzinfo=timezone.utc),
    "WIFUSDT":    datetime(2024, 1, 12, tzinfo=timezone.utc),
    "BONKUSDT":   datetime(2023, 1, 12, tzinfo=timezone.utc),
    "GRTUSDT":    datetime(2020, 12, 17, tzinfo=timezone.utc),
    "TAOUSDT":    datetime(2023, 11, 1, tzinfo=timezone.utc),
    "RENDERUSDT": datetime(2023, 11, 8, tzinfo=timezone.utc),
    "TIAUSDT":    datetime(2023, 10, 31, tzinfo=timezone.utc),
    "UNIUSDT":    datetime(2020, 9, 17, tzinfo=timezone.utc),
    "FETUSDT":    datetime(2019, 2, 28, tzinfo=timezone.utc),
    "SEIUSDT":    datetime(2023, 8, 15, tzinfo=timezone.utc),
    "PYTHUSDT":   datetime(2023, 11, 16, tzinfo=timezone.utc),
    "WUSDT":      datetime(2024, 4, 3, tzinfo=timezone.utc),
    "ORDIUSDT":   datetime(2023, 5, 8, tzinfo=timezone.utc),
    "KASUSDT":    datetime(2023, 2, 22, tzinfo=timezone.utc),
    "GTCUSDT":    datetime(2021, 5, 25, tzinfo=timezone.utc),
    "POLUSDT":    datetime(2023, 9, 14, tzinfo=timezone.utc),
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get_json(url: str, timeout: int = 15, retries: int = 4) -> object:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IG-88-TradingBot/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {url}")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            raise RuntimeError(f"Fetch failed: {url}: {e}")
    raise RuntimeError(f"Max retries: {url}")


# ---------------------------------------------------------------------------
# Binance fetcher
# ---------------------------------------------------------------------------

BINANCE_BASE = "https://api.binance.com/api/v3/klines"


def fetch_binance_page(
    symbol: str,
    interval_code: str,
    start_ms: int,
    end_ms: Optional[int] = None,
    limit: int = 1000,
) -> list[dict]:
    """Fetch a single page of Binance klines. Returns list of OHLCV dicts."""
    url = f"{BINANCE_BASE}?symbol={symbol}&interval={interval_code}&startTime={start_ms}&limit={limit}"
    if end_ms:
        url += f"&endTime={end_ms}"

    raw = _http_get_json(url)
    if not isinstance(raw, list):
        raise RuntimeError(f"Unexpected Binance response: {raw}")

    candles = []
    for c in raw:
        candles.append({
            "time":   int(c[0]) // 1000,   # ms -> seconds
            "open":   float(c[1]),
            "high":   float(c[2]),
            "low":    float(c[3]),
            "close":  float(c[4]),
            "volume": float(c[5]),
        })
    return candles


def fetch_binance_full(
    symbol: str,
    interval_min: int,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    page_delay: float = 0.12,
) -> pd.DataFrame:
    """
    Fetch complete history from Binance for a symbol/interval, paginating as needed.

    symbol: Binance symbol e.g. 'BTCUSDT'
    interval_min: interval in minutes (must be in BINANCE_INTERVAL_MAP)
    start_dt: UTC datetime to start from (default: listing date or 5yr ago)
    end_dt: UTC datetime to end at (default: now)
    page_delay: seconds between pages (0.12 = ~8 req/sec, well under 1200/min limit)

    Returns DataFrame with DatetimeIndex (UTC), columns: time, open, high, low, close, volume
    """
    if interval_min not in BINANCE_INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval_min}m. Valid: {list(BINANCE_INTERVAL_MAP.keys())}")

    interval_code = BINANCE_INTERVAL_MAP[interval_min]
    listing_dt = BINANCE_LISTING_DATES.get(symbol, datetime(2019, 1, 1, tzinfo=timezone.utc))

    if start_dt is None:
        # Default: 5 years back, but not before listing date
        five_yr_ago = datetime.now(timezone.utc) - timedelta(days=5 * 365)
        start_dt = max(five_yr_ago, listing_dt)

    if end_dt is None:
        end_dt = datetime.now(timezone.utc)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)
    interval_ms = interval_min * 60 * 1000

    all_candles: list[dict] = []
    cursor_ms = start_ms
    page_num = 0

    while cursor_ms < end_ms:
        page_num += 1
        candles = fetch_binance_page(symbol, interval_code, cursor_ms, end_ms, limit=1000)

        if not candles:
            break

        all_candles.extend(candles)
        last_ts_ms = candles[-1]["time"] * 1000
        cursor_ms = last_ts_ms + interval_ms

        pct = min(100, (last_ts_ms - start_ms) / (end_ms - start_ms) * 100)
        last_dt = datetime.fromtimestamp(candles[-1]["time"], tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"    page {page_num:3d}: {len(candles):4d} bars  up to {last_dt}  [{pct:5.1f}%]")

        if len(candles) < 1000:
            break  # Last page

        if cursor_ms >= end_ms:
            break

        time.sleep(page_delay)

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles)
    # Deduplicate on timestamp
    df = df.drop_duplicates(subset="time")
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df


# ---------------------------------------------------------------------------
# Disk cache management
# ---------------------------------------------------------------------------

def cache_path(exchange: str, symbol: str, interval_min: int) -> Path:
    safe = symbol.replace("/", "_")
    return DATA_DIR / f"{exchange}_{safe}_{interval_min}m.parquet"


def load_cached(exchange: str, symbol: str, interval_min: int) -> Optional[pd.DataFrame]:
    p = cache_path(exchange, symbol, interval_min)
    if p.exists():
        return pd.read_parquet(p)
    return None


def save_cached(df: pd.DataFrame, exchange: str, symbol: str, interval_min: int) -> Path:
    p = cache_path(exchange, symbol, interval_min)
    df.to_parquet(p)
    return p


def incremental_update(
    exchange: str,
    symbol: str,
    interval_min: int,
    fetch_fn,
) -> pd.DataFrame:
    """
    Load existing cache, determine what's missing, fetch only the gap, merge and save.
    Returns the complete up-to-date DataFrame.
    """
    existing = load_cached(exchange, symbol, interval_min)

    if existing is not None and not existing.empty:
        # Find latest timestamp in cache
        latest_cached = existing.index[-1]
        gap_start = latest_cached + pd.Timedelta(minutes=interval_min)
        now = pd.Timestamp.now(tz="UTC")

        if gap_start >= now - pd.Timedelta(minutes=interval_min * 2):
            print(f"  [current] {symbol} {interval_min}m — {len(existing)} bars, up to {latest_cached.date()}")
            return existing

        print(f"  [update]  {symbol} {interval_min}m — cached to {latest_cached.date()}, fetching tail...")
        new_data = fetch_fn(start_dt=gap_start.to_pydatetime())

        if new_data.empty:
            return existing

        combined = pd.concat([existing, new_data])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
    else:
        print(f"  [full]    {symbol} {interval_min}m — no cache, fetching full history...")
        combined = fetch_fn()

        if combined.empty:
            print(f"  [warn]    No data returned for {symbol} {interval_min}m")
            return pd.DataFrame()

    p = save_cached(combined, exchange, symbol, interval_min)
    print(f"  [saved]   {len(combined)} bars -> {p.name}")
    return combined


# ---------------------------------------------------------------------------
# Fetch plan: what we want
# ---------------------------------------------------------------------------

# Priority symbols for backtesting + paper trading
FETCH_PLAN = [
    # (ig88_symbol, interval_min, years_back)
    # Tier 1 — deep history, all intervals
    ("BTC/USD",  1440, 8),   # ~2920 daily candles; BTC back to 2017 on Binance
    ("ETH/USDT", 1440, 8),
    ("SOL/USDT", 1440, 5),   # SOL listed Aug 2020

    ("BTC/USD",  240,  3),   # 4h: 3yr = ~6570 bars (7 pages)
    ("ETH/USDT", 240,  3),
    ("SOL/USDT", 240,  3),

    ("BTC/USD",  60,   1),   # 1h: 1yr = ~8760 bars (9 pages)
    ("SOL/USDT", 60,   1),

    # Tier 2 — daily only for backtest screening
    ("LINK/USD",  1440, 5),
    ("AVAX/USD",  1440, 5),
    ("XRP/USD",   1440, 5),
    ("DOGE/USD",  1440, 5),
    ("ATOM/USD",  1440, 5),
    ("INJ/USD",   1440, 3),
    ("NEAR/USD",  1440, 5),
    ("GRT/USD",   1440, 5),
    ("UNI/USD",   1440, 5),
    ("FET/USD",   1440, 5),

    # Tier 3 — newer tokens, daily only
    ("BONK/USD",  1440, 2),
    ("WIF/USD",   1440, 2),
    ("TIA/USD",   1440, 2),
    ("RENDER/USD",1440, 2),
    ("SEI/USD",   1440, 2),
    ("PYTH/USD",  1440, 2),
    ("ORDI/USD",  1440, 2),
    ("JUP/USD",   1440, 1),
    ("W/USD",     1440, 1),
]


def run_fetch_plan(symbols: Optional[list[str]] = None, dry_run: bool = False):
    """
    Execute the fetch plan, incrementally updating all configured symbols.

    symbols: optional filter list of ig88 symbol names
    dry_run: just print what would be fetched, don't fetch
    """
    print(f"\n{'='*60}")
    print(f"IG-88 Historical Data Fetch")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    plan = FETCH_PLAN
    if symbols:
        plan = [(s, i, y) for s, i, y in plan if s in symbols]

    total_bytes_before = sum(p.stat().st_size for p in DATA_DIR.glob("binance_*.parquet")) if not dry_run else 0

    for ig88_sym, interval_min, years_back in plan:
        binance_sym = BINANCE_SYMBOL_MAP.get(ig88_sym)
        if not binance_sym:
            print(f"  [skip] {ig88_sym} — no Binance mapping")
            continue

        listing_dt = BINANCE_LISTING_DATES.get(binance_sym, datetime(2019, 1, 1, tzinfo=timezone.utc))
        cutoff_dt  = datetime.now(timezone.utc) - timedelta(days=years_back * 365)
        start_dt   = max(cutoff_dt, listing_dt)

        if dry_run:
            interval_label = BINANCE_INTERVAL_MAP.get(interval_min, f"{interval_min}m")
            total_bars = int((datetime.now(timezone.utc) - start_dt).total_seconds() / (interval_min * 60))
            pages = (total_bars // 1000) + 1
            print(f"  {ig88_sym:<15} {interval_label:<5}  from {start_dt.date()}  ~{total_bars:5d} bars  {pages} pages")
            continue

        def make_fetch_fn(sym, itvl_min, s_dt):
            def fetch_fn(start_dt=s_dt):
                return fetch_binance_full(sym, itvl_min, start_dt=start_dt)
            return fetch_fn

        fetch_fn = make_fetch_fn(binance_sym, interval_min, start_dt)

        try:
            df = incremental_update("binance", ig88_sym, interval_min, fetch_fn)
            if not df.empty:
                span = f"{df.index[0].date()} -> {df.index[-1].date()}"
                print(f"    {len(df):6d} bars  {span}")
        except Exception as e:
            print(f"  [ERROR] {ig88_sym} {interval_min}m: {e}")

    if not dry_run:
        total_bytes_after = sum(p.stat().st_size for p in DATA_DIR.glob("binance_*.parquet"))
        delta_mb = (total_bytes_after - total_bytes_before) / (1024 * 1024)
        total_mb = total_bytes_after / (1024 * 1024)
        print(f"\nDisk usage: {total_mb:.1f} MB total  (+{delta_mb:.1f} MB this run)")


def check_coverage():
    """Print a summary of what data is currently on disk."""
    print(f"\n{'='*60}")
    print("On-disk OHLCV Coverage")
    print(f"{'='*60}")

    files = sorted(DATA_DIR.glob("*.parquet"))
    if not files:
        print("  No parquet files found.")
        return

    print(f"  {'File':<45} {'Bars':>6}  {'From':<12} {'To':<12}  {'MB':>5}")
    print(f"  {'-'*45} {'-'*6}  {'-'*12} {'-'*12}  {'-'*5}")

    for f in files:
        try:
            df = pd.read_parquet(f)
            if df.empty:
                print(f"  {f.name:<45}  empty")
                continue
            mb = f.stat().st_size / (1024 * 1024)
            from_dt = df.index[0].date() if hasattr(df.index[0], "date") else "?"
            to_dt   = df.index[-1].date() if hasattr(df.index[-1], "date") else "?"
            print(f"  {f.name:<45} {len(df):>6}  {str(from_dt):<12} {str(to_dt):<12}  {mb:>5.2f}")
        except Exception as e:
            print(f"  {f.name:<45}  ERROR: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IG-88 Historical OHLCV Fetcher")
    parser.add_argument("--check",    action="store_true", help="Show coverage summary only")
    parser.add_argument("--dry-run",  action="store_true", help="Print fetch plan without fetching")
    parser.add_argument("--symbols",  nargs="+",           help="Filter to specific symbols e.g. BTC/USD SOL/USDT")
    parser.add_argument("--tier1",    action="store_true", help="Fetch Tier 1 only (BTC/ETH/SOL)")
    args = parser.parse_args()

    if args.check:
        check_coverage()
    elif args.dry_run:
        syms = args.symbols
        if args.tier1:
            syms = ["BTC/USD", "ETH/USDT", "SOL/USDT"]
        run_fetch_plan(symbols=syms, dry_run=True)
    else:
        syms = args.symbols
        if args.tier1:
            syms = ["BTC/USD", "ETH/USDT", "SOL/USDT"]
        run_fetch_plan(symbols=syms)
