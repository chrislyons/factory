#!/usr/bin/env python3
"""
Test new edges with leverage and compute signal overlap with existing MACD edge.
"""

import numpy as np, pandas as pd, requests
from datetime import datetime, timezone
from pathlib import Path

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

def compute_rsi(c, p=14):
    delta = np.diff(c)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(p).mean().values
    avg_loss = pd.Series(loss).rolling(p).mean().values
    rs = np.where(avg_loss > 0, avg_gain / np.where(avg_loss > 0, avg_loss, 1), 100)
    rsi = 100 - 100 / (1 + rs)
    return np.concatenate([[50], rsi])

def backtest_with_trades(df, signal_fn, trail_mult=2.5, friction=0.005, max_hold=30):
    """Returns trade list with entry/exit indices for overlap analysis."""
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values
    trades = []; in_trade = False; highest = 0.0; entry_idx = 0; entry_price = 0.0
    for i in range(55, len(c)):
        if in_trade:
            highest = max(highest, c[i])
            trail_stop = highest - trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (c[i] - entry_price) / entry_price - friction
            if c[i] < trail_stop or bars_held >= max_hold:
                trades.append({'entry': entry_idx, 'exit': i, 'ret': ret})
                in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, adx, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; highest = c[i]
    if trades:
        pnls = np.array([t['ret'] for t in trades])
        wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
        pf = wins.sum()/max(gl, 0.0001)
        return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
                'total':pnls.sum(),'trades':trades}
    return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[]}

# === SIGNALS ===

def sig_macd_v6(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] > 0 and hist[i-1] <= 0 and c[i] > ema50[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_ema_ribbon(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    e8 = pd.Series(c[:i+1]).ewm(span=8, adjust=False).mean().values
    e21 = pd.Series(c[:i+1]).ewm(span=21, adjust=False).mean().values
    e50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    prev_aligned = e8[i-1] > e21[i-1] and e21[i-1] > e50[i-1]
    return (e8[i] > e21[i] and e21[i] > e50[i] and not prev_aligned and
            c[i] > e8[i] and v[i] > 1.2 * vsma[i])

def sig_macd_pullback(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema21 = pd.Series(c[:i+1]).ewm(span=21, adjust=False).mean().values
    touched = any(c[max(i-3,0):i+1] <= ema21[max(i-3,0):i+1] * 1.005)
    return (hist[i] > 0 and touched and c[i] > ema21[i] * 1.002 and
            adx[i] > 25 and v[i] > 1.2 * vsma[i])

def main():
    print("Fetching ETH 4h data...")
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    df = fetch_binance('ETHUSDT', '4h', start_ms=start_ms)
    print(f"ETH 4h: {len(df)} bars\n")

    edges = {
        'MACD v6': sig_macd_v6,
        'EMA Ribbon': sig_ema_ribbon,
        'MACD Pullback': sig_macd_pullback,
    }

    # Full-sample with different leverage
    print("=== LEVERAGE IMPACT ===\n")
    for name, sig_fn in edges.items():
        print(f"  {name}:")
        for lev in [1.0, 1.5, 2.0]:
            r = backtest_with_trades(df, sig_fn, friction=0.005 * lev)
            # Margin cost: 8% annual, only while in trade
            n = r['n']
            if n == 0: continue
            trades_per_year = n / 6
            avg_hold = 5  # 30 bars * 4h / 24
            days_in_market = trades_per_year * avg_hold
            margin_cost = 0.08 * (days_in_market / 365) * 6  # 6 years
            gross = r['total'] * lev
            net = gross - margin_cost
            ann = (1 + net) ** (1/6) - 1 if net > -0.99 else -0.99
            print(f"    {lev}x: PF={r['pf']:.2f} WR={r['wr']:.0%} "
                  f"Gross={gross:+.1%} Margin={-margin_cost:.1%} Net={net:+.1%} Ann={ann:+.1%}")

    # Signal overlap analysis
    print("\n=== SIGNAL OVERLAP ===\n")
    results = {}
    for name, sig_fn in edges.items():
        results[name] = backtest_with_trades(df, sig_fn)

    for n1 in edges:
        for n2 in edges:
            if n1 >= n2: continue
            # Check how many bars have entry signals in both
            t1 = set(t['entry'] for t in results[n1]['trades'])
            t2 = set(t['entry'] for t in results[n2]['trades'])
            overlap = len(t1 & t2)
            total_unique = len(t1 | t2)
            jaccard = overlap / total_unique if total_unique > 0 else 0
            print(f"  {n1} vs {n2}: {overlap} shared entries out of {total_unique} unique "
                  f"(Jaccard={jaccard:.2f}, overlap={overlap/max(len(t1),1):.0%} of {n1})")

    # Combined portfolio: MACD v6 + MACD Pullback + EMA Ribbon
    print("\n=== COMBINED PORTFOLIO (2x leverage) ===\n")

    # Interleave all trades chronologically
    all_trades = []
    alloc = {'MACD v6': 0.45, 'EMA Ribbon': 0.25, 'MACD Pullback': 0.30}
    for name, weight in alloc.items():
        for t in results[name]['trades']:
            all_trades.append({**t, 'weight': weight, 'edge': name})
    all_trades.sort(key=lambda x: x['exit'])

    eq = [1.0]
    peak = 1.0
    max_dd = 0
    lev = 2.0
    for t in all_trades:
        pnl = t['ret'] * t['weight'] * lev
        eq.append(max(eq[-1] * (1 + pnl), 1))
        peak = max(peak, eq[-1])
        max_dd = max(max_dd, (peak - eq[-1]) / peak)

    total_ret = eq[-1] - 1
    ann = (1 + total_ret) ** (1/6) - 1

    # Margin cost
    total_trades = sum(len(results[n]['trades']) for n in alloc)
    days_in_market = total_trades / 6 * 5
    margin_cost = 0.08 * (days_in_market / 365) * 6
    net_ret = total_ret - margin_cost
    net_ann = (1 + net_ret) ** (1/6) - 1 if net_ret > -0.99 else -0.99

    print(f"  Allocation: {', '.join(f'{k}={v:.0%}' for k,v in alloc.items())}")
    print(f"  Gross return (6y): {total_ret:+.1%}")
    print(f"  Margin cost: {-margin_cost:.1%}")
    print(f"  Net return: {net_ret:+.1%}")
    print(f"  Net annualized: {net_ann:+.1%}")
    print(f"  Max drawdown: {max_dd:.1%}")
    print(f"  Total trades: {total_trades}")

    # vs MACD only
    r_macd = results['MACD v6']
    eq_macd = [1.0]
    peak_macd = 1.0
    dd_macd = 0
    for t in r_macd['trades']:
        eq_macd.append(max(eq_macd[-1] * (1 + t['ret'] * lev), 1))
        peak_macd = max(peak_macd, eq_macd[-1])
        dd_macd = max(dd_macd, (peak_macd - eq_macd[-1]) / peak_macd)

    ret_macd = eq_macd[-1] - 1
    days_macd = r_macd['n'] / 6 * 5
    cost_macd = 0.08 * (days_macd / 365) * 6
    net_macd = ret_macd - cost_macd
    ann_macd = (1 + net_macd) ** (1/6) - 1 if net_macd > -0.99 else -0.99

    print(f"\n  MACD v6 only (2x):")
    print(f"    Net return: {net_macd:+.1%}, Ann: {ann_macd:+.1%}, DD: {dd_macd:.1%}")
    print(f"\n  Portfolio vs MACD-only:")
    print(f"    Return: {net_ret/net_macd - 1:+.0%} {'better' if net_ret > net_macd else 'worse'}")
    print(f"    DD: {max_dd/dd_macd - 1:+.0%} {'worse' if max_dd > dd_macd else 'better'}")

if __name__ == "__main__":
    main()
