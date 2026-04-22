#!/usr/bin/env python3
"""Full analysis: SHORT side 4H ATR, combined scoring, new venue candidates."""
import pandas as pd
import numpy as np
import sys, os, glob
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')
from src.quant import indicators as ind

DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h'
SYMBOLS = ['SOLUSDT','BTCUSDT','ETHUSDT','AVAXUSDT','ARBUSDT','OPUSDT',
           'LINKUSDT','RENDERUSDT','NEARUSDT','AAVEUSDT','DOGEUSDT','LTCUSDT']
SHORT_SYMBOLS = ['ARBUSDT','OPUSDT','APTUSDT','AVAXUSDT','ETHUSDT','NEARUSDT','SUIUSDT']
ATR_PERIOD = 14
ATR_LONG_MULT = 2.0
ATR_SHORT_MULT = 1.5
SMA_PERIOD = 100

def load_4h(symbol):
    # Try multiple naming conventions — prioritize deep data
    if 'USDT' in symbol:
        base_sym = symbol.replace('USDT','')
        bases = [
            f'binance_{base_sym}_USDT_240m.parquet',  # deep data pattern
            f'binance_{symbol}_240m.parquet',
            f'binance_{base_sym}_USD_240m.parquet',
            f'binance_{symbol}_240m_resampled.parquet',
        ]
    else:
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
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
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
                trades.append(pnl)
                in_pos = False
            elif df['close'].iloc[i] < df['sma100'].iloc[i]:
                pnl = (df['close'].iloc[i]/entry_price - 1)*100
                trades.append(pnl)
                in_pos = False
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
                trades.append(pnl)
                in_pos = False
            elif df['close'].iloc[i] > df['sma100'].iloc[i]:
                pnl = (1 - df['close'].iloc[i]/entry_price)*100
                trades.append(pnl)
                in_pos = False
    return np.array(trades)

def stats(pnls, label=""):
    if len(pnls) == 0: return None
    pf = pnls[pnls>0].sum()/abs(pnls[pnls<0].sum()) if (pnls<0).any() else float('inf')
    wr = (pnls>0).mean()*100
    return {'n': len(pnls), 'pf': pf, 'wr': wr, 'avg': pnls.mean(), 'med': np.median(pnls), 'total': pnls.sum()}

def print_stats(s, prefix=""):
    if s is None: return
    print(f"{prefix}n={s['n']:>4d} PF={s['pf']:>6.2f} WR={s['wr']:>5.1f}% Avg={s['avg']:>+6.2f}% Med={s['med']:>+6.2f}% Total={s['total']:>+7.2f}%")

# Part 1: SHORT side
print("="*90)
print("PART 1: SHORT SIDE — 4H ATR (1.5x mult)")
print("="*90)
short_results = {}
all_short = []
for sym in SHORT_SYMBOLS:
    df = load_4h(sym)
    if df is None:
        print(f"  {sym}: NO DATA"); continue
    df = calc_indicators(df)
    if len(df) < 500: continue
    pnls = backtest_short(df)
    if len(pnls) == 0:
        print(f"  {sym}: 0 trades"); continue
    s = stats(pnls)
    short_results[sym] = s
    all_short.extend(pnls)
    print(f"  {sym:<12s}", end="")
    print_stats(s)

all_short = np.array(all_short)
if len(all_short) > 0:
    s = stats(all_short)
    print(f"\n  {'PORTFOLIO':<12s}", end="")
    print_stats(s)

# Part 2: Combined scoring
print("\n" + "="*90)
print("PART 2: COMBINED SCORING — LONG + SHORT per pair")
print("="*90)
combined_all = []
scoring = []
for sym in SYMBOLS:
    df = load_4h(sym)
    if df is None: continue
    df = calc_indicators(df)
    if len(df) < 500: continue
    
    l_pnls = backtest_long(df)
    s_pnls = backtest_short(df) if sym in SHORT_SYMBOLS else np.array([])
    
    l_s = stats(l_pnls)
    s_s = stats(s_pnls)
    
    combined = np.concatenate([l_pnls, s_pnls])
    c_s = stats(combined)
    
    has_short = sym in SHORT_SYMBOLS and len(s_pnls) > 0
    combined_all.extend(combined)
    
    scoring.append({
        'symbol': sym.replace('USDT',''),
        'l_n': l_s['n'] if l_s else 0, 'l_pf': l_s['pf'] if l_s else 0, 'l_wr': l_s['wr'] if l_s else 0, 'l_total': l_s['total'] if l_s else 0,
        's_n': s_s['n'] if s_s else 0, 's_pf': s_s['pf'] if s_s else 0, 's_wr': s_s['wr'] if s_s else 0, 's_total': s_s['total'] if s_s else 0,
        'c_n': c_s['n'] if c_s else 0, 'c_pf': c_s['pf'] if c_s else 0, 'c_total': c_s['total'] if c_s else 0,
        'has_short': has_short
    })

scoring_df = pd.DataFrame(scoring).sort_values('c_pf', ascending=False)
for _, r in scoring_df.iterrows():
    short_str = f" S: n={int(r.s_n):>3d} PF={r.s_pf:>5.2f}" if r.has_short else ""
    print(f"  {r.symbol:<6s} L: n={int(r.l_n):>3d} PF={r.l_pf:>5.2f} T={r.l_total:>+7.2f}%{short_str} | Combined: PF={r.c_pf:>5.2f} Total={r.c_total:>+7.2f}%")

combined_all = np.array(combined_all)
s = stats(combined_all)
print(f"\n  {'TOTAL':<6s}", end="")
print_stats(s)

# Part 3: Annualized return estimate
print("\n" + "="*90)
print("PART 3: ANNUALIZED RETURN ESTIMATE")
print("="*90)
# 4H bars: ~6 per day, ~2190 per year
for sym in SYMBOLS:
    df = load_4h(sym)
    if df is None: continue
    df = calc_indicators(df)
    if len(df) < 500: continue
    years = len(df) / 2190
    
    l_pnls = backtest_long(df)
    s_pnls = backtest_short(df) if sym in SHORT_SYMBOLS else np.array([])
    combined = np.concatenate([l_pnls, s_pnls])
    
    if len(combined) == 0: continue
    
    total_ret = combined.sum()
    ann_ret = total_ret / years
    trades_per_year = len(combined) / years
    
    name = sym.replace('USDT','')
    print(f"  {name:<6s} {ann_ret:>+8.1f}%/yr ({trades_per_year:.0f} trades/yr, {len(combined)} total over {years:.1f}yr)")

# Part 4: Check for additional 4h data (new venue candidates)
print("\n" + "="*90)
print("PART 4: AVAILABLE 4H DATA — NEW PAIR CANDIDATES")
print("="*90)
all_4h_files = glob.glob(os.path.join(DATA_DIR, 'binance_*240m.parquet')) + \
               glob.glob(os.path.join(DATA_DIR, 'binance_*4h.parquet'))
existing = set()
for f in all_4h_files:
    base = os.path.basename(f)
    sym = base.replace('binance_','').replace('_240m.parquet','').replace('_4h.parquet','')
    existing.add(sym)

known = set(SYMBOLS + SHORT_SYMBOLS)
new_candidates = existing - known
print(f"  Total 4h files: {len(existing)}")
print(f"  Already in strategy: {len(known)}")
print(f"  New candidates: {len(new_candidates)}")
for sym in sorted(new_candidates):
    df = load_4h(sym)
    if df is not None:
        print(f"    {sym}: {len(df)} bars")
