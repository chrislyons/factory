#!/usr/bin/env python3
"""Corrected annualized returns — equity compounding."""
import numpy as np, pandas as pd
from pathlib import Path
import json

DATA = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
ASSETS = ["ETH","AVAX","SOL","LINK","NEAR"]
FRICTION = 0.0007

def ensure_dt(df):
    if 'time' not in df.columns:
        df = df.reset_index()
        for c in ['timestamp','datetime','index','level_0']:
            if c in df.columns: df=df.rename(columns={c:'time'}); break
    if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
        if df['time'].dtype=='int64': df['time']=pd.to_datetime(df['time'],unit='ms' if df['time'].iloc[0]>1e12 else 's')
    return df

def load():
    d={}
    for a in ASSETS:
        best=0; df=None
        for f in DATA.glob(f"*{a}*_60m.parquet"):
            t=pd.read_parquet(f)
            if len(t)>best: best=len(t); df=ensure_dt(t).sort_values('time').reset_index(drop=True)
        d[a]=df
    return d

def bt_trades(df,d,a,s,t,h):
    n=len(df); H=df['high'].values.astype(float); L=df['low'].values.astype(float); C=df['close'].values.astype(float)
    up=np.full(n,np.nan)
    for i in range(d-1,n): up[i]=np.max(H[i-d+1:i+1])
    tr=np.zeros(n)
    for i in range(1,n): tr[i]=max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
    atr=np.full(n,np.nan)
    for i in range(a,n): atr[i]=np.mean(tr[i-a+1:i+1])
    trades=[]; inp=ep=sp=hi=0.0; eb=0
    for i in range(max(d+2,a+2,50),n):
        if np.isnan(up[i]) or np.isnan(atr[i]): continue
        if inp:
            hi=max(hi,C[i]); sp=max(sp,hi*(1-t))
            if C[i]<=sp or (i-eb)>=h: trades.append((sp-ep)/ep-FRICTION); inp=False
        else:
            if i>0 and C[i]>up[i-1]: inp,ep,sp,hi,eb=True,C[i],C[i]-s*atr[i],C[i],i
    return trades

def compounded_returns(trades, leverage=1.0):
    """Proper equity compounding with leverage."""
    equity = 1.0
    peak = 1.0
    max_dd = 0
    equity_curve = [1.0]
    for r in trades:
        # Leverage amplifies returns
        lev_ret = r * leverage
        equity *= (1 + lev_ret)
        equity_curve.append(equity)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    return equity, max_dd, equity_curve

data = load()

print("="*80)
print("CORRECTED ANNUALIZED RETURNS — EQUITY COMPOUNDING (FULL SAMPLE, 5yr)")
print("="*80)
print()

results = {}
for lev in [1, 2, 3]:
    print(f"--- {lev}x Leverage ---")
    print(f"{'Asset':6s} {'Trades':7s} {'WR':5s} {'PF':5s} {'Equity':10s} {'Ann%':8s} {'MaxDD':7s}")
    print("-"*55)
    for a in ASSETS:
        df = data[a]
        trades = bt_trades(df, 20, 10, 1.5, 0.02, 96)
        if not trades:
            continue
        w = [t for t in trades if t > 0]
        gp = sum(w); gl = abs(sum(t for t in trades if t <= 0)) or 0.001
        pf = gp/gl
        wr = len(w)/len(trades)*100
        equity, max_dd, _ = compounded_returns(trades, lev)
        n_years = len(df) / 8760  # bars / hours_per_year
        ann = equity ** (1/n_years) - 1
        print(f"{a:6s} {len(trades):7d} {wr:5.0f}% {pf:5.2f} {equity:10.2f}x {ann*100:7.0f}% {max_dd*100:6.1f}%")
        if lev == 2:
            results[a] = {"equity": equity, "ann": ann, "pf": pf, "wr": wr, "trades": len(trades), "max_dd": max_dd, "n_years": n_years}
    print()

print("="*80)
print("WALK-FORWARD COMPOUNDED (5 splits)")
print("="*80)
print()
for lev in [1, 2]:
    print(f"--- {lev}x Leverage ---")
    print(f"{'Asset':6s} {'Avg PF':7s} {'Avg Ann%':9s} {'Min Ann%':9s}")
    print("-"*35)
    for a in ASSETS:
        df = data[a]
        n = len(df); sz = n // 5
        split_anns = []
        for si in range(5):
            ts = si*sz + sz//2; te = min((si+1)*sz, n)
            if te-ts < 200: continue
            sub = df.iloc[ts:te].reset_index(drop=True)
            trades = bt_trades(sub, 20, 10, 1.5, 0.02, 96)
            if len(trades) < 5: continue
            w = [t for t in trades if t > 0]
            gp = sum(w); gl = abs(sum(t for t in trades if t <= 0)) or 0.001
            pf = gp/gl
            equity, _, _ = compounded_returns(trades, lev)
            n_yrs = len(sub) / 8760
            ann = equity ** (1/n_yrs) - 1
            split_anns.append(ann)
        if split_anns:
            avg_ann = np.mean(split_anns)
            min_ann = min(split_anns)
            print(f"{a:6s} {np.mean([gp/gl for _ in split_anns]):7.2f} {avg_ann*100:8.0f}% {min_ann*100:8.0f}%")
    print()

# Save corrected projections
with open("/Users/nesbitt/dev/factory/agents/ig88/data/realistic_projections.json","w") as f:
    json.dump({k: {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in results.items()}, f, indent=2)
print("Saved corrected projections.")
