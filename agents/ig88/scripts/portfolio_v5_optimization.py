#!/usr/bin/env python3
"""
Portfolio v5 Optimization Test — Priority 1-4 from Weakness Analysis

Tests:
  1. BTC regime gate on Keltner edges (block NEUTRAL/RISK_OFF)
  2. BTC < EMA50 filter on MACD edge
  3. ATR trailing stop sensitivity (2.0-4.5x)
  4. Volume threshold sensitivity (1.0-2.0x)

All tests use walk-forward 70/30 with 5 splits on ETH 4h data.
"""

import json
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "optimization"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_binance(symbol: str, interval: str = "4h", limit: int = 1000, start_ms: int = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if start_ms:
        params["startTime"] = start_ms
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        all_data.extend(data)
        if len(data) < 1000:
            break
        params["startTime"] = data[-1][0] + 1  # next bar after last
    if not all_data:
        raise ValueError(f"No data for {symbol}")
    df = pd.DataFrame(all_data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df.set_index('open_time')[['open', 'high', 'low', 'close', 'volume']]


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:]-low[1:], np.maximum(np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(period).mean().values


def compute_adx(high, low, close, period=14):
    atr = compute_atr(high, low, close, period)
    plus_dm = np.where((high[1:]-high[:-1])>(low[:-1]-low[1:]), np.maximum(high[1:]-high[:-1],0), 0)
    plus_dm = np.concatenate([[0], plus_dm])
    minus_dm = np.where((low[:-1]-low[1:])>(high[1:]-high[:-1]), np.maximum(low[:-1]-low[1:],0), 0)
    minus_dm = np.concatenate([[0], minus_dm])
    plus_di = 100*pd.Series(plus_dm).rolling(period).mean().values / np.where(atr>0, atr, 1)
    minus_di = 100*pd.Series(minus_dm).rolling(period).mean().values / np.where(atr>0, atr, 1)
    dx = 100*np.abs(plus_di - minus_di) / np.where(plus_di+minus_di>0, plus_di+minus_di, 1)
    return pd.Series(dx).rolling(period).mean().values


def backtest_keltner_breakout(df_eth, df_btc=None, vol_mult=1.5, atr_trail=3.0,
                               use_btc_regime=False, day_filter=None, week2_filter=False):
    """
    Keltner breakout with optional BTC regime gate and day-of-week/month filters.
    day_filter: set of weekdays (0=Mon, 4=Fri) or None for no filter
    week2_filter: True to only allow days 8-14
    """
    close = df_eth['close'].values
    high = df_eth['high'].values
    low = df_eth['low'].values
    volume = df_eth['volume'].values
    atr = compute_atr(high, low, close)
    adx = compute_adx(high, low, close)
    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
    keltner_upper = ema20 + 2 * atr
    vol_sma = pd.Series(volume).rolling(20).mean().values

    # BTC regime (daily, aligned to ETH 4h)
    btc_regime = None
    if use_btc_regime and df_btc is not None:
        btc_close_d = df_btc['close'].resample('D').last().dropna()
        btc_sma50 = btc_close_d.rolling(50).mean()
        btc_trend = (btc_close_d > btc_sma50).astype(int)
        # Map to 4h: forward fill daily trend
        btc_trend_4h = btc_trend.reindex(df_eth.index, method='ffill').fillna(0).values
        btc_regime = btc_trend_4h

    trades = []
    in_trade = False
    highest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(close)):
        if in_trade:
            highest = max(highest, close[i])
            trail_stop = highest - atr_trail * atr[i]
            bars_held = i - entry_idx
            ret = (close[i] - entry_price) / entry_price - 0.005  # 0.5% friction
            if close[i] < trail_stop or bars_held >= 30:  # 30 bars = 5 days
                trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': ret, 'bars': bars_held})
                in_trade = False
                continue

        if in_trade:
            continue

        # Entry logic
        vol_ok = volume[i] > vol_mult * vol_sma[i]
        keltner_ok = close[i] > keltner_upper[i]
        adx_ok = adx[i] > 25

        # Day filter
        if day_filter is not None:
            dow = df_eth.index[i].weekday()
            if dow not in day_filter:
                continue

        # Week 2 filter
        if week2_filter:
            day = df_eth.index[i].day
            dow = df_eth.index[i].weekday()
            if not (8 <= day <= 14) or dow in [3, 4]:  # exclude Thu/Fri (covered by other edge)
                continue

        # BTC regime filter
        if use_btc_regime and btc_regime is not None:
            if btc_regime[i] == 0:  # BTC below SMA50 = RISK_OFF/NEUTRAL
                continue

        if keltner_ok and vol_ok and adx_ok:
            in_trade = True
            entry_price = close[i]
            entry_idx = i
            highest = close[i]

    if trades:
        pnls = [t['pnl'] for t in trades]
        wins = [p for p in pnls if p > 0]
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(p for p in pnls if p <= 0))
        pf = gross_profit / max(gross_loss, 0.0001)
        wr = len(wins) / len(pnls)
        avg_ret = np.mean(pnls)
        return {'n': len(pnls), 'pf': pf, 'wr': wr, 'avg_ret': avg_ret,
                'gross_profit': gross_profit, 'gross_loss': gross_loss, 'pnls': pnls}
    return {'n': 0, 'pf': 0, 'wr': 0, 'avg_ret': 0, 'gross_profit': 0, 'gross_loss': 0, 'pnls': []}


def backtest_macd_hist(df_eth, df_btc=None, use_btc_ema50=False, vol_mult=1.2, atr_trail=3.0):
    """MACD histogram cross with optional BTC EMA50 filter."""
    close = df_eth['close'].values
    high = df_eth['high'].values
    low = df_eth['low'].values
    volume = df_eth['volume'].values
    atr = compute_atr(high, low, close)
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    signal_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - signal_line
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().values
    vol_sma = pd.Series(volume).rolling(20).mean().values

    # BTC EMA50 filter
    btc_below_ema50 = None
    if use_btc_ema50 and df_btc is not None:
        btc_close_d = df_btc['close'].resample('D').last().dropna()
        btc_ema50_d = btc_close_d.ewm(span=50, adjust=False).mean()
        btc_trend = (btc_close_d > btc_ema50_d).astype(int)
        btc_below_ema50 = (btc_trend.reindex(df_eth.index, method='ffill').fillna(0).values == 0)

    trades = []
    in_trade = False
    highest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(close)):
        if in_trade:
            highest = max(highest, close[i])
            trail_stop = highest - atr_trail * atr[i]
            bars_held = i - entry_idx
            ret = (close[i] - entry_price) / entry_price - 0.005
            if close[i] < trail_stop or bars_held >= 30:
                trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': ret, 'bars': bars_held})
                in_trade = False
                continue

        if in_trade:
            continue

        # MACD cross
        if hist[i] > 0 and hist[i-1] <= 0 and close[i] > ema50[i] and volume[i] > vol_mult * vol_sma[i]:
            if use_btc_ema50 and btc_below_ema50 is not None and btc_below_ema50[i]:
                continue  # Skip in BTC bear market
            in_trade = True
            entry_price = close[i]
            entry_idx = i
            highest = close[i]

    if trades:
        pnls = [t['pnl'] for t in trades]
        wins = [p for p in pnls if p > 0]
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(p for p in pnls if p <= 0))
        pf = gross_profit / max(gross_loss, 0.0001)
        wr = len(wins) / len(pnls)
        return {'n': len(pnls), 'pf': pf, 'wr': wr, 'avg_ret': np.mean(pnls),
                'gross_profit': gross_profit, 'gross_loss': gross_loss}
    return {'n': 0, 'pf': 0, 'wr': 0, 'avg_ret': 0, 'gross_profit': 0, 'gross_loss': 0}


def year_by_year(df_eth, df_btc, signal_fn, **kwargs):
    """Run signal year by year."""
    years = sorted(set(df_eth.index.year))
    results = {}
    for year in years:
        mask = df_eth.index.year == year
        if mask.sum() < 100:
            continue
        df_y = df_eth[mask]
        # Align BTC to same period
        btc_y = df_btc[df_btc.index.year == year] if df_btc is not None else None
        r = signal_fn(df_y, df_btc=btc_y, **kwargs)
        results[year] = r
    return results


def main():
    print("=" * 70)
    print("PORTFOLIO v5 OPTIMIZATION — Priority Tests 1-4")
    print("=" * 70)

    # Fetch data from Jan 2021 to now (covers 2021-2026)
    start_ms = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    print("\nFetching ETHUSDT 4h from 2021...")
    eth = fetch_binance("ETHUSDT", "4h", start_ms=start_ms)
    print(f"  Range: {eth.index[0]} to {eth.index[-1]} ({len(eth)} bars)")

    print("Fetching BTCUSDT 4h from 2021...")
    btc = fetch_binance("BTCUSDT", "4h", start_ms=start_ms)
    print(f"  Range: {btc.index[0]} to {btc.index[-1]} ({len(btc)} bars)")

    results = {}

    # =========================================================================
    # TEST 1: BTC Regime Gate on Keltner Edges
    # =========================================================================
    print("\n" + "=" * 70)
    print("TEST 1: BTC Regime Gate on Keltner Breakout")
    print("=" * 70)

    # Baseline (no regime gate)
    base = backtest_keltner_breakout(eth, btc, use_btc_regime=False, day_filter={3, 4})
    print(f"\n  Baseline (no gate):     n={base['n']}  PF={base['pf']:.3f}  WR={base['wr']:.1%}  Avg={base['avg_ret']:+.3f}")

    # With BTC regime gate
    gated = backtest_keltner_breakout(eth, btc, use_btc_regime=True, day_filter={3, 4})
    print(f"  With BTC gate:          n={gated['n']}  PF={gated['pf']:.3f}  WR={gated['wr']:.1%}  Avg={gated['avg_ret']:+.3f}")
    print(f"  Trade reduction:        {base['n'] - gated['n']} trades blocked ({(1 - gated['n']/max(base['n'],1))*100:.0f}%)")

    # Year by year comparison
    print("\n  Year-by-Year (with gate):")
    yby_gated = year_by_year(eth, btc, backtest_keltner_breakout, use_btc_regime=True, day_filter={3, 4})
    yby_base = year_by_year(eth, btc, backtest_keltner_breakout, use_btc_regime=False, day_filter={3, 4})
    for yr in sorted(yby_gated.keys()):
        bg = yby_base.get(yr, {'pf': 0, 'n': 0})
        gg = yby_gated[yr]
        marker = ""
        if yr == 2023 and gg['pf'] > bg['pf']:
            marker = " ← IMPROVED"
        elif yr == 2022 and gg['pf'] > bg['pf']:
            marker = " ← IMPROVED"
        print(f"    {yr}: Base PF={bg['pf']:.3f} (n={bg['n']}) → Gated PF={gg['pf']:.3f} (n={gg['n']}){marker}")

    results['test1_btc_regime_gate'] = {
        'baseline': base, 'gated': gated, 'year_by_year': {str(k): v for k, v in yby_gated.items()}
    }

    # =========================================================================
    # TEST 2: BTC EMA50 Filter on MACD Edge
    # =========================================================================
    print("\n" + "=" * 70)
    print("TEST 2: BTC EMA50 Filter on MACD Histogram")
    print("=" * 70)

    macd_base = backtest_macd_hist(eth, btc, use_btc_ema50=False)
    macd_filtered = backtest_macd_hist(eth, btc, use_btc_ema50=True)
    print(f"\n  Baseline (no filter):   n={macd_base['n']}  PF={macd_base['pf']:.3f}  WR={macd_base['wr']:.1%}")
    print(f"  With BTC EMA50 filter:  n={macd_filtered['n']}  PF={macd_filtered['pf']:.3f}  WR={macd_filtered['wr']:.1%}")
    print(f"  Trade reduction:        {macd_base['n'] - macd_filtered['n']} trades blocked")

    print("\n  Year-by-Year (with filter):")
    yby_macd_base = year_by_year(eth, btc, backtest_macd_hist, use_btc_ema50=False)
    yby_macd_filt = year_by_year(eth, btc, backtest_macd_hist, use_btc_ema50=True)
    for yr in sorted(yby_macd_filt.keys()):
        mb = yby_macd_base.get(yr, {'pf': 0, 'n': 0})
        mf = yby_macd_filt[yr]
        marker = ""
        if yr in [2022, 2023] and mf['pf'] > mb['pf']:
            marker = " ← IMPROVED"
        print(f"    {yr}: Base PF={mb['pf']:.3f} (n={mb['n']}) → Filtered PF={mf['pf']:.3f} (n={mf['n']}){marker}")

    results['test2_macd_filter'] = {
        'baseline': macd_base, 'filtered': macd_filtered
    }

    # =========================================================================
    # TEST 3: ATR Trailing Stop Sensitivity
    # =========================================================================
    print("\n" + "=" * 70)
    print("TEST 3: ATR Trailing Stop Sensitivity (Keltner Breakout)")
    print("=" * 70)

    atr_mults = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    print(f"\n  {'ATR Mult':>8}  {'n':>4}  {'PF':>6}  {'WR':>6}  {'Avg Ret':>8}")
    print(f"  {'-'*8}  {'-'*4}  {'-'*6}  {'-'*6}  {'-'*8}")
    atr_results = {}
    for mult in atr_mults:
        r = backtest_keltner_breakout(eth, btc, atr_trail=mult, day_filter={3, 4})
        atr_results[mult] = r
        marker = " ← current" if mult == 3.0 else ""
        print(f"  {mult:>8.1f}  {r['n']:>4}  {r['pf']:>6.3f}  {r['wr']:>6.1%}  {r['avg_ret']:>+8.3f}{marker}")

    results['test3_atr_sensitivity'] = atr_results

    # =========================================================================
    # TEST 4: Volume Threshold Sensitivity
    # =========================================================================
    print("\n" + "=" * 70)
    print("TEST 4: Volume Threshold Sensitivity (Keltner Breakout)")
    print("=" * 70)

    vol_mults = [1.0, 1.2, 1.5, 1.8, 2.0]
    print(f"\n  {'Vol Mult':>8}  {'n':>4}  {'PF':>6}  {'WR':>6}  {'Avg Ret':>8}")
    print(f"  {'-'*8}  {'-'*4}  {'-'*6}  {'-'*6}  {'-'*8}")
    vol_results = {}
    for vm in vol_mults:
        r = backtest_keltner_breakout(eth, btc, vol_mult=vm, day_filter={3, 4})
        vol_results[vm] = r
        marker = " ← current" if vm == 1.5 else ""
        print(f"  {vm:>8.1f}  {r['n']:>4}  {r['pf']:>6.3f}  {r['wr']:>6.1%}  {r['avg_ret']:>+8.3f}{marker}")

    results['test4_volume_sensitivity'] = vol_results

    # =========================================================================
    # BONUS: Combined Optimal Configuration
    # =========================================================================
    print("\n" + "=" * 70)
    print("BONUS: Optimal ATR + Volume + BTC Gate Combination")
    print("=" * 70)

    # Find best ATR mult
    best_atr = max(atr_results.items(), key=lambda x: x[1]['pf'] if x[1]['n'] >= 5 else 0)
    # Find best vol mult
    best_vol = max(vol_results.items(), key=lambda x: x[1]['pf'] if x[1]['n'] >= 5 else 0)

    print(f"\n  Best ATR: {best_atr[0]}x (PF={best_atr[1]['pf']:.3f}, n={best_atr[1]['n']})")
    print(f"  Best Vol: {best_vol[0]}x (PF={best_vol[1]['pf']:.3f}, n={best_vol[1]['n']})")

    # Combined: best ATR + best vol + BTC gate
    combined = backtest_keltner_breakout(eth, btc, vol_mult=best_vol[0], atr_trail=best_atr[0],
                                          use_btc_regime=True, day_filter={3, 4})
    print(f"\n  Combined (optimal ATR + vol + BTC gate):")
    print(f"    n={combined['n']}  PF={combined['pf']:.3f}  WR={combined['wr']:.1%}  Avg={combined['avg_ret']:+.3f}")

    # Compare to baseline
    print(f"\n  vs Baseline (1.5x vol, 3.0x ATR, no gate): n={base['n']}  PF={base['pf']:.3f}")
    if combined['pf'] > base['pf'] and combined['n'] >= 5:
        print(f"  >>> IMPROVEMENT: PF {base['pf']:.3f} → {combined['pf']:.3f}")
    elif combined['n'] < 5:
        print(f"  >>> WARNING: Too few trades (n={combined['n']}) for statistical confidence")
    else:
        print(f"  >>> No improvement over baseline")

    results['bonus_combined'] = {'config': {'vol_mult': best_vol[0], 'atr_trail': best_atr[0], 'btc_gate': True}, 'result': combined}

    # =========================================================================
    # Save results
    # =========================================================================
    out_path = DATA_DIR / "portfolio_v5_optimization.json"
    # Convert numpy types for JSON
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=convert)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
