#!/usr/bin/env python3
"""Test short edges on 4h timeframe to reduce funding costs."""

import numpy as np, pandas as pd, requests
from datetime import datetime, timezone

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
                trades.append({'ret': ret, 'bars': bars_held}); in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; lowest = c[i]
    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[],'avg_hold':0}
    pnls = np.array([t['ret'] for t in trades])
    wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    avg_hold = np.mean([t['bars'] for t in trades])
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
            'total':pnls.sum(),'trades':trades,'avg_hold':avg_hold}

# === SHORT SIGNALS (adapted for 4h) ===

def sig_ema50_short_4h(c, h, l, v, atr, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

def sig_20low_short_4h(c, h, l, v, atr, vsma, i):
    if i < 22: return False
    low20 = pd.Series(l[:i]).rolling(20).min().values
    return c[i] < low20[-1] and v[i] > 1.5 * vsma[i]

def sig_macd_short_4h(c, h, l, v, atr, vsma, i):
    """MACD histogram crosses below 0 — trend reversal short"""
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] < 0 and hist[i-1] >= 0 and c[i] < ema50[i] and v[i] > 1.2 * vsma[i]

def sig_ema_cross_short_4h(c, h, l, v, atr, vsma, i):
    """EMA12 crosses below EMA50"""
    if i < 55: return False
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return e12[i] < e50[i] and e12[i-1] >= e50[i-1] and v[i] > 1.2 * vsma[i]

def sig_donchian_breakdown_4h(c, h, l, v, atr, vsma, i):
    """Close breaks below 20-bar low"""
    if i < 22: return False
    low20 = pd.Series(l[:i]).rolling(20).min().values[-1]
    return c[i] < low20 and v[i] > 1.2 * vsma[i]

def main():
    print("Fetching ETH 4h data (2020-2026)...")
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    df = fetch_binance('ETHUSDT', '4h', start_ms=start_ms)
    print(f"ETH 4h: {len(df)} bars\n")

    # Test different max_hold for 4h shorts
    signals = {
        'EMA50 Short 4h': sig_ema50_short_4h,
        '20-Low Short 4h': sig_20low_short_4h,
        'MACD Short 4h': sig_macd_short_4h,
        'EMA Cross Short 4h': sig_ema_cross_short_4h,
        'Donchian Breakdown 4h': sig_donchian_breakdown_4h,
    }

    for name, sig_fn in signals.items():
        print(f"\n  {name}:")
        print(f"  {'Hold':>4s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>7s} {'Total':>8s} {'AvgHold':>7s} {'Funding':>8s} {'Net':>8s}")
        print(f"  {'-'*4} {'-'*4} {'-'*7} {'-'*6} {'-'*7} {'-'*8} {'-'*7} {'-'*8} {'-'*8}")

        for hold in [5, 10, 15, 20, 30]:
            r = backtest_short(df, sig_fn, trail_mult=2.0, max_hold=hold)
            if r['n'] == 0:
                print(f"  {hold:4d} {'—':>4s} {'—':>7s} {'—':>6s} {'—':>7s} {'—':>8s} {'—':>7s} {'—':>8s} {'—':>8s}")
                continue
            # Funding: 0.0001 per 8h = 0.0003 per 4h bar
            avg_hold_bars = r['avg_hold']
            n = r['n']
            years = 6
            trades_per_year = n / years
            days_in_market = trades_per_year * avg_hold_bars * 4 / 24
            market_fraction = days_in_market / 365
            funding = 0.0003 * avg_hold_bars * n  # per-trade funding
            net = r['total'] - funding
            print(f"  {hold:4d} {r['n']:4d} {r['pf']:7.3f} {r['wr']:5.0%} {r['avg']:+6.2%} "
                  f"{r['total']:+7.1%} {avg_hold_bars:6.1f}b {-funding:+7.1%} {net:+7.1%}")

    # Walk-forward for best
    print(f"\n--- WALK-FORWARD OOS (4h shorts) ---\n")
    total = len(df)
    for name, sig_fn in signals.items():
        for hold in [10, 15, 20]:
            r_full = backtest_short(df, sig_fn, max_hold=hold)
            if r_full['n'] < 10 or r_full['pf'] < 1.0:
                continue
            oos_pfs = []
            for k in range(1, 5):
                is_pct = 0.50 + k * 0.05
                is_idx = int(total * is_pct)
                if is_idx < 100 or total - is_idx < 100: continue
                r = backtest_short(df.iloc[is_idx:], sig_fn, max_hold=hold)
                if r['n'] > 0:
                    oos_pfs.append(r['pf'])
            if oos_pfs:
                status = "ROBUST" if np.mean(oos_pfs) > 1.0 else "FRAGILE"
                print(f"  {name} (hold={hold}) OOS PF={np.mean(oos_pfs):.3f} ± {np.std(oos_pfs):.3f} [{status}]")

if __name__ == "__main__":
    main()
