#!/usr/bin/env python3
"""
Edge 4 Kill Test: Compare Portfolio v5.1 WITH vs WITHOUT Edge 4.
Reallocate Edge 4's 15% to Edge 1 and Edge 5 proportionally.
"""

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


def keltner_thufri(df, vm=1.2, am=2.5):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr; vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        dow=df.index[i].weekday()
        if dow not in [3,4]: continue
        if c[i]>kelt[i] and v[i]>vm*vsma[i] and adx[i]>25:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def week2_keltner(df, vm=1.2, am=2.5):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr; vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        day=df.index[i].day; dow=df.index[i].weekday()
        if not(8<=day<=14 and dow not in [3,4]): continue
        if c[i]>kelt[i] and v[i]>vm*vsma[i]:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def vol_breakout(df, vm=1.2, am=4.0):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    atr_sma=pd.Series(atr).rolling(50).mean().values
    sma20=pd.Series(c).rolling(20).mean().values
    vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        if atr[i]>1.5*atr_sma[i] and c[i]>sma20[i] and v[i]>vm*vsma[i]:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def link_thufri(df, vm=1.2, am=2.5):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr; vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        dow=df.index[i].weekday()
        if dow not in [3,4]: continue
        if c[i]>kelt[i] and v[i]>vm*vsma[i]:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def macd_hist(df, vm=1.2, am=3.0):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    e12=pd.Series(c).ewm(span=12,adjust=False).mean().values
    e26=pd.Series(c).ewm(span=26,adjust=False).mean().values
    macd=e12-e26; sig=pd.Series(macd).ewm(span=9,adjust=False).mean().values
    hist=macd-sig; e50=pd.Series(c).ewm(span=50,adjust=False).mean().values
    vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        if hist[i]>0 and hist[i-1]<=0 and c[i]>e50[i] and v[i]>vm*vsma[i] and adx[i]>25:
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def analyze(pnls, label=""):
    if not pnls:
        print(f"  {label}: n=0")
        return None
    pnls = np.array(pnls)
    wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    wr = len(wins)/len(pnls)
    compounded = np.prod(1 + pnls) - 1
    # Max drawdown
    cum = np.cumprod(1 + pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = dd.max() if len(dd) > 0 else 0
    print(f"  {label}: n={len(pnls)}  PF={pf:.3f}  WR={wr:.1%}  Compound={compounded:+.1%}  MaxDD={max_dd:.1%}")
    return {'n':len(pnls), 'pf':pf, 'wr':wr, 'compound':compounded, 'max_dd':max_dd}


def portfolio_pnl(edge_trades, alloc, lev):
    return [t * alloc * lev for t in edge_trades]


def main():
    print("=" * 70)
    print("EDGE 4 KILL TEST: Portfolio v5.1 WITH vs WITHOUT Edge 4")
    print("=" * 70)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    print("\nFetching data from 2020...")
    eth = fetch_binance("ETHUSDT", "4h", start_ms=start_ms)
    link = fetch_binance("LINKUSDT", "4h", start_ms=start_ms)
    print(f"ETH: {len(eth)} bars, LINK: {len(link)} bars")

    years = list(range(2021, 2027))

    # Collect all trades for full-period analysis
    all_with_e4 = []
    all_without_e4 = []

    print(f"\n{'='*70}")
    print(f"  YEAR-BY-YEAR COMPARISON")
    print(f"{'='*70}")

    for year in years:
        yr_eth = eth.loc[f'{year}-01-01':f'{year}-12-31']
        yr_link = link.loc[f'{year}-01-01':f'{year}-12-31']
        if len(yr_eth) < 100: break

        # Edge trades (v5.1 optimized params)
        t1 = keltner_thufri(yr_eth, vm=1.2, am=2.5)   # Edge 1
        t2 = vol_breakout(yr_eth, vm=1.2, am=4.0)      # Edge 2
        t3 = link_thufri(yr_link, vm=1.2, am=2.5)      # Edge 3
        t4 = week2_keltner(yr_eth, vm=1.2, am=2.5)     # Edge 4
        t5 = macd_hist(yr_eth, vm=1.2, am=3.0)         # Edge 5

        # Portfolio WITH Edge 4 (v5.1 current)
        with_e4 = (portfolio_pnl(t1, 0.30, 2.0) + portfolio_pnl(t2, 0.25, 2.0) +
                   portfolio_pnl(t3, 0.15, 1.5) + portfolio_pnl(t4, 0.15, 2.0) +
                   portfolio_pnl(t5, 0.15, 2.0))

        # Portfolio WITHOUT Edge 4 (reallocate to E1 and E5 proportionally)
        # E1: 30/45 = 2/3 of 15% = +10% -> 40%
        # E5: 15/45 = 1/3 of 15% = +5%  -> 20%
        without_e4 = (portfolio_pnl(t1, 0.40, 2.0) + portfolio_pnl(t2, 0.25, 2.0) +
                      portfolio_pnl(t3, 0.15, 1.5) +
                      portfolio_pnl(t5, 0.20, 2.0))

        w4_total = sum(with_e4) if with_e4 else 0
        wo4_total = sum(without_e4) if without_e4 else 0

        all_with_e4.extend(with_e4)
        all_without_e4.extend(without_e4)

        print(f"\n  {year}:")
        print(f"    WITH    Edge 4: {len(with_e4):3d} trades, return: {w4_total:+.1%}")
        print(f"    WITHOUT Edge 4: {len(without_e4):3d} trades, return: {wo4_total:+.1%}  (diff: {wo4_total-w4_total:+.1%})")

    # Full period
    print(f"\n{'='*70}")
    print(f"  FULL PERIOD 2021-2026 SUMMARY")
    print(f"{'='*70}")

    print(f"\n  WITH Edge 4 (v5.1 current):")
    r_with = analyze(all_with_e4, "  Portfolio")

    print(f"\n  WITHOUT Edge 4 (reallocated):")
    r_without = analyze(all_without_e4, "  Portfolio")

    if r_with and r_without:
        print(f"\n  DELTA (without - with):")
        print(f"    PF: {r_without['pf'] - r_with['pf']:+.3f}")
        print(f"    WR: {r_without['wr'] - r_with['wr']:+.1%}")
        print(f"    Compound: {r_without['compound'] - r_with['compound']:+.1%}")
        print(f"    MaxDD: {r_without['max_dd'] - r_with['max_dd']:+.1%}")

        # Edge 4 standalone for context
        print(f"\n  Edge 4 standalone contribution (for reference):")
        full_eth = eth.loc['2021-01-01':'2026-04-16']
        e4_trades = week2_keltner(full_eth, vm=1.2, am=2.5)
        analyze([t * 0.15 * 2.0 for t in e4_trades], "  Edge 4 leveraged")


if __name__ == "__main__":
    main()
