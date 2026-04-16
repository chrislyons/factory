#!/usr/bin/env python3
"""
Portfolio v6 — Correct Approach

Test each edge on its PROPER timeframe with PROPER exit logic.
Then compute combined portfolio returns and correlation.

Long edges: 4h data (Kraken spot)
Short edges: daily data (Jupiter Perps)
Regime: BTC daily SMA50
"""

import numpy as np, pandas as pd, requests, json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "portfolio_v6"
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
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values
    trades = []; in_trade = False; highest = 0.0; entry_idx = 0; entry_price = 0.0
    equity_curve = np.ones(len(c))

    for i in range(55, len(c)):
        if in_trade:
            highest = max(highest, c[i])
            trail_stop = highest - trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (c[i] - entry_price) / entry_price - friction
            if c[i] < trail_stop or bars_held >= max_hold:
                trades.append(ret); in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, adx, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; highest = c[i]

    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[]}
    pnls = np.array(trades); wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
            'total':pnls.sum(),'trades':trades}


def backtest_short(df, signal_fn, trail_mult=2.0, friction=0.001, max_hold=30):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values
    trades = []; in_trade = False; lowest = 0.0; entry_idx = 0; entry_price = 0.0

    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret); in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; lowest = c[i]

    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[]}
    pnls = np.array(trades); wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
            'total':pnls.sum(),'trades':trades}


# ============================================================================
# Signal functions
# ============================================================================

def sig_eth_keltner(c, h, l, v, atr, adx, vsma, i):
    if i < 25: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_upper = ema20 + 2 * atr[:i+1]
    return c[i] > kelt_upper[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_eth_vol_breakout(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    atr_sma = pd.Series(atr[:i+1]).rolling(50).mean().values
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return atr[i] > 1.5 * atr_sma[i] and c[i] > sma20[i] and v[i] > 1.2 * vsma[i]

def sig_eth_macd(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] > 0 and hist[i-1] <= 0 and c[i] > ema50[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_eth_ema50_short(c, h, l, v, atr, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

def sig_eth_20low_short(c, h, l, v, atr, vsma, i):
    if i < 22: return False
    low20 = pd.Series(l[:i]).rolling(20).min().values
    return c[i] < low20[-1] and v[i] > 1.5 * vsma[i]

def sig_btc_ema50_short(c, h, l, v, atr, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("  PORTFOLIO v6 — CORRECT EDGE-LEVEL VALIDATION")
    print("=" * 70)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    print("\nFetching data...")
    df_eth_4h = fetch_binance('ETHUSDT', '4h', start_ms=start_ms)
    df_link_4h = fetch_binance('LINKUSDT', '4h', start_ms=start_ms)
    df_eth_daily = fetch_binance('ETHUSDT', '1d', start_ms=start_ms)
    df_btc_daily = fetch_binance('BTCUSDT', '1d', start_ms=start_ms)

    print(f"ETH 4h: {len(df_eth_4h)} bars")
    print(f"LINK 4h: {len(df_link_4h)} bars")
    print(f"ETH Daily: {len(df_eth_daily)} bars")
    print(f"BTC Daily: {len(df_btc_daily)} bars")

    # Test each edge
    edges = {
        'L1: ETH Keltner': (df_eth_4h, sig_eth_keltner, 2.5, 0.005, 30),
        'L2: ETH Vol Breakout': (df_eth_4h, sig_eth_vol_breakout, 4.0, 0.005, 30),
        'L3: ETH MACD': (df_eth_4h, sig_eth_macd, 3.0, 0.005, 30),
        'S1: ETH EMA50 Short': (df_eth_daily, sig_eth_ema50_short, 2.0, 0.001, 30),
        'S2: ETH 20-Low Short': (df_eth_daily, sig_eth_20low_short, 2.0, 0.001, 30),
        'S3: BTC EMA50 Short': (df_btc_daily, sig_btc_ema50_short, 2.0, 0.001, 30),
    }

    print(f"\n{'Edge':<25s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>8s} {'Total':>8s}")
    print(f"{'-'*25} {'-'*4} {'-'*7} {'-'*6} {'-'*8} {'-'*8}")

    results = {}
    for name, (df, sig_fn, trail, fric, hold) in edges.items():
        if 'short' in name.lower():
            r = backtest_short(df, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        else:
            r = backtest_long(df, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        results[name] = r
        print(f"{name:<25s} {r['n']:4d} {r['pf']:7.3f} {r['wr']:5.0%} {r['avg']:+8.3f} {r['total']:+7.1%}")

    # Walk-forward for each edge
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD OOS — EACH EDGE")
    print(f"{'='*70}")

    for name, (df, sig_fn, trail, fric, hold) in edges.items():
        total = len(df)
        oos_pfs = []
        oos_totals = []

        for k in range(1, 5):
            is_pct = 0.50 + k * 0.05
            is_idx = int(total * is_pct)
            if is_idx < 100 or total - is_idx < 100: continue
            df_oos = df.iloc[is_idx:]
            if 'short' in name.lower():
                r = backtest_short(df_oos, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
            else:
                r = backtest_long(df_oos, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
            if r['n'] > 0:
                oos_pfs.append(r['pf'])
                oos_totals.append(r['total'])

        if oos_pfs:
            status = 'ROBUST' if np.mean(oos_pfs) > 1.0 else 'FRAGILE'
            print(f"{name:<25s} OOS PF: {np.mean(oos_pfs):.3f} ± {np.std(oos_pfs):.3f} [{status}]")
        else:
            print(f"{name:<25s} OOS: insufficient trades")

    # Combined portfolio estimate
    print(f"\n{'='*70}")
    print(f"  COMBINED PORTFOLIO ESTIMATE")
    print(f"{'='*70}")

    # Use full-sample total returns as a rough estimate
    # Weight by allocation and regime
    long_total = (results['L1: ETH Keltner']['total'] * 0.40 +
                  results['L2: ETH Vol Breakout']['total'] * 0.25 +
                  results['L3: ETH MACD']['total'] * 0.20)
    short_total = (results['S1: ETH EMA50 Short']['total'] * 0.50 +
                   results['S2: ETH 20-Low Short']['total'] * 0.25 +
                   results['S3: BTC EMA50 Short']['total'] * 0.15)

    # With regime gating (RISK_ON ~60% of time, RISK_OFF ~40%)
    regime_adjusted = long_total * 0.70 + short_total * 0.30  # Approximate

    print(f"Long side (weighted):     {long_total:+.1%}")
    print(f"Short side (weighted):    {short_total:+.1%}")
    print(f"Regime-adjusted total:    {regime_adjusted:+.1%} (approx)")
    print(f"\nNote: This is full-sample, not OOS. Walk-forward results are the real test.")

    # Save
    out = {name: {'pf': r['pf'], 'n': r['n'], 'total': r['total'], 'wr': r['wr']}
           for name, r in results.items()}
    with open(DATA_DIR / "edge_level_results.json", 'w') as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
