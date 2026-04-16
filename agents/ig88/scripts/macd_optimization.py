#!/usr/bin/env python3
"""MACD Histogram Edge Optimization — Fix the 2022/2024 losses."""

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


def macd_backtest(df, vol_mult=1.2, atr_trail=3.0, adx_filter=None, rsi_filter=None,
                   btc_ema50_filter=False, btc_df=None):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    e12=pd.Series(c).ewm(span=12,adjust=False).mean().values
    e26=pd.Series(c).ewm(span=26,adjust=False).mean().values
    macd=e12-e26; sig=pd.Series(macd).ewm(span=9,adjust=False).mean().values
    hist=macd-sig; e50=pd.Series(c).ewm(span=50,adjust=False).mean().values
    vsma=pd.Series(v).rolling(20).mean().values

    # RSI
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.values

    # BTC EMA50
    btc_below = None
    if btc_ema50_filter and btc_df is not None:
        bc = btc_df['close'].resample('D').last().dropna()
        be50 = bc.ewm(span=50,adjust=False).mean()
        trend = (bc > be50).astype(int)
        btc_below = (trend.reindex(df.index, method='ffill').fillna(0).values == 0)

    trades = []; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55, len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-atr_trail*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30:
                trades.append({'pnl':ret,'entry_idx':ei,'exit_idx':i}); in_t=False; continue
        if in_t: continue
        if hist[i]>0 and hist[i-1]<=0 and c[i]>e50[i] and v[i]>vol_mult*vsma[i]:
            if adx_filter and adx[i] < adx_filter: continue
            if rsi_filter and rsi[i] > rsi_filter: continue  # skip overbought
            if btc_ema50_filter and btc_below is not None and btc_below[i]: continue
            in_t=True; ep=c[i]; ei=i; hi=c[i]
    return trades


def analyze(trades, label=""):
    if not trades:
        print(f"  {label}: n=0")
        return None
    pnls = np.array([t['pnl'] for t in trades])
    wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl,0.0001)
    print(f"  {label}: n={len(pnls)}  PF={pf:.3f}  WR={len(wins)/len(pnls):.1%}  Avg={pnls.mean():+.3f}  Total={pnls.sum():+.1%}")
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'total':pnls.sum()}


def main():
    print("="*70)
    print("MACD HISTOGRAM EDGE OPTIMIZATION")
    print("="*70)

    start_ms = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp()*1000)
    print("\nFetching data from 2020...")
    eth = fetch_binance("ETHUSDT","4h",start_ms=start_ms)
    btc = fetch_binance("BTCUSDT","4h",start_ms=start_ms)
    print(f"ETH: {len(eth)} bars, BTC: {len(btc)} bars")

    # Baseline
    print("\n--- Baseline (no filters) ---")
    base = macd_backtest(eth, vol_mult=1.2)
    analyze(base, "Full")
    for year in range(2021, 2027):
        yr = eth.loc[f'{year}-01-01':f'{year}-12-31']
        if len(yr) < 100: break
        yt = macd_backtest(yr, vol_mult=1.2)
        analyze(yt, str(year))

    # Test filters
    filters = [
        ("ADX > 20", {'adx_filter': 20}),
        ("ADX > 25", {'adx_filter': 25}),
        ("ADX > 30", {'adx_filter': 30}),
        ("RSI < 65", {'rsi_filter': 65}),
        ("RSI < 70", {'rsi_filter': 70}),
        ("BTC > EMA50 only", {'btc_ema50_filter': True, 'btc_df': btc}),
        ("ADX>25 + BTC>EMA50", {'adx_filter': 25, 'btc_ema50_filter': True, 'btc_df': btc}),
        ("ADX>20 + RSI<65", {'adx_filter': 20, 'rsi_filter': 65}),
    ]

    print("\n--- Filter Tests (Full Period) ---")
    for name, kwargs in filters:
        trades = macd_backtest(eth, vol_mult=1.2, **kwargs)
        analyze(trades, name)

    # Year by year for best filters
    print("\n--- Year-by-Year for Promising Filters ---")
    for name in ["ADX > 20", "ADX > 25", "BTC > EMA50 only"]:
        kwargs = dict(filters)[name] if isinstance(filters, list) else None
        # Find matching filter
        for fn, kw in filters:
            if fn == name: kwargs = kw; break
        print(f"\n  {name}:")
        for year in range(2021, 2027):
            yr = eth.loc[f'{year}-01-01':f'{year}-12-31']
            if len(yr) < 100: break
            yt = macd_backtest(yr, vol_mult=1.2, **kwargs)
            analyze(yt, f"  {year}")


if __name__ == "__main__":
    main()
