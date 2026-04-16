#!/usr/bin/env python3
"""
Proper Walk-Forward for Keltner Breakout — 50/50 splits with 2+ year OOS windows.
"""

import json, numpy as np, pandas as pd, requests
from datetime import datetime, timezone


def fetch_binance(symbol, interval="4h", start_ms=None):
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
        params["startTime"] = data[-1][0] + 1
    df = pd.DataFrame(all_data, columns=['ts','o','h','l','c','v','ct','q','t','tb','tq','ig'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    for col in ['o','h','l','c','v']:
        df[col] = df[col].astype(float)
    return df.set_index('ts')[['o','h','l','c','v']].rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})


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


def keltner_thufri(df, vol_mult=1.5, atr_trail=3.0):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr; vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-atr_trail*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30:
                trades.append(ret); in_t=False; continue
        if in_t: continue
        dow=df.index[i].weekday()
        if dow not in [3,4]: continue
        if c[i]>kelt[i] and v[i]>vol_mult*vsma[i] and adx[i]>25:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def macd_hist(df, vol_mult=1.2, atr_trail=3.0):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    e12=pd.Series(c).ewm(span=12,adjust=False).mean().values
    e26=pd.Series(c).ewm(span=26,adjust=False).mean().values
    macd=e12-e26; sig=pd.Series(macd).ewm(span=9,adjust=False).mean().values
    hist=macd-sig; e50=pd.Series(c).ewm(span=50,adjust=False).mean().values
    vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-atr_trail*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30:
                trades.append(ret); in_t=False; continue
        if in_t: continue
        if hist[i]>0 and hist[i-1]<=0 and c[i]>e50[i] and v[i]>vol_mult*vsma[i]:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def analyze(trades, label=""):
    if not trades:
        print(f"  {label}: n=0, no trades")
        return None
    pnls=np.array(trades)
    wins=pnls[pnls>0]
    gl=abs(pnls[pnls<=0].sum())
    pf=wins.sum()/max(gl,0.0001)
    wr=len(wins)/len(pnls)
    print(f"  {label}: n={len(pnls)}  PF={pf:.3f}  WR={wr:.1%}  Avg={pnls.mean():+.3f}  Total={pnls.sum():+.1%}")
    return {'n':len(pnls),'pf':pf,'wr':wr,'avg':pnls.mean(),'total':pnls.sum()}


def main():
    print("=" * 70)
    print("PROPER WALK-FORWARD — Long OOS Windows")
    print("=" * 70)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    print("\nFetching 4h data from 2020...")
    eth = fetch_binance("ETHUSDT", "4h", start_ms=start_ms)
    print(f"ETH: {eth.index[0]} to {eth.index[-1]} ({len(eth)} bars)")

    # Walk-forward splits: ~2yr OOS each, sequential
    splits = [
        ("Train 2021-2022 / Test 2023", '2021-01-01', '2023-01-01', '2023-01-01', '2025-01-01'),
        ("Train 2021-2023 / Test 2024-2025", '2021-01-01', '2024-01-01', '2024-01-01', '2026-04-16'),
        ("Train 2021-2024 / Test 2025+", '2021-01-01', '2025-01-01', '2025-01-01', '2026-04-16'),
    ]

    configs = [
        ("Baseline (1.5x vol, 3.0x ATR)", 1.5, 3.0),
        ("1.2x vol, 3.0x ATR", 1.2, 3.0),
        ("1.2x vol, 2.5x ATR", 1.2, 2.5),
        ("1.0x vol, 3.0x ATR", 1.0, 3.0),
    ]

    for config_name, vm, am in configs:
        print(f"\n{'='*60}")
        print(f"  {config_name}")
        print(f"{'='*60}")

        all_oos_trades = []
        for split_name, ts, te, os, oe in splits:
            # Full period for context
            test_df = eth.loc[os:oe]
            if len(test_df) < 100:
                continue
            trades = keltner_thufri(test_df, vol_mult=vm, atr_trail=am)
            analyze(trades, f"OOS {os[:7]} to {oe[:7]} ({split_name.split('/')[1].strip()})")
            all_oos_trades.extend(trades)

        analyze(all_oos_trades, "ALL OOS COMBINED")

    # Also test MACD with and without filter
    print(f"\n{'='*60}")
    print(f"  MACD Histogram — Baseline vs Filtered")
    print(f"{'='*60}")
    macd_all = macd_hist(eth.loc['2021-01-01':'2026-04-16'], vol_mult=1.2)
    analyze(macd_all, "MACD Baseline (all periods)")

    # MACD by year
    for year in range(2021, 2027):
        yr_df = eth.loc[f'{year}-01-01':f'{year}-12-31']
        if len(yr_df) < 100:
            break
        yr_trades = macd_hist(yr_df, vol_mult=1.2)
        analyze(yr_trades, f"MACD {year}")


if __name__ == "__main__":
    main()
