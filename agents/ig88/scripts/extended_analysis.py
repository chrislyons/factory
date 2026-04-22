#!/usr/bin/env python3
"""Extended analysis: test all deep-data pairs + new candidates."""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')
from src.quant import indicators as ind

DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h'
ATR_PERIOD = 14
ATR_LONG_MULT = 2.0
ATR_SHORT_MULT = 1.5
SMA_PERIOD = 100

# All pairs with deep data (>2000 bars) + interesting new ones
PAIRS = [
    'SOL_USDT', 'AVAX_USDT', 'ETH_USDT', 'LINK_USDT', 'NEAR_USDT',
    'ARB_USDT', 'OP_USDT', 'SUI_USDT', 'APT_USDT', 'AAVE_USDT',
    'INJ_USDT', 'ATOM_USDT', 'POL_USDT', 'UNI_USDT', 'BTC_USD',
]

SHORT_CANDIDATES = ['ARB_USDT','OP_USDT','APT_USDT','AVAX_USDT','ETH_USDT',
                     'NEAR_USDT','SUI_USDT','INJ_USDT','ATOM_USDT','UNI_USDT']

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

def calc_indicators(df):
    df = df.copy()
    h = df['high'].values; l = df['low'].values; c = df['close'].values
    df['atr'] = ind.atr(h, l, c, ATR_PERIOD)
    df['sma100'] = ind.sma(c, SMA_PERIOD)
    df['rsi'] = ind.rsi(c, 14)
    df['macd_hist'] = ind.macd(c).histogram
    return df.dropna()

def backtest_long(df, mult=ATR_LONG_MULT):
    trades = []
    in_pos = False
    entry_price = entry_stop = 0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] <= df['sma100'].iloc[i-1] and df['close'].iloc[i] > df['sma100'].iloc[i]:
                wait = df['close'].iloc[i:i+2]
                if len(wait) < 2: continue
                if wait.iloc[1] > df['sma100'].iloc[i] * 1.005:
                    entry_price = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    entry_stop = entry_price - mult * df['atr'].iloc[i]
                    in_pos = True
        else:
            if df['low'].iloc[i] <= entry_stop:
                pnl = (entry_stop/entry_price - 1)*100
                trades.append(pnl); in_pos = False
            elif df['close'].iloc[i] < df['sma100'].iloc[i]:
                pnl = (df['close'].iloc[i]/entry_price - 1)*100
                trades.append(pnl); in_pos = False
    return np.array(trades)

def backtest_short(df, mult=ATR_SHORT_MULT):
    trades = []
    in_pos = False
    entry_price = entry_stop = 0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] >= df['sma100'].iloc[i-1] and df['close'].iloc[i] < df['sma100'].iloc[i]:
                wait = df['close'].iloc[i:i+2]
                if len(wait) < 2: continue
                if wait.iloc[1] < df['sma100'].iloc[i] * 0.995:
                    entry_price = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    entry_stop = entry_price + mult * df['atr'].iloc[i]
                    in_pos = True
        else:
            if df['high'].iloc[i] >= entry_stop:
                pnl = (1 - entry_stop/entry_price)*100
                trades.append(pnl); in_pos = False
            elif df['close'].iloc[i] > df['sma100'].iloc[i]:
                pnl = (1 - df['close'].iloc[i]/entry_price)*100
                trades.append(pnl); in_pos = False
    return np.array(trades)

def pstats(pnls):
    if len(pnls) == 0: return None
    pf = pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()) if (pnls<0).any() else float('inf')
    wr = (pnls>0).mean()*100
    return {'n':len(pnls),'pf':pf,'wr':wr,'avg':pnls.mean(),'med':np.median(pnls),'total':pnls.sum()}

def walk_forward(df, test_fn, n_splits=3):
    """Simple walk-forward: train on first portion, test on next."""
    n = len(df)
    split_size = n // (n_splits + 1)
    oos_results = []
    for k in range(n_splits):
        train_end = split_size * (k + 1)
        test_start = train_end
        test_end = min(train_end + split_size, n)
        test_df = df.iloc[test_start:test_end]
        if len(test_df) < 200: continue
        pnls = test_fn(test_df)
        if len(pnls) > 0:
            oos_results.extend(pnls)
    return np.array(oos_results)

print("="*100)
print("EXTENDED ANALYSIS — All Deep-Data Pairs (4H ATR)")
print("="*100)

results = []
all_long = []
all_short = []
all_combined = []

for sym in PAIRS:
    df = load_4h(sym)
    if df is None or len(df) < 2000:
        continue
    df = calc_indicators(df)
    if len(df) < 500:
        continue
    
    years = len(df) / (6*365)
    l_pnls = backtest_long(df)
    l_s = pstats(l_pnls)
    
    s_pnls = backtest_short(df) if sym in SHORT_CANDIDATES else np.array([])
    s_s = pstats(s_pnls)
    
    combined = np.concatenate([l_pnls, s_pnls])
    c_s = pstats(combined)
    
    name = sym.replace('_USDT','').replace('_USD','')
    
    l_ann = l_s['total']/years if l_s else 0
    s_ann = s_s['total']/years if s_s else 0
    
    all_long.extend(l_pnls)
    all_short.extend(s_pnls)
    all_combined.extend(combined)
    
    l_str = f"L:{l_s['n']:>4d} PF={l_s['pf']:>5.2f} WR={l_s['wr']:>4.1f}% +{l_ann:>6.1f}%/yr" if l_s else "L: 0"
    s_str = f"S:{s_s['n']:>4d} PF={s_s['pf']:>5.2f} WR={s_s['wr']:>4.1f}% +{s_ann:>6.1f}%/yr" if s_s and s_s['n']>0 else ""
    
    print(f"  {name:<6s} ({len(df):>5d} bars, {years:.1f}yr)  {l_str}  {s_str}  Combined:{c_s['total']:>+8.1f}%")
    
    results.append({'sym':name, 'bars':len(df), 'years':years,
                    'l_n':l_s['n'] if l_s else 0, 'l_pf':l_s['pf'] if l_s else 0, 'l_ann':l_ann,
                    's_n':s_s['n'] if s_s else 0, 's_pf':s_s['pf'] if s_s else 0, 's_ann':s_ann,
                    'c_total':c_s['total'] if c_s else 0})

# Portfolio summary
print(f"\n  {'PORTFOLIO':<6s} L: n={len(all_long)} PF={pstats(np.array(all_long))['pf']:.2f}  S: n={len(all_short)} PF={pstats(np.array(all_short))['pf'] if all_short else 0:.2f}  Combined: {pstats(np.array(all_combined))['total']:.1f}%")

# Walk-forward validation for top performers
print("\n" + "="*100)
print("WALK-FORWARD VALIDATION — Top LONG Performers")
print("="*100)

for sym in ['SOL_USDT','AVAX_USDT','NEAR_USDT','LINK_USDT','ETH_USDT']:
    df = load_4h(sym)
    if df is None: continue
    df = calc_indicators(df)
    
    # In-sample
    is_pnls = backtest_long(df)
    is_s = pstats(is_pnls)
    
    # Walk-forward OOS
    oos_pnls = walk_forward(df, backtest_long, n_splits=3)
    oos_s = pstats(oos_pnls)
    
    name = sym.replace('_USDT','')
    deg = (1 - oos_s['pf']/is_s['pf'])*100 if is_s and oos_s else 0
    print(f"  {name:<6s} IS: n={is_s['n']:>4d} PF={is_s['pf']:>5.2f}  OOS: n={oos_s['n']:>4d} PF={oos_s['pf']:>5.2f}  Degradation: {deg:>+.1f}%")

# SHORT walk-forward
print("\n" + "="*100)
print("WALK-FORWARD VALIDATION — SHORT Candidates")
print("="*100)

for sym in SHORT_CANDIDATES:
    df = load_4h(sym)
    if df is None or len(df) < 2000: continue
    df = calc_indicators(df)
    
    is_pnls = backtest_short(df)
    is_s = pstats(is_pnls)
    if is_s is None or is_s['n'] < 20: continue
    
    oos_pnls = walk_forward(df, backtest_short, n_splits=3)
    oos_s = pstats(oos_pnls)
    if oos_s is None: continue
    
    name = sym.replace('_USDT','')
    deg = (1 - oos_s['pf']/is_s['pf'])*100
    print(f"  {name:<6s} IS: n={is_s['n']:>4d} PF={is_s['pf']:>5.2f}  OOS: n={oos_s['n']:>4d} PF={oos_s['pf']:>5.2f}  Degradation: {deg:>+.1f}%")

# Venue friction analysis
print("\n" + "="*100)
print("VENUE FRICTION ANALYSIS")
print("="*100)
print("  Kraken spot: ~0.26% RT (0.13% maker/taker)")
print("  Jupiter perps: ~0.14% RT (0.07% avg)")
print("  Binance futures: ~0.08% RT (0.04% maker/taker)")
print("")
for cost_bps in [8, 14, 26]:
    cost = cost_bps / 100  # as %
    adj_pf = {}
    for sym in ['SOL_USDT','AVAX_USDT','NEAR_USDT','LINK_USDT','ETH_USDT']:
        df = load_4h(sym)
        if df is None: continue
        df = calc_indicators(df)
        pnls = backtest_long(df)
        if len(pnls) == 0: continue
        adj = pnls - cost  # subtract RT cost from each trade
        pf = adj[adj>0].sum()/abs(adj[adj<0].sum()) if (adj<0).any() else float('inf')
        name = sym.replace('_USDT','')
        adj_pf[name] = pf
    print(f"  {cost_bps:>3d} bps RT: " + " | ".join(f"{k}={v:.2f}" for k,v in adj_pf.items()))
