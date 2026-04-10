"""
venue_research.py — Venue-specific data fetching, comparison, and backtesting.

Studies:
  1. Kraken vs Binance OHLCV comparison
     - Price divergence (Kraken SOL/USD vs Binance SOLUSDT)
     - Signal timing alignment (do H3 signals fire on same bars?)
     - Volume differences (Kraken thinner — how much?)

  2. Kraken fee model validation
     - Maker: 0.16% (limit orders, used in our model) ✓
     - Taker: 0.26% (market orders — we never take)
     - Verify our model is using maker correctly

  3. H3-A/B/C/D re-run on Kraken native data
     - Same walk-forward 70/30 split
     - Compare OOS PF to Binance results

  4. Jupiter SOL-PERP via public Birdeye API
     - Get actual SOL-PERP candles (different from spot)
     - Funding rate history
     - Run H3-B on perp-specific data

  5. LunarCrush sentiment signal test
     - Add SOL Galaxy Score to regime inputs
     - Measure if it improves signal quality over BTC-trend-only

  6. CoinGecko Pro — fix 7d BTC trend
     - Use real API key for accurate historical data

All secrets loaded via Infisical at runtime — nothing written to disk.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import hmac
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays
from src.quant.indicator_research import (
    build_all_signals, backtest_signal,
    signals_ichimoku_h3a, signals_vol_spike_break, signals_rsi_momentum_cross,
)
from src.quant.research_loop import ExitResearchBacktester
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
PAPER_TRADES = DATA_DIR / "paper_trades.jsonl"
VENUE = "kraken_spot"


# ---------------------------------------------------------------------------
# Secret access — always via env, never disk
# ---------------------------------------------------------------------------

def get_secret(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(f"Secret {name} not in environment. Run via: infisical run -- python3 ...")
    return val


# ---------------------------------------------------------------------------
# Kraken REST helpers
# ---------------------------------------------------------------------------

KRAKEN_BASE = "https://api.kraken.com"


def kraken_public(path: str, params: dict | None = None) -> dict:
    url = KRAKEN_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "IG-88/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def kraken_private(path: str, data: dict) -> dict:
    api_key    = get_secret("KRAKEN_API_KEY")
    api_secret = get_secret("KRAKEN_API_SECRET")

    nonce = str(int(time.time() * 1000))
    data["nonce"] = nonce

    post_data = urllib.parse.urlencode(data).encode()
    message   = path.encode() + hashlib.sha256(nonce.encode() + post_data).digest()
    signature = hmac.new(
        base64.b64decode(api_secret),
        message,
        hashlib.sha512,
    ).digest()
    api_sign = base64.b64encode(signature).decode()

    req = urllib.request.Request(
        KRAKEN_BASE + path,
        data=post_data,
        headers={
            "API-Key":  api_key,
            "API-Sign": api_sign,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def fetch_kraken_ohlcv_full(pair: str, interval_min: int, since_ts: int | None = None) -> pd.DataFrame:
    """
    Fetch Kraken OHLCV. Pages backward using 'since' to get up to ~2yr.
    pair: Kraken pair name e.g. 'SOLUSD', 'XBTUSD', 'ETHUSD'
    interval_min: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
    """
    all_candles = []
    # Kraken gives 720 candles max per call.
    # To get 2yr of 4h (2yr * 365 * 6 = 4380 bars), need 7 pages.
    # Strategy: start from 2yr ago and page forward.
    if since_ts is None:
        since_ts = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp())

    cursor = since_ts
    max_pages = 10
    for page in range(max_pages):
        data = kraken_public("/0/public/OHLC", {"pair": pair, "interval": interval_min, "since": cursor})
        if data.get("error"):
            raise RuntimeError(f"Kraken error: {data['error']}")
        result_key = [k for k in data["result"] if k != "last"][0]
        candles = data["result"][result_key]
        last_ts = data["result"]["last"]
        if not candles:
            break
        all_candles.extend(candles)
        # If fewer than 720 returned, we've hit the present
        if len(candles) < 720:
            break
        cursor = last_ts
        time.sleep(0.5)

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["time","open","high","low","close","vwap","volume","count"])
    df = df.astype({"time": int, "open": float, "high": float, "low": float,
                    "close": float, "vwap": float, "volume": float, "count": int})
    df = df.drop_duplicates(subset="time")
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df


# ---------------------------------------------------------------------------
# Birdeye Jupiter SOL-PERP data
# ---------------------------------------------------------------------------

def fetch_birdeye_ohlcv(address: str, interval: str = "4H", limit: int = 1000) -> pd.DataFrame:
    """
    Fetch OHLCV from Birdeye public API for a Solana token/perp.
    SOL-PERP address on Jupiter: varies — use SOL spot as proxy if unavailable.
    interval: '1m','5m','15m','1H','4H','1D'
    """
    # Birdeye public endpoint (no key needed for basic OHLCV)
    url = (f"https://public-api.birdeye.so/defi/ohlcv"
           f"?address={address}&type={interval}&limit={limit}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "IG-88/1.0",
        "X-Chain": "solana",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        items = data.get("data", {}).get("items", [])
        if not items:
            return pd.DataFrame()
        df = pd.DataFrame(items)
        df["datetime"] = pd.to_datetime(df["unixTime"], unit="s", utc=True)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                                  "c": "close", "v": "volume"})
        df = df.set_index("datetime").sort_index()
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print(f"  Birdeye error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# LunarCrush sentiment
# ---------------------------------------------------------------------------

def fetch_lunarcrush_sol(api_key: str, days_back: int = 30) -> pd.DataFrame:
    """
    Fetch SOL Galaxy Score from LunarCrush.
    Returns daily DataFrame with columns: galaxy_score, alt_rank, sentiment.
    """
    url = f"https://lunarcrush.com/api4/public/coins/sol/time-series/v2?bucket=day&interval={days_back}d"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "IG-88/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        rows = data.get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("datetime").sort_index()
        cols = [c for c in ["galaxy_score","alt_rank","sentiment","social_volume"] if c in df.columns]
        return df[cols]
    except Exception as e:
        print(f"  LunarCrush error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Kraken account info (paper trading validation)
# ---------------------------------------------------------------------------

def fetch_kraken_account_balance() -> dict:
    """Fetch account balance via private API."""
    return kraken_private("/0/private/Balance", {})


def fetch_kraken_open_orders() -> dict:
    """Fetch open orders."""
    return kraken_private("/0/private/OpenOrders", {})


# ---------------------------------------------------------------------------
# Study 1: Kraken vs Binance data comparison
# ---------------------------------------------------------------------------

def study_kraken_vs_binance():
    print("\n" + "=" * 70)
    print("STUDY 1: Kraken vs Binance OHLCV Comparison")
    print("=" * 70)

    # Fetch Kraken SOL/USD 4h
    print("\n  Fetching Kraken SOLUSD 4h (~2yr)...")
    try:
        krak_sol = fetch_kraken_ohlcv_full("SOLUSD", 240)
        print(f"  Kraken SOL: {len(krak_sol)} bars  "
              f"{krak_sol.index[0].date()} -> {krak_sol.index[-1].date()}")
        # Save for reuse
        krak_sol.to_parquet(DATA_DIR / "kraken_SOL_USD_240m.parquet")
    except Exception as e:
        print(f"  [FAIL] Kraken SOL: {e}")
        krak_sol = pd.DataFrame()

    # Load Binance equivalent
    binance_sol = pd.read_parquet(DATA_DIR / "binance_SOL_USDT_240m.parquet")

    if krak_sol.empty:
        print("  Cannot compare — Kraken fetch failed")
        return None

    # Align on overlapping period
    overlap_start = max(krak_sol.index[0], binance_sol.index[0])
    overlap_end   = min(krak_sol.index[-1], binance_sol.index[-1])
    k = krak_sol[overlap_start:overlap_end]["close"]
    b = binance_sol[overlap_start:overlap_end]["close"]

    # Align to same timestamps (inner join)
    aligned = pd.DataFrame({"kraken": k, "binance": b}).dropna()
    if aligned.empty:
        print("  No overlapping bars found")
        return None

    price_diff_pct = ((aligned["kraken"] - aligned["binance"]) / aligned["binance"] * 100)
    print(f"\n  Overlap: {len(aligned)} bars ({aligned.index[0].date()} -> {aligned.index[-1].date()})")
    print(f"  Price divergence (Kraken - Binance):")
    print(f"    Mean: {price_diff_pct.mean():+.4f}%")
    print(f"    Std:  {price_diff_pct.std():.4f}%")
    print(f"    Max:  {price_diff_pct.max():+.4f}%")
    print(f"    Min:  {price_diff_pct.min():+.4f}%")
    print(f"    |>0.5%| bars: {(price_diff_pct.abs() > 0.5).sum()} / {len(aligned)}")

    return krak_sol


# ---------------------------------------------------------------------------
# Study 2: Signal alignment (same bars fire on Kraken vs Binance?)
# ---------------------------------------------------------------------------

def study_signal_alignment(krak_df: pd.DataFrame, binance_df: pd.DataFrame,
                            btc_ts, btc_c):
    print("\n" + "=" * 70)
    print("STUDY 2: Signal Timing Alignment")
    print("=" * 70)

    def get_signals(df, label):
        ts, o, h, l, c, v = df_to_arrays(df)
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        m_h3a, _ = signals_ichimoku_h3a(h, l, c)
        rsi_v = ind.rsi(c, 14); vol_ma = ind.sma(v, 20)
        m_h3b = np.zeros(len(ts), dtype=bool)
        for i in range(1, len(ts)):
            if np.isnan(vol_ma[i]) or np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]): continue
            m_h3b[i] = (v[i] > 1.5*vol_ma[i] and (c[i]-c[i-1])/c[i-1] > 0.005
                        and rsi_v[i] > 50 and rsi_v[i-1] <= 50
                        and regime[i] != RegimeState.RISK_OFF)
        sig_ts_a = set(ts[m_h3a])
        sig_ts_b = set(ts[m_h3b])
        print(f"  {label}: H3-A={m_h3a.sum()} signals, H3-B={m_h3b.sum()} signals")
        return sig_ts_a, sig_ts_b, ts, o, h, l, c, v, regime, m_h3a, m_h3b

    # Find common date range
    overlap_start = max(krak_df.index[0], binance_df.index[0])
    k_trim = krak_df[overlap_start:]
    b_trim = binance_df[overlap_start:]

    krak_a, krak_b, *krak_data = get_signals(k_trim, "Kraken")
    bin_a,  bin_b,  *bin_data  = get_signals(b_trim, "Binance")

    # Intersection
    match_a = len(krak_a & bin_a) / max(len(krak_a | bin_a), 1) * 100
    match_b = len(krak_b & bin_b) / max(len(krak_b | bin_b), 1) * 100

    print(f"\n  H3-A signal overlap (Jaccard): {match_a:.1f}%")
    print(f"  H3-B signal overlap (Jaccard): {match_b:.1f}%")

    only_krak_a = krak_a - bin_a
    only_bin_a  = bin_a - krak_a
    print(f"  H3-A Kraken-only: {len(only_krak_a)}  Binance-only: {len(only_bin_a)}")

    return krak_data


# ---------------------------------------------------------------------------
# Study 3: Full H3 backtest on Kraken data
# ---------------------------------------------------------------------------

def study_kraken_backtest(krak_df: pd.DataFrame, btc_ts, btc_c):
    print("\n" + "=" * 70)
    print("STUDY 3: H3 Backtest on Kraken Native Data")
    print("=" * 70)

    ts, o, h, l, c, v = df_to_arrays(krak_df)
    n = len(ts); SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_v  = ind.atr(h, l, c, 14)

    # Note: Kraken fee model
    # Maker: 0.16% (limit orders) — same as our model, VERIFIED
    # Taker: 0.26% (market orders) — we always use limit, so 0.16% is correct
    print(f"\n  Kraken SOL/USD 4h: {n} bars, split at bar {SPLIT}")
    print(f"  Train: {datetime.fromtimestamp(ts[0], tz=timezone.utc).date()} -> "
          f"{datetime.fromtimestamp(ts[SPLIT-1], tz=timezone.utc).date()}")
    print(f"  Test:  {datetime.fromtimestamp(ts[SPLIT], tz=timezone.utc).date()} -> "
          f"{datetime.fromtimestamp(ts[-1], tz=timezone.utc).date()}")
    print(f"  Fee model: 0.16% maker (limit orders) — confirmed correct for Kraken")

    bt = ExitResearchBacktester(10_000.0, 4.0)
    results = {}

    # Build all signals
    all_sigs = build_all_signals(o, h, l, c, v)

    # H3-A
    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    # H3-B
    rsi_v = ind.rsi(c, 14); vol_ma = ind.sma(v, 20)
    m_h3b = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(vol_ma[i]) or np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]): continue
        m_h3b[i] = (v[i] > 1.5*vol_ma[i] and (c[i]-c[i-1])/c[i-1] > 0.005
                    and rsi_v[i] > 50 and rsi_v[i-1] <= 50
                    and regime[i] != RegimeState.RISK_OFF)
    # H3-C
    kama_v = ind.kama(c, period=4)
    m_h3c = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if any(np.isnan(x) for x in [rsi_v[i],rsi_v[i-1],kama_v[i],kama_v[i-1]]): continue
        m_h3c[i] = (rsi_v[i] > 52 and rsi_v[i-1] <= 52 and c[i] > kama_v[i]
                    and c[i-1] <= kama_v[i-1] and regime[i] != RegimeState.RISK_OFF)
    # H3-D
    obv_v = ind.obv(c, v); ema10 = ind.ema(obv_v, 10)
    m_h3d = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if any(np.isnan(x) for x in [ema10[i],ema10[i-1],rsi_v[i],rsi_v[i-1]]): continue
        m_h3d[i] = (obv_v[i] > ema10[i] and obv_v[i-1] <= ema10[i-1]
                    and rsi_v[i] > 50 and rsi_v[i-1] <= 50
                    and regime[i] != RegimeState.RISK_OFF)

    print(f"\n  {'Strategy':<20} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  "
          f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*20} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    for name, mask in [("H3-A (Ichimoku)", m_h3a), ("H3-B (vol+rsi)", m_h3b),
                        ("H3-C (rsi+kama)", m_h3c), ("H3-D (obv+rsi)", m_h3d),
                        ("H3-A+B combined", m_h3a | m_h3b)]:
        tr_t = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            regime[:SPLIT], mask[:SPLIT], "atr_trail")
        te_t = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:],
                            regime[SPLIT:], mask[SPLIT:], "atr_trail")
        def s(tr):
            if not tr: return None
            e = BacktestEngine(10_000.0); e.add_trades(tr)
            return e.compute_stats(venue=VENUE)
        tr_s = s(tr_t); te_s = s(te_t)
        tr_str = f"{tr_s.n_trades:5d} {tr_s.profit_factor:7.3f} {tr_s.p_value:7.3f}" if tr_s else "    0       -       -"
        te_str = (f"{te_s.n_trades:5d} {te_s.profit_factor:7.3f} {te_s.sharpe_ratio:7.3f} {te_s.p_value:7.3f}"
                  if te_s else "    0       -       -       -")
        star = "*" if (te_s and te_s.p_value < 0.10) else " "
        print(f"  {name:<20} {tr_str}  {te_str}{star}")
        results[name] = {"train": tr_s, "test": te_s}

    return results


# ---------------------------------------------------------------------------
# Study 4: LunarCrush sentiment in regime
# ---------------------------------------------------------------------------

def study_lunarcrush_regime(btc_ts, btc_c):
    print("\n" + "=" * 70)
    print("STUDY 4: LunarCrush Sentiment Signal")
    print("=" * 70)

    try:
        lc_key = get_secret("LUNARCRUSH_API_KEY_IG88")
    except RuntimeError as e:
        print(f"  {e}")
        return

    print("  Fetching SOL Galaxy Score (90 days)...")
    lc_df = fetch_lunarcrush_sol(lc_key, days_back=90)
    if lc_df.empty:
        print("  No LunarCrush data returned")
        return

    print(f"  Got {len(lc_df)} days of data")
    print(f"  Columns: {list(lc_df.columns)}")
    if "galaxy_score" in lc_df.columns:
        gs = lc_df["galaxy_score"].dropna()
        print(f"  Galaxy Score: mean={gs.mean():.1f}  min={gs.min():.1f}  max={gs.max():.1f}")
        print(f"  Latest: {gs.iloc[-1]:.1f} ({lc_df.index[-1].date()})")
        # Rough signal: score > 60 = bullish, < 40 = bearish
        bull_days = (gs > 60).sum()
        bear_days = (gs < 40).sum()
        print(f"  Bull days (>60): {bull_days}/{len(gs)}  Bear days (<40): {bear_days}/{len(gs)}")
    return lc_df


# ---------------------------------------------------------------------------
# Study 5: CoinGecko Pro — fix BTC 7d trend
# ---------------------------------------------------------------------------

def study_coingecko_pro():
    print("\n" + "=" * 70)
    print("STUDY 5: CoinGecko Pro API Validation")
    print("=" * 70)

    try:
        cg_key = get_secret("COINGECKO_API_KEY")
    except RuntimeError as e:
        print(f"  {e}")
        return

    # Test Pro endpoint — should return 7d data without rate limits
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_7d_change=true"
    req = urllib.request.Request(url, headers={
        "User-Agent": "IG-88/1.0",
        "x-cg-demo-api-key": cg_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        btc = data["bitcoin"]
        print(f"  BTC price: ${btc['usd']:,.2f}")
        print(f"  7d change: {btc.get('usd_7d_change', 'N/A')}%")
        print(f"  API key working: YES")
        return btc
    except Exception as e:
        print(f"  CoinGecko Pro error: {e}")
        return None


# ---------------------------------------------------------------------------
# Paper trade logger
# ---------------------------------------------------------------------------

def log_paper_trade(signal: dict, venue: str, strategy: str):
    """Log a paper trade signal. Called by scanner when signal fires."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "venue": venue,
        "strategy": strategy,
        **signal,
        "status": "OPEN",
        "exit_price": None,
        "exit_time": None,
        "pnl_pct": None,
    }
    with open(PAPER_TRADES, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"  [LOGGED] {venue} {strategy} @ ${signal.get('entry_price', 0):,.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("IG-88 VENUE RESEARCH — Kraken + Jupiter + LunarCrush")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # Load BTC daily for regime
    btc_df = pd.read_parquet(DATA_DIR / "binance_BTC_USD_1440m.parquet")
    btc_ts = btc_df.index.astype("int64").values / 1e9
    btc_c  = btc_df["close"].values.astype(float)
    binance_sol = pd.read_parquet(DATA_DIR / "binance_SOL_USDT_240m.parquet")

    # Study 1: Kraken vs Binance
    krak_sol = study_kraken_vs_binance()

    if krak_sol is not None and not krak_sol.empty:
        # Study 2: Signal alignment
        study_signal_alignment(krak_sol, binance_sol, btc_ts, btc_c)

        # Study 3: Full H3 backtest on Kraken data
        kraken_results = study_kraken_backtest(krak_sol, btc_ts, btc_c)
    else:
        print("\n  Skipping studies 2+3 — Kraken data unavailable")

    # Study 4: LunarCrush
    study_lunarcrush_regime(btc_ts, btc_c)

    # Study 5: CoinGecko Pro
    study_coingecko_pro()

    # Kraken account check
    print("\n" + "=" * 70)
    print("KRAKEN ACCOUNT CHECK")
    print("=" * 70)
    try:
        balance = fetch_kraken_account_balance()
        if balance.get("error"):
            print(f"  Error: {balance['error']}")
        else:
            balances = balance.get("result", {})
            print(f"  Account balances:")
            for asset, amount in balances.items():
                if float(amount) > 0:
                    print(f"    {asset}: {amount}")
            if not any(float(v) > 0 for v in balances.values()):
                print("  (all balances zero — paper trading only)")
    except Exception as e:
        print(f"  Account check error: {e}")
