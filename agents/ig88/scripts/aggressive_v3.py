"""Aggressive v3 — 5-year data, 1h timeframe, corrected annualization"""
import pandas as pd
import numpy as np
import os, json

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data"

def ema(s, p): return s.ewm(span=p, adjust=False).mean()

def macd_sig(close, fast=12, slow=26, sig=9):
    m = ema(close, fast) - ema(close, slow)
    sg = ema(m, sig)
    h = m - sg
    sigs = np.zeros(len(close))
    for i in range(1, len(close)):
        if h.iloc[i] > 0 and h.iloc[i-1] <= 0: sigs[i] = 1
        elif h.iloc[i] < 0 and h.iloc[i-1] >= 0: sigs[i] = -1
    return sigs

def ema_xsig(close, f=8, s=21):
    ef, es = ema(close, f), ema(close, s)
    sigs = np.zeros(len(close))
    for i in range(1, len(close)):
        if ef.iloc[i] > es.iloc[i] and ef.iloc[i-1] <= es.iloc[i-1]: sigs[i] = 1
        elif ef.iloc[i] < es.iloc[i] and ef.iloc[i-1] >= es.iloc[i-1]: sigs[i] = -1
    return sigs

def run_bt(close, sigs, trail, hold, fee=0.00043, short=False):
    trades = []
    in_t = False; ep = 0; pp = 0; eb = 0
    for i in range(len(close)):
        p = close.iloc[i]
        if not in_t:
            if (not short and sigs[i] == 1) or (short and sigs[i] == -1):
                in_t = True; ep = p; pp = p; eb = i
        else:
            if short:
                pp = min(pp, p); stop = pp * (1 + trail)
                if p >= stop or (i-eb) >= hold or sigs[i] == 1:
                    trades.append({'pnl': (ep/p)-1-fee, 'bars': i-eb, 'eb': eb, 'ex': i})
                    in_t = False
            else:
                pp = max(pp, p); stop = pp * (1 - trail)
                if p <= stop or (i-eb) >= hold or sigs[i] == -1:
                    trades.append({'pnl': (p/ep)-1-fee, 'bars': i-eb, 'eb': eb, 'ex': i})
                    in_t = False
    return trades

def stats(trades, bpy):
    if len(trades) < 5: return None
    pnls = np.array([t['pnl'] for t in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    n = len(pnls)
    total = float(pnls.sum())
    gp = float(wins.sum()) if len(wins) else 0
    gl = abs(float(losses.sum())) if len(losses) else 0.0001
    pf = gp / gl
    wr = len(wins) / n
    avg_win = float(np.mean(wins)) if len(wins) else 0
    avg_loss = float(np.mean(losses)) if len(losses) else 0
    
    t_span = (trades[-1]['ex'] - trades[0]['eb']) / bpy
    if t_span < 1.0: return None
    ann = (1 + total) ** (1 / t_span) - 1 if total > -1 else -1.0
    
    eq = np.cumsum(pnls)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    trades_yr = n / t_span
    
    return {'n': n, 'wr': wr, 'pf': pf, 'total': total, 'ann': ann, 'dd': dd,
            'trades_yr': trades_yr, 'avg_win': avg_win, 'avg_loss': avg_loss, 'years': t_span}

# Use the DEEP data files (5yr 60m)
pairs = {
    "ETH": ("binance_ETHUSDT_60m.parquet", 8760),
    "BTC": ("binance_BTCUSDT_60m.parquet", 8760),
    "SOL": ("binance_SOLUSDT_60m.parquet", 8760),
    "AVAX": ("binance_AVAXUSDT_60m.parquet", 8760),
    "LINK": ("binance_LINKUSDT_60m.parquet", 8760),
    "NEAR": ("binance_NEARUSDT_60m.parquet", 8760),
}

strats = [
    ("MACD(12,26,9)", lambda c: macd_sig(c, 12, 26, 9)),
    ("MACD(8,17,9)", lambda c: macd_sig(c, 8, 17, 9)),
    ("EMA(5,13)", lambda c: ema_xsig(c, 5, 13)),
    ("EMA(8,21)", lambda c: ema_xsig(c, 8, 21)),
    ("EMA(3,8)", lambda c: ema_xsig(c, 3, 8)),
]

results = []

for sym, (fname, bpy) in pairs.items():
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): continue
    df = pd.read_parquet(path)
    close = df['close'].reset_index(drop=True)
    n = len(close)
    split = int(n * 0.6)
    train = close[:split]
    test = close[split:]
    test_years = len(test) / bpy
    
    if test_years < 1.0:
        print(f"{sym}: only {test_years:.1f}yr OOS, skipping")
        continue
    
    print(f"{sym}: {n} bars, {test_years:.1f}yr OOS ({split} train, {n-split} test)")
    
    for sname, sfn in strats:
        sigs = sfn(close)[split:]
        
        for trail in [0.02, 0.03, 0.05]:
            for hold in [16, 32, 64, 128]:
                for short in [False, True]:
                    trades = run_bt(test, sigs, trail, hold, short=short)
                    s = stats(trades, bpy)
                    if s is None: continue
                    
                    for lev in [5, 10, 15, 20, 25]:
                        lev_total = (1 + s['ann']) ** lev - 1 if s['ann'] > 0 else s['ann'] * lev
                        ann_lev = lev_total / s['years'] if s['years'] > 0 else 0
                        # Actually: leverage on compounded annual
                        if s['ann'] > 0:
                            ann_lev = (1 + s['ann']) ** lev - 1
                        else:
                            ann_lev = s['ann'] * lev
                        dd_lev = s['dd'] * lev
                        
                        if s['pf'] > 1.2 and ann_lev > 0.5 and dd_lev < 1.0:
                            results.append({
                                'sym': sym, 'strat': sname, 'dir': 'SHT' if short else 'LNG',
                                'lev': lev, 'n': s['n'], 'wr': s['wr'], 'pf': s['pf'],
                                'ann': ann_lev, 'ann1x': s['ann'], 'dd': dd_lev, 'dd1x': s['dd'],
                                'trail': trail, 'hold': hold, 'trades_yr': s['trades_yr'],
                                'years': s['years'], 'avg_win': s['avg_win'], 'avg_loss': s['avg_loss'],
                            })

results.sort(key=lambda x: x['ann'], reverse=True)

print(f"\n{'#':>3s} {'Sym':<5s} {'Strat':<16s} {'Dir':>4s} {'Lev':>3s} {'N':>5s} {'WR':>5s} {'PF':>5s} {'Ann':>7s} {'DD':>7s} {'Ann1x':>7s} {'Trd/Yr':>7s} {'Yr':>4s}")
print("-" * 85)
for i, r in enumerate(results[:40]):
    print(f"{i+1:>3d} {r['sym']:<5s} {r['strat']:<16s} {r['dir']:>4s} {r['lev']:>2dx} {r['n']:>5d} {r['wr']:>5.1%} {r['pf']:>5.2f} {r['ann']:>6.1%} {r['dd']:>6.1%} {r['ann1x']:>6.1%} {r['trades_yr']:>6.1f} {r['years']:>4.1f}")

with open('/Users/nesbitt/dev/factory/agents/ig88/data/aggressive_v3.json','w') as f:
    json.dump(results[:200], f, indent=2, default=str)
print(f"\nSaved {len(results)} results")
