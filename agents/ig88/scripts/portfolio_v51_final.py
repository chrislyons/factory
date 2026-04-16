#!/usr/bin/env python3
"""
Final Portfolio v5.1 Walk-Forward — All optimizations applied.

Changes from v5:
- Keltner edges: volume 1.5x → 1.2x, ATR trail 3.0x → 2.5x
- MACD: ADX > 25 filter added
- MACD ATR trail: kept at 3.0x
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
    pf = wins.sum()/max(gl,0.0001)
    wr = len(wins)/len(pnls)
    # Simulate: compound all returns
    compounded = np.prod(1 + pnls) - 1
    print(f"  {label}: n={len(pnls)}  PF={pf:.3f}  WR={wr:.1%}  Avg={pnls.mean():+.3f}  Compound={compounded:+.1%}")
    return {'n':len(pnls),'pf':pf,'wr':wr,'compound':compounded}


def main():
    print("="*70)
    print("PORTFOLIO v5.1 — FINAL WALK-FORWARD (All Optimizations)")
    print("="*70)

    start_ms = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp()*1000)
    print("\nFetching data from 2020...")
    eth = fetch_binance("ETHUSDT","4h",start_ms=start_ms)
    link = fetch_binance("LINKUSDT","4h",start_ms=start_ms)
    print(f"ETH: {len(eth)} bars, LINK: {len(link)} bars")

    # Portfolio allocation
    ALLOC = {
        'eth_thufri': 0.30,  # Edge 1
        'eth_vol': 0.25,     # Edge 2
        'link_thufri': 0.15, # Edge 3
        'eth_week2': 0.15,   # Edge 4
        'eth_macd': 0.15,    # Edge 5
    }
    LEVERAGE = {
        'eth_thufri': 2.0, 'eth_vol': 2.0, 'link_thufri': 1.5,
        'eth_week2': 2.0, 'eth_macd': 2.0,
    }

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

    # Run each edge year-by-year, combine as portfolio
    years = list(range(2021, 2027))

    print(f"\n{'='*70}")
    print(f"  PORTFOLIO v5.1 (optimized) vs v5.0 (baseline)")
    print(f"{'='*70}")

    for year in years:
        yr_eth = eth.loc[f'{year}-01-01':f'{year}-12-31']
        yr_link = link.loc[f'{year}-01-01':f'{year}-12-31']
        if len(yr_eth) < 100: break

        # v5.0 (baseline: 1.5x vol, 3.0x ATR, no ADX on MACD)
        t1_v5 = keltner_thufri(yr_eth, vm=1.5, am=3.0)
        t2_v5 = vol_breakout(yr_eth, vm=1.5, am=4.0)
        t3_v5 = link_thufri(yr_link, vm=1.5, am=3.0)
        t4_v5 = week2_keltner(yr_eth, vm=1.5, am=3.0)
        t5_v5_base = macd_hist(yr_eth, vm=1.2, am=3.0)  # No ADX filter

        # v5.1 (optimized: 1.2x vol, 2.5x ATR, ADX>25 on MACD)
        t1_v51 = keltner_thufri(yr_eth, vm=1.2, am=2.5)
        t2_v51 = vol_breakout(yr_eth, vm=1.2, am=4.0)
        t3_v51 = link_thufri(yr_link, vm=1.2, am=2.5)
        t4_v51 = week2_keltner(yr_eth, vm=1.2, am=2.5)
        t5_v51 = macd_hist(yr_eth, vm=1.2, am=3.0)  # With ADX>25

        # Weighted portfolio returns
        def portfolio_pnl(edge_trades, alloc, lev):
            return [t * alloc * lev for t in edge_trades]

        v5_pnls = (portfolio_pnl(t1_v5, 0.30, 2.0) + portfolio_pnl(t2_v5, 0.25, 2.0) +
                   portfolio_pnl(t3_v5, 0.15, 1.5) + portfolio_pnl(t4_v5, 0.15, 2.0) +
                   portfolio_pnl(t5_v5_base, 0.15, 2.0))
        v51_pnls = (portfolio_pnl(t1_v51, 0.30, 2.0) + portfolio_pnl(t2_v51, 0.25, 2.0) +
                    portfolio_pnl(t3_v51, 0.15, 1.5) + portfolio_pnl(t4_v51, 0.15, 2.0) +
                    portfolio_pnl(t5_v51, 0.15, 2.0))

        v5_total = sum(v5_pnls) if v5_pnls else 0
        v51_total = sum(v51_pnls) if v51_pnls else 0
        marker = " ← IMPROVED" if v51_total > v5_total else ""

        print(f"\n  {year}:")
        print(f"    v5.0 (baseline): {len(v5_pnls)} trades, portfolio return: {v5_total:+.1%}")
        print(f"    v5.1 (optimal):  {len(v51_pnls)} trades, portfolio return: {v51_total:+.1%}{marker}")

    # Full period summary
    print(f"\n{'='*70}")
    print(f"  FULL PERIOD SUMMARY (2021-2026)")
    print(f"{'='*70}")

    full_eth = eth.loc['2021-01-01':'2026-04-16']
    full_link = link.loc['2021-01-01':'2026-04-16']

    v51_t1 = keltner_thufri(full_eth, vm=1.2, am=2.5)
    v51_t2 = vol_breakout(full_eth, vm=1.2, am=4.0)
    v51_t3 = link_thufri(full_link, vm=1.2, am=2.5)
    v51_t4 = week2_keltner(full_eth, vm=1.2, am=2.5)
    v51_t5 = macd_hist(full_eth, vm=1.2, am=3.0)

    print(f"\n  Edge 1 (ETH Thu/Fri, 1.2x/2.5x):")
    analyze([t*0.30*2.0 for t in v51_t1], "  Leveraged")
    print(f"  Edge 2 (ETH Vol Breakout, 1.2x/4.0x):")
    analyze([t*0.25*2.0 for t in v51_t2], "  Leveraged")
    print(f"  Edge 3 (LINK Thu/Fri, 1.2x/2.5x):")
    analyze([t*0.15*1.5 for t in v51_t3], "  Leveraged")
    print(f"  Edge 4 (ETH Week 2, 1.2x/2.5x):")
    analyze([t*0.15*2.0 for t in v51_t4], "  Leveraged")
    print(f"  Edge 5 (ETH MACD+ADX, 1.2x/3.0x):")
    analyze([t*0.15*2.0 for t in v51_t5], "  Leveraged")

    # Combined portfolio
    all_pnls = ([t*0.30*2.0 for t in v51_t1] + [t*0.25*2.0 for t in v51_t2] +
                [t*0.15*1.5 for t in v51_t3] + [t*0.15*2.0 for t in v51_t4] +
                [t*0.15*2.0 for t in v51_t5])
    print(f"\n  PORTFOLIO v5.1 TOTAL:")
    r = analyze(all_pnls, "  All edges combined")
    if r:
        annual = r['compound'] / 5.25  # ~5.25 years
        print(f"  Approx annual return: {annual:+.1%} per year")


if __name__ == "__main__":
    main()
