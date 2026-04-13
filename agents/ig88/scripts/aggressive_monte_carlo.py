"""
Monte Carlo: Aggressive MR Portfolio (Optimized Parameters)
=============================================================
Uses pair-specific optimized parameters from deep_optimizer.py.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# OPTIMIZED PARAMETERS PER PAIR
PORTFOLIO = {
    'INJ':  {'rsi': 20, 'bb': 2.0, 'vol': 2.5, 'stop': 0.75, 'target': 2.5, 'bars': 25},
    'ARB':  {'rsi': 20, 'bb': 2.0, 'vol': 2.0, 'stop': 0.5, 'target': 2.5, 'bars': 15},
    'SUI':  {'rsi': 20, 'bb': 3.0, 'vol': 1.5, 'stop': 0.75, 'target': 4.0, 'bars': 15},
    'AAVE': {'rsi': 20, 'bb': 3.0, 'vol': 2.5, 'stop': 1.0, 'target': 5.0, 'bars': 15},
    'AVAX': {'rsi': 20, 'bb': 2.5, 'vol': 2.5, 'stop': 0.5, 'target': 5.0, 'bars': 15},
    'LINK': {'rsi': 20, 'bb': 2.5, 'vol': 2.5, 'stop': 1.0, 'target': 2.0, 'bars': 20},
    'POL':  {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 5.0, 'bars': 25},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


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
    bb_lower_2 = sma20 - std20 * 2
    bb_lower_25 = sma20 - std20 * 2.5
    bb_lower_3 = sma20 - std20 * 3
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower_2, bb_lower_25, bb_lower_3, atr, vol_ratio


def collect_trades(pair, params):
    """Collect all historical trades with optimized parameters."""
    df = load_data(pair)
    c, o, h, l, rsi, bb2, bb25, bb3, atr, vol_ratio = compute_indicators(df)
    
    # Select BB
    if params['bb'] == 2.5:
        bb_low = bb25
    elif params['bb'] == 3.0:
        bb_low = bb3
    else:
        bb_low = bb2
    
    trades = []
    for i in range(100, len(c) - params['bars']):
        if np.isnan(rsi[i]) or np.isnan(bb_low[i]) or np.isnan(atr[i]):
            continue
        
        if rsi[i] < params['rsi'] and c[i] < bb_low[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + 2
            if entry_bar >= len(c) - params['bars']:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


print("=" * 100)
print("MONTE CARLO: AGGRESSIVE MR PORTFOLIO (2% friction, optimized params)")
print("=" * 100)

# Collect trades
all_trades = {}
for pair, params in PORTFOLIO.items():
    trades = collect_trades(pair, params)
    all_trades[pair] = trades
    if len(trades) > 0:
        w = trades[trades > 0]
        l = trades[trades <= 0]
        pf = w.sum() / abs(l.sum()) if len(l) > 0 else 999
        print(f"{pair:<8} n={len(trades):<4} Exp={trades.mean()*100:>6.2f}%  "
              f"WR={(trades>0).mean()*100:>5.1f}%  PF={pf:>6.2f}  "
              f"AvgWin={w.mean()*100 if len(w)>0 else 0:>5.1f}%  AvgLoss={abs(l.mean())*100 if len(l)>0 else 0:>5.1f}%")
    else:
        print(f"{pair:<8} no trades")

# Combine
combined = np.concatenate([t for t in all_trades.values() if len(t) > 0])
w = combined[combined > 0]
l = combined[combined <= 0]

print(f"\n{'=' * 100}")
print("PORTFOLIO TOTALS")
print(f"{'=' * 100}")
print(f"Total trades: {len(combined)}")
print(f"Expectancy: {combined.mean()*100:.3f}%")
print(f"Win Rate: {(combined > 0).mean()*100:.1f}%")
print(f"Profit Factor: {w.sum()/abs(l.sum()):.2f}")
print(f"Avg Win: {w.mean()*100:.2f}%")
print(f"Avg Loss: {abs(l.mean())*100:.2f}%")

# Monte Carlo
N_SIM = 10000
N_MONTHS = 12
TRADES_PER_MONTH = 7  # ~1 per pair per month

np.random.seed(42)
results = []

for _ in range(N_SIM):
    sampled = np.random.choice(combined, size=TRADES_PER_MONTH * N_MONTHS, replace=True)
    total = sampled.sum()
    results.append(total)

results = np.array(results)

print(f"\n{'=' * 100}")
print(f"MONTE CARLO ({N_SIM} simulations, {N_MONTHS} months, {TRADES_PER_MONTH} trades/month)")
print(f"{'=' * 100}")
print(f"Mean return: {results.mean()*100:.1f}%")
print(f"Median return: {np.median(results)*100:.1f}%")
print(f"Std Dev: {results.std()*100:.1f}%")
print(f"5th percentile: {np.percentile(results, 5)*100:.1f}%")
print(f"25th percentile: {np.percentile(results, 25)*100:.1f}%")
print(f"75th percentile: {np.percentile(results, 75)*100:.1f}%")
print(f"95th percentile: {np.percentile(results, 95)*100:.1f}%")
print(f"\nProbability of Profit: {(results > 0).mean()*100:.1f}%")
print(f"Probability >25%: {(results > 0.25).mean()*100:.1f}%")
print(f"Probability >50%: {(results > 0.50).mean()*100:.1f}%")
print(f"Probability >100%: {(results > 1.0).mean()*100:.1f}%")
print(f"Probability Loss >20%: {(results < -0.20).mean()*100:.1f}%")

# Position sizing scenarios
print(f"\n{'=' * 100}")
print("POSITION SIZING SCENARIOS")
print(f"{'=' * 100}")

for pct in [1, 2, 5, 10]:
    scaled = results * pct
    print(f"\n{pct}% position size (base $10K = ${pct*100}):")
    print(f"  Mean 12mo: ${scaled.mean()*10000 + 10000:,.0f}")
    print(f"  Median: ${np.median(scaled)*10000 + 10000:,.0f}")
    print(f"  5th pctile: ${np.percentile(scaled, 5)*10000 + 10000:,.0f}")
    print(f"  95th pctile: ${np.percentile(scaled, 95)*10000 + 10000:,.0f}")
    print(f"  Prob loss >20%: {(scaled < -0.20).mean()*100:.1f}%")
