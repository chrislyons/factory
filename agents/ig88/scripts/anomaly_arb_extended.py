"""
ARB Extended Validation
========================
1. Test on different timeframes (1h, 2h, 8h)
2. Test on ARBUSDT perpetual futures
3. Bootstrap confidence intervals
4. Compare bounce characteristics across pairs
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02


def get_session(hour):
    if 0 <= hour < 8: return 'ASIA'
    elif 8 <= hour < 13: return 'LONDON'
    elif 13 <= hour < 16: return 'LONDON_NY'
    elif 16 <= hour < 21: return 'NY'
    else: return 'OFF_HOURS'


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    if 'session' in df.columns:
        session = df['session'].values
    else:
        session = np.zeros(len(c))
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session


def run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, filter_session=None):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < 20 and c[i] < bb_lower[i] and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * 0.75
            target_price = entry_price + atr[entry_bar] * 2.5
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l): break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * 0.75 / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * 2.5 / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("ARB EXTENDED VALIDATION")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# 1. Test different timeframes
print(f"\n{'=' * 120}")
print("TEST 1: DIFFERENT TIMEFRAMES")
print(f"{'=' * 120}")

for tf in ['60', '120', '480']:  # 1h, 2h, 8h
    path = DATA_DIR / f'binance_ARB_USDT_{tf}m.parquet'
    if path.exists():
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
        df['session'] = [(i * int(tf) // 60) % 24 for i in range(len(df))]
        df['session'] = df['session'].map(get_session)
        
        c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
        trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, ['ASIA', 'NY'])
        stats = calc_stats(trades)
        
        print(f"\nARB {tf}m:")
        print(f"  Bars: {len(df)}")
        print(f"  Trades: {stats['n']}")
        print(f"  Expectancy: {stats['exp']:.3f}%")
        print(f"  PF: {stats['pf']}")
        print(f"  WR: {stats['wr']}%")
    else:
        print(f"\nARB {tf}m: NO DATA")

# 2. Bootstrap confidence intervals
print(f"\n{'=' * 120}")
print("TEST 2: BOOTSTRAP CONFIDENCE INTERVALS")
print(f"{'=' * 120}")

df = pd.read_parquet(DATA_DIR / 'binance_ARB_USDT_240m.parquet')
if not isinstance(df.index, pd.DatetimeIndex):
    df = df.reset_index()
df['session'] = [(i * 4) % 24 for i in range(len(df))]
df['session'] = df['session'].map(get_session)
c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, ['ASIA', 'NY'])

print(f"\nSample size: {len(trades)} trades")
print(f"Observed: Exp={trades.mean()*100:.3f}%, PF={calc_stats(trades)['pf']}")

np.random.seed(42)
n_boot = 10000
boot_means = []
boot_pfs = []

for _ in range(n_boot):
    sample = np.random.choice(trades, size=len(trades), replace=True)
    boot_means.append(sample.mean() * 100)
    w = sample[sample > 0]
    ls = sample[sample <= 0]
    if len(ls) > 0 and ls.sum() != 0:
        boot_pfs.append(w.sum() / abs(ls.sum()))
    else:
        boot_pfs.append(999)

boot_means = np.array(boot_means)
boot_pfs = np.array([p for p in boot_pfs if p < 100])  # Filter out infinity

print(f"\nExpectancy Bootstrap ({n_boot} iterations):")
print(f"  Mean: {boot_means.mean():.3f}%")
print(f"  90% CI: [{np.percentile(boot_means, 5):.3f}%, {np.percentile(boot_means, 95):.3f}%]")
print(f"  95% CI: [{np.percentile(boot_means, 2.5):.3f}%, {np.percentile(boot_means, 97.5):.3f}%]")
print(f"  Prob > 0: {(boot_means > 0).mean()*100:.1f}%")

print(f"\nProfit Factor Bootstrap ({len(boot_pfs)} iterations):")
print(f"  Mean: {boot_pfs.mean():.2f}")
print(f"  90% CI: [{np.percentile(boot_pfs, 5):.2f}, {np.percentile(boot_pfs, 95):.2f}]")
print(f"  95% CI: [{np.percentile(boot_pfs, 2.5):.2f}, {np.percentile(boot_pfs, 97.5):.2f}]")
print(f"  Prob > 1.5: {(boot_pfs > 1.5).mean()*100:.1f}%")
print(f"  Prob > 2.0: {(boot_pfs > 2.0).mean()*100:.1f}%")

# 3. Compare bounce characteristics
print(f"\n{'=' * 120}")
print("TEST 3: BOUNCE CHARACTERISTICS COMPARISON")
print(f"{'=' * 120}")

for pair in ['ARB', 'AVAX', 'AAVE', 'SUI', 'ATOM', 'LINK']:
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        continue
    
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    # Find oversold bounces
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    # Count oversold events
    oversold = (rsi < 20) & (c < bb_lower)
    n_oversold = oversold.sum()
    
    # Measure bounce after oversold
    bounces = []
    for i in range(100, len(c) - 15):
        if oversold[i]:
            entry_price = c[i+2] if i+2 < len(c) else c[i]
            max_bounce = max(c[i+1:min(i+16, len(c))]) - entry_price
            bounces.append(max_bounce / entry_price * 100)
    
    bounces = np.array(bounces) if bounces else np.array([0])
    
    print(f"\n{pair}:")
    print(f"  Oversold events: {n_oversold}")
    print(f"  Avg bounce: {bounces.mean():.2f}%")
    print(f"  Median bounce: {np.median(bounces):.2f}%")
    print(f"  Bounce > 2.5%: {(bounces > 2.5).mean()*100:.1f}%")

# 4. ARB-specific: Check if edge is concentrated in specific periods
print(f"\n{'=' * 120}")
print("TEST 4: TEMPORAL CONCENTRATION CHECK")
print(f"{'=' * 120}")

df = pd.read_parquet(DATA_DIR / 'binance_ARB_USDT_240m.parquet')
if not isinstance(df.index, pd.DatetimeIndex):
    df = df.reset_index()
df['session'] = [(i * 4) % 24 for i in range(len(df))]
df['session'] = df['session'].map(get_session)
c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)

# Split by year
df['year'] = 'unknown'
if 'timestamp' in df.columns:
    df['year'] = pd.to_datetime(df['timestamp'], unit='s').dt.year
elif 'date' in df.columns:
    df['year'] = pd.to_datetime(df['date']).dt.year
elif isinstance(df.index, pd.DatetimeIndex):
    df['year'] = df.index.year

print(f"\nTrades by year:")
for year in sorted(df['year'].unique()):
    mask = df['year'] == year
    year_trades = run_mr(c[mask.values], o[mask.values], h[mask.values], l[mask.values],
                         rsi[mask.values], bb_lower[mask.values], atr[mask.values], 
                         vol_ratio[mask.values], ['ASIA', 'NY'])
    if len(year_trades) > 0:
        stats = calc_stats(year_trades)
        print(f"  {year}: N={stats['n']} Exp={stats['exp']:.2f}% PF={stats['pf']}")

# 5. Significance test: Is ARB's edge significantly better than other pairs?
print(f"\n{'=' * 120}")
print("TEST 5: IS ARB SIGNIFICANTLY BETTER?")
print(f"{'=' * 120}")

all_exp = {}
for pair in ['ARB', 'AVAX', 'AAVE', 'SUI', 'ATOM']:
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        continue
    
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    df['session'] = [(i * 4) % 24 for i in range(len(df))]
    df['session'] = df['session'].map(get_session)
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, ['ASIA', 'NY'])
    all_exp[pair] = trades

# Permutation test: ARB vs rest
arb_exp = all_exp['ARB'].mean()
rest_exp = np.concatenate([all_exp[p] for p in ['AVAX', 'AAVE', 'SUI', 'ATOM']]).mean()

print(f"\nARB mean expectancy: {arb_exp*100:.3f}%")
print(f"Rest mean expectancy: {rest_exp*100:.3f}%")
print(f"Difference: {(arb_exp - rest_exp)*100:.3f}%")

# Bootstrap comparison
np.random.seed(42)
n_perm = 10000
arb_samples = []
rest_samples = []

for _ in range(n_perm):
    arb_sample = np.random.choice(all_exp['ARB'], size=len(all_exp['ARB']), replace=True).mean()
    arb_samples.append(arb_sample)
    
    rest_all = np.concatenate([all_exp[p] for p in ['AVAX', 'AAVE', 'SUI', 'ATOM']])
    rest_sample = np.random.choice(rest_all, size=len(rest_all), replace=True).mean()
    rest_samples.append(rest_sample)

arb_samples = np.array(arb_samples)
rest_samples = np.array(rest_samples)

diffs = arb_samples - rest_samples
print(f"\nPermutation Test ({n_perm} iterations):")
print(f"  Mean difference: {diffs.mean()*100:.3f}%")
print(f"  95% CI: [{np.percentile(diffs, 2.5)*100:.3f}%, {np.percentile(diffs, 97.5)*100:.3f}%]")
print(f"  Prob ARB > Rest: {(diffs > 0).mean()*100:.1f}%")
print(f"  Prob difference > 2%: {(diffs > 0.02).mean()*100:.1f}%")
