#!/usr/bin/env python3
"""Walk-forward validation of 1.5x ATR stop improvement + asset-specific params."""
import numpy as np, pandas as pd
from pathlib import Path

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

def bt(df,d,a,s,t,h):
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
    if not trades: return None
    w=[x for x in trades if x>0]; lo=[x for x in trades if x<=0]
    gp=sum(w) if w else 0; gl=abs(sum(lo)) if lo else 0.001
    eq=np.cumsum(trades); pk=np.maximum.accumulate(eq)
    return {"pf":gp/gl,"wr":len(w)/len(trades)*100,"trades":len(trades),"avg":np.mean(trades)*100,"max_dd":np.max(pk-eq)*100}

def wf(df,d,a,s,t,h,ns=5):
    n=len(df); sz=n//ns; res=[]
    for si in range(ns):
        ts=si*sz+sz//2; te=min((si+1)*sz,n)
        if te-ts<200: continue
        sub=df.iloc[ts:te].reset_index(drop=True)
        r=bt(sub,d,a,s,t,h)
        if r: res.append(r)
    return res

data=load()

print("="*70)
print("WALK-FORWARD: Baseline D20/A10/S2.0/T2% vs Tight Stop D20/A10/S1.5/T2%")
print("="*70)
for a in ASSETS:
    df=data[a]
    wf_base=wf(df,20,10,2.0,0.02,96,5)
    wf_tight=wf(df,20,10,1.5,0.02,96,5)
    if wf_base and wf_tight:
        bp=np.mean([r['pf'] for r in wf_base]); tp=np.mean([r['pf'] for r in wf_tight])
        bdd=np.mean([r['max_dd'] for r in wf_base]); tdd=np.mean([r['max_dd'] for r in wf_tight])
        print(f"{a}: Baseline WF PF={bp:.2f} DD={bdd:.1f}% | Tight Stop WF PF={tp:.2f} DD={tdd:.1f}% | {'IMPROVED' if tp>bp else 'WORSE'}")

print()
print("="*70)
print("ASSET-SPECIFIC: Best params from grid (D40/A20 for ETH/AVAX)")
print("="*70)
configs={"ETH":(30,15,1.5,0.025),"AVAX":(40,8,1.5,0.02),"SOL":(20,8,1.5,0.015),"LINK":(20,8,1.5,0.015),"NEAR":(15,8,1.5,0.015)}
for a in ASSETS:
    df=data[a]; d,s1,s2,tl=configs[a]
    wf_opt=wf(df,d,10,s1,tl,96,5)
    wf_base=wf(df,20,10,2.0,0.02,96,5)
    if wf_opt and wf_base:
        op=np.mean([r['pf'] for r in wf_opt]); bp=np.mean([r['pf'] for r in wf_base])
        otr=np.mean([r['trades'] for r in wf_opt]); btr=np.mean([r['trades'] for r in wf_base])
        print(f"{a}: Base D20/A10/S2.0 PF={bp:.2f} ~{btr:.0f}trades | Opt D{d}/A10/S{s1} T{tl*100:.0f}% PF={op:.2f} ~{otr:.0f}trades | {'IMPROVED' if op>bp else 'WORSE'}")

print()
print("="*70)
print("ANNUALIZED PROJECTION (Walk-Forward PF, realistic)")
print("="*70)
import json
reg={}
for a in ASSETS:
    df=data[a]
    wf_res=wf(df,20,10,2.0,0.02,96,5)
    if wf_res:
        wpf=np.mean([r['pf'] for r in wf_res])
        wtotal=np.mean([r['trades'] for r in wf_res])*np.mean([r['avg'] for r in wf_res])/100
        ann=(1+wtotal)**(1/2.5)-1
        reg[a]= {"wf_pf":round(wpf,2),"ann_ret_pct":round(ann*100,0),"trades_yr":int(np.mean([r['trades'] for r in wf_res])*2.5)}
        print(f"{a}: WF PF={wpf:.2f} Ann={ann*100:.0f}% Trades/yr={reg[a]['trades_yr']}")

with open("/Users/nesbitt/dev/factory/agents/ig88/data/realistic_projections.json","w") as f:
    json.dump(reg,f,indent=2)
print("\nSaved to data/realistic_projections.json")
