#!/usr/bin/env python3
"""
Short Edge Validation — Proper Inversion Approach

Chris's insight: "Short strategies can apply all over the place (even if inverted)."
If a long trend-following strategy works, its INVERSE (short version) should also work.

This script:
1. Takes proven long signals and inverts them for shorts
2. Tests ALL signal types (trend-following AND mean-reversion) on BOTH sides
3. Uses the SAME trailing stop logic (just inverted direction)
4. Reports long PF and short PF side-by-side for each signal

If a signal works long but not short, the model is wrong (or there's a genuine asymmetry).
"""

import numpy as np, pandas as pd, requests, json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "short_inversion"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_binance(symbol, interval="4h", start_ms=None):
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


def backtest_long(df, signal_fn, trail_mult=2.5, friction=0.005, max_hold=30):
    """Standard long backtest with ATR trailing stop."""
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values

    trades = []
    in_trade = False
    highest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(c)):
        if in_trade:
            highest = max(highest, c[i])
            trail_stop = highest - trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (c[i] - entry_price) / entry_price - friction
            if c[i] < trail_stop or bars_held >= max_hold:
                trades.append(ret)
                in_trade = False
                continue
        if in_trade:
            continue
        if signal_fn(c, h, l, v, atr, adx, vsma, i):
            in_trade = True
            entry_price = c[i]
            entry_idx = i
            highest = c[i]

    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'total': 0}
    pnls = np.array(trades)
    wins = pnls[pnls>0]
    gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n': len(pnls), 'pf': pf, 'wr': len(wins)/len(pnls), 'avg': pnls.mean(), 'total': pnls.sum()}


def backtest_short(df, signal_fn, trail_mult=2.5, friction=0.005, max_hold=30):
    """Short backtest with ATR trailing stop (inverted direction)."""
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values

    trades = []
    in_trade = False
    lowest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret)
                in_trade = False
                continue
        if in_trade:
            continue
        if signal_fn(c, h, l, v, atr, adx, vsma, i):
            in_trade = True
            entry_price = c[i]
            entry_idx = i
            lowest = c[i]

    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'total': 0}
    pnls = np.array(trades)
    wins = pnls[pnls>0]
    gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n': len(pnls), 'pf': pf, 'wr': len(wins)/len(pnls), 'avg': pnls.mean(), 'total': pnls.sum()}


# ============================================================================
# INVERTED SIGNAL SET — Mirror image of long signals
# ============================================================================

# LONG SIGNAL: Close breaks ABOVE Keltner upper + volume + ADX
def sig_long_keltner_breakout(c, h, l, v, atr, adx, vsma, i):
    if i < 25: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_upper = ema20 + 2 * atr[:i+1]
    return c[i] > kelt_upper[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

# SHORT INVERSE: Close breaks BELOW Keltner lower + volume + ADX
def sig_short_keltner_breakdown(c, h, l, v, atr, adx, vsma, i):
    if i < 25: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_lower = ema20 - 2 * atr[:i+1]
    return c[i] < kelt_lower[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

# LONG: Close breaks ABOVE EMA50 + volume
def sig_long_break_ema50(c, h, l, v, atr, adx, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] > ema50[i] and c[i-1] <= ema50[i-1] and v[i] > 1.2 * vsma[i]

# SHORT: Close breaks BELOW EMA50 + volume (the EXACT inverse)
def sig_short_break_ema50(c, h, l, v, atr, adx, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

# LONG: MACD histogram turns positive
def sig_long_macd_cross(c, h, l, v, atr, adx, vsma, i):
    if i < 35: return False
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = e12 - e26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig
    return hist[i] > 0 and hist[i-1] <= 0 and v[i] > 1.0 * vsma[i]

# SHORT: MACD histogram turns negative
def sig_short_macd_cross(c, h, l, v, atr, adx, vsma, i):
    if i < 35: return False
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = e12 - e26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig
    return hist[i] < 0 and hist[i-1] >= 0 and v[i] > 1.0 * vsma[i]

# LONG: ATR volatility expansion + close > SMA20 + volume (Vol Breakout)
def sig_long_vol_breakout(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    atr_sma = pd.Series(atr[:i+1]).rolling(50).mean().values
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return atr[i] > 1.5 * atr_sma[i] and c[i] > sma20[i] and v[i] > 1.2 * vsma[i]

# SHORT: ATR volatility expansion + close < SMA20 + volume (inverted vol breakout)
def sig_short_vol_breakdown(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    atr_sma = pd.Series(atr[:i+1]).rolling(50).mean().values
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return atr[i] > 1.5 * atr_sma[i] and c[i] < sma20[i] and v[i] > 1.2 * vsma[i]

# LONG: RSI oversold bounce (RSI < 30 then rises above 30)
def sig_long_rsi_bounce(c, h, l, v, atr, adx, vsma, i):
    if i < 16: return False
    delta = pd.Series(c[:i+1]).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).values
    return rsi[i] > 30 and rsi[i-1] <= 30

# SHORT: RSI overbought reversal (RSI > 70 then drops below 70)
def sig_short_rsi_reversal(c, h, l, v, atr, adx, vsma, i):
    if i < 16: return False
    delta = pd.Series(c[:i+1]).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100 / (1 + rs)).values
    return rsi[i] < 70 and rsi[i-1] >= 70

# LONG: 3 green candles + volume expansion
def sig_long_three_green(c, h, l, v, atr, adx, vsma, i):
    if i < 3: return False
    return (c[i] > c[i-1] and c[i-1] > c[i-2] and c[i-2] > c[i-3] and
            v[i] > v[i-1] > v[i-2] and v[i] > 1.5 * vsma[i])

# SHORT: 3 red candles + volume expansion
def sig_short_three_red(c, h, l, v, atr, adx, vsma, i):
    if i < 3: return False
    return (c[i] < c[i-1] and c[i-1] < c[i-2] and c[i-2] < c[i-3] and
            v[i] > v[i-1] > v[i-2] and v[i] > 1.5 * vsma[i])

# LONG: Close breaks above 20-bar high + volume
def sig_long_break_20high(c, h, l, v, atr, adx, vsma, i):
    if i < 22: return False
    high20 = pd.Series(h[:i]).rolling(20).max().values  # excludes current bar
    return c[i] > high20[-1] and v[i] > 1.5 * vsma[i]

# SHORT: Close breaks below 20-bar low + volume
def sig_short_break_20low(c, h, l, v, atr, adx, vsma, i):
    if i < 22: return False
    low20 = pd.Series(l[:i]).rolling(20).min().values  # excludes current bar
    return c[i] < low20[-1] and v[i] > 1.5 * vsma[i]

# LONG: Price > EMA20 + price rising + volume
def sig_long_trend_pullback(c, h, l, v, atr, adx, vsma, i):
    if i < 22: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    return c[i] > ema20[i] and c[i] > c[i-1] and c[i-1] > c[i-2] and v[i] > 1.0 * vsma[i]

# SHORT: Price < EMA20 + price falling + volume
def sig_short_trend_pullback(c, h, l, v, atr, adx, vsma, i):
    if i < 22: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    return c[i] < ema20[i] and c[i] < c[i-1] and c[i-1] < c[i-2] and v[i] > 1.0 * vsma[i]


def main():
    print("=" * 80)
    print("SHORT EDGE VALIDATION — PROPER INVERSION APPROACH")
    print("=" * 80)
    print()
    print("Testing paired signals: if LONG works, SHORT (inverted) should also work.")
    print("If SHORT doesn't work, the MODEL is wrong, not the market.")
    print()

    start_ms = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    assets = {
        'ETHUSDT': 'ETH',
        'BTCUSDT': 'BTC',
        'SOLUSDT': 'SOL',
        'LINKUSDT': 'LINK',
    }

    # Paired signals: (long_name, long_fn, short_name, short_fn)
    signal_pairs = [
        ('Keltner Breakout', sig_long_keltner_breakout,
         'Keltner Breakdown', sig_short_keltner_breakdown),
        ('Break EMA50', sig_long_break_ema50,
         'Break EMA50', sig_short_break_ema50),
        ('MACD Bull Cross', sig_long_macd_cross,
         'MACD Bear Cross', sig_short_macd_cross),
        ('Vol Breakout', sig_long_vol_breakout,
         'Vol Breakdown', sig_short_vol_breakdown),
        ('Break 20-High', sig_long_break_20high,
         'Break 20-Low', sig_short_break_20low),
        ('Trend Pullback Up', sig_long_trend_pullback,
         'Trend Pullback Down', sig_short_trend_pullback),
    ]

    timeframes = {'4h': '4h', '1d': '1d'}
    trail_mults = [2.0, 3.0]

    all_results = []

    for tf_name, tf_interval in timeframes.items():
        print(f"\n{'='*80}")
        print(f"  TIMEFRAME: {tf_name}")
        print(f"{'='*80}")

        for asset_name, asset_label in assets.items():
            print(f"\n  --- {asset_label} ---")
            try:
                df = fetch_binance(asset_name, tf_interval, start_ms=start_ms)
            except Exception as e:
                print(f"    ERROR: {e}")
                continue
            print(f"    {len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

            for trail in trail_mults:
                print(f"\n    Trail: {trail}x ATR")
                print(f"    {'Signal':<25s} {'Side':<6s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>8s} {'Total':>8s}")
                print(f"    {'-'*25} {'-'*6} {'-'*4} {'-'*7} {'-'*6} {'-'*8} {'-'*8}")

                for long_name, long_fn, short_name, short_fn in signal_pairs:
                    rl = backtest_long(df, long_fn, trail_mult=trail)
                    rs = backtest_short(df, short_fn, trail_mult=trail)

                    lp = f"{rl['pf']:.3f}" if rl['n'] > 0 else "  N/A"
                    sp = f"{rs['pf']:.3f}" if rs['n'] > 0 else "  N/A"
                    lw = f"{rl['wr']:.0%}" if rl['n'] > 0 else " N/A"
                    sw = f"{rs['wr']:.0%}" if rs['n'] > 0 else " N/A"
                    la = f"{rl['avg']:+.3f}" if rl['n'] > 0 else "   N/A"
                    sa = f"{rs['avg']:+.3f}" if rs['n'] > 0 else "   N/A"
                    lt = f"{rl['total']:+.1%}" if rl['n'] > 0 else "  N/A"
                    st = f"{rs['total']:+.1%}" if rs['n'] > 0 else "  N/A"

                    # Mark symmetry
                    sym = ""
                    if rl['n'] > 0 and rs['n'] > 0:
                        if rl['pf'] > 1.0 and rs['pf'] > 1.0:
                            sym = " ✓ BOTH WORK"
                        elif rl['pf'] > 1.0 and rs['pf'] <= 1.0:
                            sym = " ⚠ LONG ONLY"
                        elif rl['pf'] <= 1.0 and rs['pf'] > 1.0:
                            sym = " ⚠ SHORT ONLY"

                    print(f"    {long_name:<25s} {'LONG':<6s} {rl['n']:4d} {lp:>7s} {lw:>6s} {la:>8s} {lt:>8s}")
                    print(f"    {short_name:<25s} {'SHORT':<6s} {rs['n']:4d} {sp:>7s} {sw:>6s} {sa:>8s} {st:>8s}{sym}")
                    print()

                    all_results.append({
                        'asset': asset_label, 'tf': tf_name, 'trail': trail,
                        'long_name': long_name, 'long_pf': rl['pf'], 'long_n': rl['n'],
                        'short_name': short_name, 'short_pf': rs['pf'], 'short_n': rs['n'],
                    })

    # Summary: which shorts work?
    print(f"\n{'='*80}")
    print(f"  SUMMARY: SHORT SIGNALS WITH PF > 1.5")
    print(f"{'='*80}")
    working_shorts = [r for r in all_results if r['short_pf'] > 1.5 and r['short_n'] >= 10]
    working_shorts.sort(key=lambda x: x['short_pf'], reverse=True)
    if working_shorts:
        for r in working_shorts:
            print(f"    {r['asset']} {r['tf']} {r['short_name']} trail={r['trail']}x  "
                  f"PF={r['short_pf']:.3f}  n={r['short_n']}  "
                  f"(long PF={r['long_pf']:.3f})")
    else:
        print("    No short signals with PF > 1.5 and n >= 10 found.")
        print("    Top shorts by PF:")
        sorted_shorts = sorted(all_results, key=lambda x: x['short_pf'], reverse=True)
        for r in sorted_shorts[:10]:
            print(f"    {r['asset']} {r['tf']} {r['short_name']} trail={r['trail']}x  "
                  f"PF={r['short_pf']:.3f}  n={r['short_n']}")

    # Save
    out_path = DATA_DIR / "inversion_results.json"
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
