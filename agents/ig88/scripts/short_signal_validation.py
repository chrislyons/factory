#!/usr/bin/env python3
"""
Comprehensive Short Signal Validation — Top 5 Daily Short Signals

Tests:
1. Regime-conditional (always vs RISK_OFF only)
2. Walk-forward validation (3 splits)
3. Correlation with long edges
4. Drawdown analysis
5. Optimal trail multiplier search

Goal: Find 1-2 short edges that work in RISK_OFF, don't interfere with RISK_ON longs.
"""

import numpy as np, pandas as pd, requests, json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "short_validation"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_binance(symbol, interval="1d", start_ms=None):
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if start_ms: params["startTime"] = start_ms
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data: break
        all_data.extend(data)
        if len(data) < 1000: break
        params["startTime"] = data[-1][0] + 1
    df = pd.DataFrame(all_data, columns=['ts','o','h','l','c','v','ct','q','t','tb','tq','ig'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.set_index('ts')[['o','h','l','c','v']].rename(
        columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})


def compute_atr(h, l, c, p=14):
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(p).mean().values

def compute_adx(h, l, c, p=14):
    atr = compute_atr(h, l, c, p)
    pdm = np.where((h[1:]-h[:-1])>(l[:-1]-l[1:]), np.maximum(h[1:]-h[:-1],0),0)
    pdm = np.concatenate([[0], pdm])
    mdm = np.where((l[:-1]-l[1:])>(h[1:]-h[:-1]), np.maximum(l[:-1]-l[1:],0),0)
    mdm = np.concatenate([[0], mdm])
    pdi = 100*pd.Series(pdm).rolling(p).mean().values/np.where(atr>0,atr,1)
    mdi = 100*pd.Series(mdm).rolling(p).mean().values/np.where(atr>0,atr,1)
    dx = 100*np.abs(pdi-mdi)/np.where(pdi+mdi>0,pdi+mdi,1)
    return pd.Series(dx).rolling(p).mean().values

def compute_rsi(c, p=14):
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(p).mean()
    loss = (-delta.clip(upper=0)).rolling(p).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).values


# ============================================================================
# REGIME DETECTION
# ============================================================================

def get_btc_regime(btc_df):
    """RISK_OFF = BTC daily close < SMA50. Returns boolean array."""
    btc_close = btc_df['close'].values
    sma50 = pd.Series(btc_close).rolling(50).mean().values
    # Align to main dataframe dates
    regime_map = {}
    for i, dt in enumerate(btc_df.index):
        if i >= 50:
            regime_map[dt] = btc_close[i] < sma50[i]
    return regime_map


# ============================================================================
# SHORT SIGNAL DEFINITIONS
# ============================================================================

def sig_break_ema50(c, h, l, v, atr, adx, rsi, vsma, i):
    """Close drops below EMA(50) — major trend break"""
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

def sig_break_sma20(c, h, l, v, atr, adx, rsi, vsma, i):
    """Close drops below SMA(20) with ADX trend confirmation"""
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return c[i] < sma20[i] and c[i-1] >= sma20[i-1] and adx[i] > 20 and v[i] > 1.2 * vsma[i]

def sig_macd_bearish_cross(c, h, l, v, atr, adx, rsi, vsma, i):
    """MACD histogram turns negative (was positive)"""
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = e12 - e26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig
    return hist[i] < 0 and hist[i-1] >= 0 and v[i] > 1.0 * vsma[i]


# ============================================================================
# BACKTESTER WITH REGIME FILTER AND DRAWDOWN TRACKING
# ============================================================================

def backtest_short_full(df, signal_fn, trail_mult=3.0, friction=0.005, max_hold=30,
                         regime_filter=None, regime_map=None):
    """
    Full short backtester with optional regime filtering and drawdown tracking.
    regime_filter: None (always), 'RISK_OFF' (only when BTC < SMA50), 'RISK_ON' (only when BTC >= SMA50)
    """
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c); rsi=compute_rsi(c)
    vsma=pd.Series(v).rolling(20).mean().values

    trades = []
    trade_details = []
    in_trade = False
    lowest = 0.0
    entry_idx = 0
    entry_price = 0.0
    equity_curve = [1.0]

    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret)
                trade_details.append({
                    'entry_idx': entry_idx, 'exit_idx': i,
                    'entry_date': str(df.index[entry_idx].date()),
                    'exit_date': str(df.index[i].date()),
                    'pnl': ret, 'bars': bars_held
                })
                equity_curve.append(equity_curve[-1] * (1 + ret))
                in_trade = False
                continue
        if in_trade:
            continue

        # Regime filter
        if regime_filter and regime_map:
            dt = df.index[i]
            is_risk_off = regime_map.get(dt, False)
            if regime_filter == 'RISK_OFF' and not is_risk_off:
                continue
            elif regime_filter == 'RISK_ON' and is_risk_off:
                continue

        if signal_fn(c, h, l, v, atr, adx, rsi, vsma, i):
            in_trade = True
            entry_price = c[i]
            entry_idx = i
            lowest = c[i]

    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'total': 0, 'trades': [],
                'trade_details': [], 'equity_curve': [], 'max_dd': 0, 'regime_days': 0}

    pnls = np.array(trades)
    wins = pnls[pnls>0]
    gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)

    # Drawdown analysis
    ec = np.array(equity_curve)
    peak = np.maximum.accumulate(ec)
    dd = (peak - ec) / peak
    max_dd = dd.max() if len(dd) > 0 else 0

    return {
        'n': len(pnls), 'pf': pf, 'wr': len(wins)/len(pnls),
        'avg': pnls.mean(), 'total': pnls.sum(),
        'trades': trades, 'trade_details': trade_details,
        'equity_curve': equity_curve, 'max_dd': max_dd,
    }


def compute_max_drawdown(trades):
    """Compute max drawdown from trade list."""
    if not trades:
        return 0
    ec = [1.0]
    for t in trades:
        ec.append(ec[-1] * (1 + t))
    ec = np.array(ec)
    peak = np.maximum.accumulate(ec)
    dd = (peak - ec) / peak
    return dd.max()


def compute_consecutive_losses(trades):
    """Max consecutive losses."""
    max_streak = 0
    streak = 0
    for t in trades:
        if t <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


# ============================================================================
# LONG SIGNAL (for correlation check)
# ============================================================================

def sig_long_keltner_thufri(c, h, l, v, atr, adx, rsi, vsma, i, dow):
    """ETH Thu/Fri Keltner breakout — our best long edge"""
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_upper = ema20 + 2 * atr[:i+1]
    if dow not in [3, 4]: return False
    return c[i] > kelt_upper[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_long_macd_hist(c, h, l, v, atr, adx, rsi, vsma, i):
    """MACD histogram cross up — long edge"""
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = e12 - e26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig
    e50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] > 0 and hist[i-1] <= 0 and c[i] > e50[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25


# ============================================================================
# MAIN VALIDATION
# ============================================================================

def main():
    print("=" * 80)
    print("COMPREHENSIVE SHORT SIGNAL VALIDATION")
    print(f"Timestamp: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    # Fetch daily data for all assets + BTC for regime
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    assets = {
        'SOLUSDT': 'SOL',
        'BTCUSDT': 'BTC',
        'ETHUSDT': 'ETH',
        'AVAXUSDT': 'AVAX',
    }

    print("\nFetching daily data from 2020...")
    data = {}
    for sym, label in assets.items():
        try:
            df = fetch_binance(sym, "1d", start_ms=start_ms)
            data[label] = df
            print(f"  {label}: {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
        except Exception as e:
            print(f"  {label}: ERROR - {e}")

    btc_df = data.get('BTC')
    if btc_df is None:
        print("ERROR: BTC data required for regime detection")
        return

    regime_map = get_btc_regime(btc_df)

    # Define top 5 signals with their specific parameters
    top_signals = [
        ('SOL', 'Break EMA50', sig_break_ema50, 4.0),
        ('BTC', 'Break EMA50', sig_break_ema50, 3.0),
        ('ETH', 'Break SMA20', sig_break_sma20, 2.0),
        ('SOL', 'Break SMA20', sig_break_sma20, 4.0),
        ('AVAX', 'MACD Bearish Cross', sig_macd_bearish_cross, 2.0),
    ]

    # =========================================================================
    # SECTION 1: REGIME-CONDITIONAL TEST
    # =========================================================================
    print("\n" + "=" * 80)
    print("1. REGIME-CONDITIONAL TEST")
    print("=" * 80)
    print("Testing each signal: ALWAYS vs RISK_OFF only (BTC < SMA50)")
    print()

    regime_results = {}

    for asset, sig_name, sig_fn, trail in top_signals:
        df = data.get(asset)
        if df is None:
            continue

        # Test always
        r_always = backtest_short_full(df, sig_fn, trail_mult=trail, regime_filter=None)
        # Test RISK_OFF only
        r_riskoff = backtest_short_full(df, sig_fn, trail_mult=trail,
                                         regime_filter='RISK_OFF', regime_map=regime_map)
        # Test RISK_ON only
        r_riskon = backtest_short_full(df, sig_fn, trail_mult=trail,
                                        regime_filter='RISK_ON', regime_map=regime_map)

        key = f"{asset}_{sig_name}_trail{trail}"
        regime_results[key] = {
            'always': r_always, 'risk_off': r_riskoff, 'risk_on': r_riskon
        }

        print(f"--- {asset} {sig_name} (trail {trail}x) ---")
        print(f"  {'Mode':<12} {'n':>4} {'PF':>7} {'WR':>7} {'Avg':>8} {'Total':>8} {'MaxDD':>8}")
        print(f"  {'-'*12} {'-'*4} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

        for mode, r in [('ALWAYS', r_always), ('RISK_OFF', r_riskoff), ('RISK_ON', r_riskon)]:
            if r['n'] > 0:
                print(f"  {mode:<12} {r['n']:>4} {r['pf']:>7.3f} {r['wr']:>6.1%} {r['avg']:>+7.3f} {r['total']:>+7.1%} {r['max_dd']:>7.1%}")
            else:
                print(f"  {mode:<12} {'n=0':>4}")

        # Highlight regime improvement
        if r_always['n'] > 0 and r_riskoff['n'] > 0:
            pf_change = r_riskoff['pf'] - r_always['pf']
            wr_change = r_riskoff['wr'] - r_always['wr']
            if pf_change > 0:
                print(f"  >>> RISK_OFF IMPROVES PF by {pf_change:+.3f}")
            else:
                print(f"  >>> RISK_OFF degrades PF by {pf_change:+.3f}")
        print()

    # =========================================================================
    # SECTION 2: YEAR-BY-YEAR ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("2. YEAR-BY-YEAR ANALYSIS (RISK_OFF regime filtered)")
    print("=" * 80)

    for asset, sig_name, sig_fn, trail in top_signals:
        df = data.get(asset)
        if df is None: continue

        print(f"\n--- {asset} {sig_name} (trail {trail}x, RISK_OFF only) ---")
        print(f"  {'Year':>6} {'n':>4} {'PF':>7} {'WR':>7} {'Total':>8} {'MaxDD':>8} {'ConsecL':>8}")
        print(f"  {'-'*6} {'-'*4} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

        year_pf = {}
        for year in range(2021, 2026):
            yr_start = f'{year}-01-01'
            yr_end = f'{year}-12-31'
            yr_df = df.loc[yr_start:yr_end]
            if len(yr_df) < 50: break
            r = backtest_short_full(yr_df, sig_fn, trail_mult=trail,
                                     regime_filter='RISK_OFF', regime_map=regime_map)
            if r['n'] > 0:
                consec_l = compute_consecutive_losses(r['trades'])
                marker = " LOSS" if r['pf'] < 1.0 else ""
                print(f"  {year:>6} {r['n']:>4} {r['pf']:>7.3f} {r['wr']:>6.1%} {r['total']:>+7.1%} {r['max_dd']:>7.1%} {consec_l:>8}{marker}")
                year_pf[year] = r['pf']
            else:
                print(f"  {year:>6} {'n=0':>4}")

        # Summary
        if year_pf:
            profitable_years = sum(1 for v in year_pf.values() if v > 1.0)
            print(f"  Profitable years: {profitable_years}/{len(year_pf)}")

    # =========================================================================
    # SECTION 3: WALK-FORWARD VALIDATION
    # =========================================================================
    print("\n" + "=" * 80)
    print("3. WALK-FORWARD VALIDATION")
    print("=" * 80)
    print("Splits: train 2021-2022/test 2023, train 2021-2023/test 2024, train 2021-2024/test 2025")
    print()

    wf_splits = [
        ('2021-2022', '2023-01-01', '2023-12-31'),
        ('2021-2023', '2024-01-01', '2024-12-31'),
        ('2021-2024', '2025-01-01', '2025-12-31'),
    ]

    for asset, sig_name, sig_fn, trail in top_signals:
        df = data.get(asset)
        if df is None: continue

        print(f"--- {asset} {sig_name} (trail {trail}x, RISK_OFF) ---")
        print(f"  {'Train':<12} {'Test Period':<24} {'n':>4} {'PF':>7} {'WR':>7} {'Total':>8}")
        print(f"  {'-'*12} {'-'*24} {'-'*4} {'-'*7} {'-'*7} {'-'*8}")

        oos_pfs = []
        for train_label, test_start, test_end in wf_splits:
            try:
                test_df = df.loc[test_start:test_end]
                if len(test_df) < 50:
                    print(f"  {train_label:<12} {test_start[:4]:<24} {'insufficient data'}")
                    continue
                r = backtest_short_full(test_df, sig_fn, trail_mult=trail,
                                        regime_filter='RISK_OFF', regime_map=regime_map)
                if r['n'] > 0:
                    oos_pfs.append(r['pf'])
                    marker = " LOSS" if r['pf'] < 1.0 else ""
                    print(f"  {train_label:<12} {test_start[:10]+' to '+test_end[:10]:<24} {r['n']:>4} {r['pf']:>7.3f} {r['wr']:>6.1%} {r['total']:>+7.1%}{marker}")
                else:
                    print(f"  {train_label:<12} {test_start[:10]+' to '+test_end[:10]:<24} {'n=0':>4}")
            except Exception as e:
                print(f"  {train_label:<12} {test_start[:4]:<24} ERROR: {e}")

        if oos_pfs:
            print(f"  Median OOS PF: {np.median(oos_pfs):.3f}  |  Min OOS PF: {min(oos_pfs):.3f}  |  PF>1: {sum(1 for p in oos_pfs if p > 1)}/{len(oos_pfs)}")
        print()

    # =========================================================================
    # SECTION 4: CORRELATION WITH LONGS
    # =========================================================================
    print("\n" + "=" * 80)
    print("4. CORRELATION WITH LONG EDGES")
    print("=" * 80)
    print("Checking if short signals fire in same periods as long edges.")
    print("Ideally shorts fire in RISK_OFF (bear) and longs fire in RISK_ON (bull).")
    print()

    # Build long signal calendar for ETH (our primary long asset)
    eth_df = data.get('ETH')
    if eth_df is not None:
        c = eth_df['close'].values
        h = eth_df['high'].values
        l = eth_df['low'].values
        v = eth_df['volume'].values
        atr = compute_atr(h, l, c)
        adx = compute_adx(h, l, c)
        vsma = pd.Series(v).rolling(20).mean().values

        long_dates = set()
        for i in range(55, len(c)):
            dow = eth_df.index[i].weekday()
            if sig_long_keltner_thufri(c, h, l, v, atr, adx, None, vsma, i, dow):
                long_dates.add(eth_df.index[i].date())
            if sig_long_macd_hist(c, h, l, v, atr, adx, None, vsma, i):
                long_dates.add(eth_df.index[i].date())

        # For each short signal, check overlap with long dates
        for asset, sig_name, sig_fn, trail in top_signals:
            df = data.get(asset)
            if df is None: continue

            r = backtest_short_full(df, sig_fn, trail_mult=trail, regime_filter=None)
            short_dates = set()
            for td in r.get('trade_details', []):
                entry_idx = td['entry_idx']
                if entry_idx < len(df):
                    short_dates.add(df.index[entry_idx].date())

            if short_dates:
                overlap = short_dates & long_dates
                overlap_pct = len(overlap) / len(short_dates) * 100 if short_dates else 0

                # Check how many short dates are in RISK_OFF
                riskoff_dates = set()
                for d in short_dates:
                    # Find closest BTC date
                    for bd in regime_map:
                        if bd.date() == d:
                            if regime_map[bd]:
                                riskoff_dates.add(d)
                            break

                riskoff_pct = len(riskoff_dates) / len(short_dates) * 100 if short_dates else 0

                print(f"  {asset} {sig_name}: {len(short_dates)} short entries")
                print(f"    Overlap with long edges: {len(overlap)}/{len(short_dates)} ({overlap_pct:.1f}%)")
                print(f"    In RISK_OFF regime:     {len(riskoff_dates)}/{len(short_dates)} ({riskoff_pct:.1f}%)")
                if overlap_pct < 20 and riskoff_pct > 50:
                    print(f"    >>> GOOD HEDGE: Low overlap, mostly in bear markets")
                elif overlap_pct > 50:
                    print(f"    >>> WARNING: High overlap with longs — may interfere")
                print()

    # =========================================================================
    # SECTION 5: DETAILED DRAWDOWN ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("5. DRAWDOWN ANALYSIS")
    print("=" * 80)
    print("Short strategies can have violent losses (short squeeze).")
    print()

    for asset, sig_name, sig_fn, trail in top_signals:
        df = data.get(asset)
        if df is None: continue

        r = backtest_short_full(df, sig_fn, trail_mult=trail,
                                regime_filter='RISK_OFF', regime_map=regime_map)
        if r['n'] == 0:
            print(f"  {asset} {sig_name}: no trades")
            continue

        trades = r['trades']
        max_dd = compute_max_drawdown(trades)
        consec_l = compute_consecutive_losses(trades)
        worst_trade = min(trades)
        best_trade = max(trades)
        avg_loss = np.mean([t for t in trades if t < 0]) if any(t < 0 for t in trades) else 0
        avg_win = np.mean([t for t in trades if t > 0]) if any(t > 0 for t in trades) else 0

        print(f"  --- {asset} {sig_name} (trail {trail}x, RISK_OFF) ---")
        print(f"    Trades:           {r['n']}")
        print(f"    Max Drawdown:     {max_dd:.1%}")
        print(f"    Worst Trade:      {worst_trade:+.1%}")
        print(f"    Best Trade:       {best_trade:+.1%}")
        print(f"    Avg Win:          {avg_win:+.1%}")
        print(f"    Avg Loss:         {avg_loss:+.1%}")
        print(f"    Win/Loss Ratio:   {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "    Win/Loss Ratio:   N/A")
        print(f"    Max Consec Loss:  {consec_l}")
        print(f"    Profit Factor:    {r['pf']:.3f}")
        print()

    # =========================================================================
    # SECTION 6: OPTIMAL TRAIL MULTIPLIER SEARCH
    # =========================================================================
    print("\n" + "=" * 80)
    print("6. OPTIMAL TRAIL MULTIPLIER SEARCH (RISK_OFF regime)")
    print("=" * 80)
    print("Testing trail multipliers: [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]")
    print()

    trail_multipliers = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]

    for asset, sig_name, sig_fn, _ in top_signals:
        df = data.get(asset)
        if df is None: continue

        print(f"--- {asset} {sig_name} ---")
        print(f"  {'Trail':>6} {'n':>4} {'PF':>7} {'WR':>7} {'Avg':>8} {'Total':>8} {'MaxDD':>8}")
        print(f"  {'-'*6} {'-'*4} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

        best_pf = 0
        best_trail = 0
        for trail in trail_multipliers:
            r = backtest_short_full(df, sig_fn, trail_mult=trail,
                                    regime_filter='RISK_OFF', regime_map=regime_map)
            if r['n'] > 0:
                marker = " <-- BEST" if r['pf'] > best_pf and r['n'] >= 5 else ""
                print(f"  {trail:>5.1f}x {r['n']:>4} {r['pf']:>7.3f} {r['wr']:>6.1%} {r['avg']:>+7.3f} {r['total']:>+7.1%} {r['max_dd']:>7.1%}{marker}")
                if r['pf'] > best_pf and r['n'] >= 5:
                    best_pf = r['pf']
                    best_trail = trail
            else:
                print(f"  {trail:>5.1f}x {'n=0':>4}")

        if best_trail > 0:
            print(f"  >>> Optimal trail: {best_trail}x (PF={best_pf:.3f})")
        print()

    # =========================================================================
    # FINAL RECOMMENDATIONS
    # =========================================================================
    print("\n" + "=" * 80)
    print("FINAL RECOMMENDATIONS")
    print("=" * 80)
    print("""
    SUMMARY:
    --------
    The goal is to find 1-2 short edges that:
    1. Work in RISK_OFF regime (bear market)
    2. Don't fire in RISK_ON (don't interfere with longs)
    3. Add portfolio resilience without destroying returns

    Evaluation criteria:
    - RISK_OFF PF >> ALWAYS PF (regime filtering helps)
    - RISK_ON has few/no trades (non-interference)
    - Walk-forward OOS PF > 1.0 in all splits
    - Low correlation with long edge dates
    - Acceptable max drawdown (< 20%)
    """)


if __name__ == "__main__":
    main()
