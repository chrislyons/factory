#!/usr/bin/env python3
"""Strategy Scorecard: definitive ranking with WF validation, annualized returns,
capital allocation, and new opportunity exploration."""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')
from src.quant import indicators as ind

DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h'
ATR_PERIOD = 14; SMA_PERIOD = 100
LONG_MULT = 2.0; SHORT_MULT = 1.5

DEEP_PAIRS = [
    'SOL_USDT','AVAX_USDT','ETH_USDT','LINK_USDT','NEAR_USDT',
    'ARB_USDT','OP_USDT','SUI_USDT','AAVE_USDT','INJ_USDT',
    'ATOM_USDT','POL_USDT','UNI_USDT','BTC_USD',
]
SHORT_OK = ['ARB_USDT','OP_USDT','AVAX_USDT','ETH_USDT','NEAR_USDT',
            'SUI_USDT','INJ_USDT','ATOM_USDT','UNI_USDT']

def load_4h(symbol):
    bases = [f'binance_{symbol}_240m.parquet', f'binance_{symbol}_240m_resampled.parquet']
    for fname in bases:
        fp = os.path.join(DATA_DIR, fname)
        if os.path.exists(fp):
            df = pd.read_parquet(fp)
            if 'time' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df['time'], unit='s')
            return df[['open','high','low','close','volume']].sort_index()
    return None

def calc(df):
    df = df.copy()
    h=df['high'].values; l=df['low'].values; c=df['close'].values
    df['atr'] = ind.atr(h,l,c,ATR_PERIOD)
    df['sma100'] = ind.sma(c,SMA_PERIOD)
    return df.dropna()

def bt_long(df, mult=LONG_MULT):
    trades = []; in_pos = False; ep = es = 0.0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] <= df['sma100'].iloc[i-1] and df['close'].iloc[i] > df['sma100'].iloc[i]:
                w = df['close'].iloc[i:i+2]
                if len(w) < 2: continue
                if w.iloc[1] > df['sma100'].iloc[i] * 1.005:
                    ep = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    es = ep - mult * df['atr'].iloc[i]; in_pos = True
        else:
            if df['low'].iloc[i] <= es:
                trades.append((es/ep-1)*100); in_pos = False
            elif df['close'].iloc[i] < df['sma100'].iloc[i]:
                trades.append((df['close'].iloc[i]/ep-1)*100); in_pos = False
    return np.array(trades)

def bt_short(df, mult=SHORT_MULT):
    trades = []; in_pos = False; ep = es = 0.0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] >= df['sma100'].iloc[i-1] and df['close'].iloc[i] < df['sma100'].iloc[i]:
                w = df['close'].iloc[i:i+2]
                if len(w) < 2: continue
                if w.iloc[1] < df['sma100'].iloc[i] * 0.995:
                    ep = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    es = ep + mult * df['atr'].iloc[i]; in_pos = True
        else:
            if df['high'].iloc[i] >= es:
                trades.append((1-es/ep)*100); in_pos = False
            elif df['close'].iloc[i] > df['sma100'].iloc[i]:
                trades.append((1-df['close'].iloc[i]/ep)*100); in_pos = False
    return np.array(trades)

def ps(pnls):
    if len(pnls)==0: return None
    pf = pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()) if (pnls<0).any() else 999.0
    wr = (pnls>0).mean()*100
    return dict(n=len(pnls), pf=pf, wr=wr, avg=pnls.mean(), med=np.median(pnls), total=pnls.sum())

def wf(df, fn, splits=3):
    n=len(df); sz=n//(splits+1); oos=[]
    for k in range(splits):
        t = df.iloc[sz*(k+1):min(sz*(k+2),n)]
        if len(t)<200: continue
        p = fn(t)
        if len(p)>0: oos.extend(p)
    return np.array(oos)

def sharpe(pnls):
    if len(pnls)<2: return 0
    return pnls.mean()/(pnls.std()+1e-10) * np.sqrt(len(pnls)/5.0)  # annualized rough

# Main analysis
print("="*110)
print("STRATEGY SCORECARD — 4H ATR Breakout (Walk-Forward Validated)")
print("="*110)

scorecard = []
for sym in DEEP_PAIRS:
    df = load_4h(sym)
    if df is None or len(df)<2000: continue
    df = calc(df)
    years = len(df)/(6*365)
    name = sym.replace('_USDT','').replace('_USD','')
    
    # LONG
    l_is = ps(bt_long(df))
    l_oos = ps(wf(df, bt_long))
    if l_is and l_oos and l_oos['n']>=20:
        l_wf_ratio = l_oos['pf']/l_is['pf']
        l_ann = l_is['total']/years
        l_sharpe = sharpe(bt_long(df))
        scorecard.append({
            'pair':name, 'side':'LONG', 'years':years,
            'is_n':l_is['n'], 'is_pf':l_is['pf'], 'is_wr':l_is['wr'],
            'oos_n':l_oos['n'], 'oos_pf':l_oos['pf'], 'oos_wr':l_oos['wr'],
            'wf_ratio':l_wf_ratio, 'ann_ret':l_ann, 'sharpe':l_sharpe,
            'robust': l_wf_ratio > 0.7 and l_oos['pf'] > 1.0
        })
    
    # SHORT
    if sym in SHORT_OK:
        s_is = ps(bt_short(df))
        s_oos = ps(wf(df, bt_short))
        if s_is and s_oos and s_oos['n']>=15:
            s_wf_ratio = s_oos['pf']/s_is['pf']
            s_ann = s_is['total']/years
            s_sharpe = sharpe(bt_short(df))
            scorecard.append({
                'pair':name, 'side':'SHORT', 'years':years,
                'is_n':s_is['n'], 'is_pf':s_is['pf'], 'is_wr':s_is['wr'],
                'oos_n':s_oos['n'], 'oos_pf':s_oos['pf'], 'oos_wr':s_oos['wr'],
                'wf_ratio':s_wf_ratio, 'ann_ret':s_ann, 'sharpe':s_sharpe,
                'robust': s_wf_ratio > 0.7 and s_oos['pf'] > 1.0
            })

sc = pd.DataFrame(scorecard).sort_values('ann_ret', ascending=False)

print(f"\n{'Pair':<6s} {'Side':<6s} {'Yrs':>4s} {'IS n':>5s} {'IS PF':>6s} {'OOS n':>5s} {'OOS PF':>6s} {'WF%':>6s} {'Ann%':>8s} {'Sharpe':>7s} {'★':>2s}")
print("-"*95)
for _, r in sc.iterrows():
    star = "★" if r['robust'] else ""
    print(f"{r['pair']:<6s} {r['side']:<6s} {r['years']:>4.1f} {int(r.is_n):>5d} {r.is_pf:>6.2f} {int(r.oos_n):>5d} {r.oos_pf:>6.2f} {r.wf_ratio:>5.1%} {r.ann_ret:>+7.1f}% {r.sharpe:>6.2f} {star:>2s}")

# Robust strategies only
robust = sc[sc['robust']].sort_values('ann_ret', ascending=False)
print(f"\n{'='*95}")
print(f"ROBUST STRATEGIES (WF ratio > 70%, OOS PF > 1.0)")
print(f"{'='*95}")
total_ann = 0
for _, r in robust.iterrows():
    print(f"  {r['pair']:<6s} {r['side']:<6s} OOS PF={r.oos_pf:.2f}  Ann={r.ann_ret:>+7.1f}%  Sharpe={r.sharpe:.2f}")
    total_ann += r['ann_ret']
print(f"\n  COMBINED ANNUAL RETURN (if equal-weighted): {total_ann:>+7.1f}%/yr")

# Optimal allocation (Kelly-fraction based on PF)
print(f"\n{'='*95}")
print("CAPITAL ALLOCATION (Kelly-scaled, 25% Kelly fraction)")
print(f"{'='*95}")
kelly_total = 0
kelly_weights = []
for _, r in robust.iterrows():
    # Kelly = (pf - 1) / (avg_win/avg_loss - 1) simplified to (pf-1)/pf
    kelly = max(0, (r['oos_pf'] - 1) / r['oos_pf']) * 0.25  # quarter Kelly
    kelly_weights.append((r['pair'], r['side'], kelly, r['ann_ret']))
    kelly_total += kelly

if kelly_total > 0:
    for pair, side, k, ann in kelly_weights:
        weight = k / kelly_total
        adj_ann = ann * weight
        print(f"  {pair:<6s} {side:<6s} Kelly={k:.3f} Weight={weight:>5.1%} Contrib={adj_ann:>+7.1f}%/yr")

# Venue selection
print(f"\n{'='*95}")
print("OPTIMAL VENUE PER STRATEGY")
print(f"{'='*95}")
print("  LONG strategies: Binance Futures (0.08% RT) > Jupiter Perps (0.14% RT) > Kraken Spot (0.26% RT)")
print("  SHORT strategies: Binance Futures or Jupiter Perps (short-capable)")
print("")
for _, r in robust.iterrows():
    if r['side'] == 'LONG':
        print(f"  {r['pair']:<6s} LONG  → Binance Futures (PF adj: {r['oos_pf']*0.99:.2f}) or Jupiter perps")
    else:
        print(f"  {r['pair']:<6s} SHORT → Jupiter Perps (PF adj: {r['oos_pf']*0.99:.2f}) or Binance Futures")
