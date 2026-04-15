"""
Monte Carlo Simulation: SUI + OP Portfolio
============================================
Simulates 1000 possible futures to understand:
- Expected P&L range (confidence intervals)
- Probability of loss
- Max drawdown distribution
- Time to breakeven
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133
N_SIMULATIONS = 1000
N_MONTHS = 12
TRADING_DAYS_PER_MONTH = 20

PAIRS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.75'},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.5'},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_l = sma20 - std20 * 1.5
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    return c, o, h, l, rsi, bb_l, vol_ratio, atr


def get_stop_distance(stop_type, entry_price, atr_value):
    if stop_type == 'fixed_0.5':
        return entry_price * 0.005
    elif stop_type == 'fixed_0.75':
        return entry_price * 0.0075
    return entry_price * 0.005


def collect_trades(pair, params):
    """Collect all historical trades."""
    df = load_data(pair)
    c, o, h, l, rsi, bb_l, vol_ratio, atr = compute_indicators(df)
    
    trades = []
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_dist = get_stop_distance(params['stop'], entry_price, atr[entry_bar])
            stop_price = entry_price - stop_dist
            target_price = entry_price * (1 + params['target'])
            for j in range(1, 16):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop_dist/entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


print("=" * 90)
print(f"MONTE CARLO SIMULATION: {N_SIMULATIONS} runs x {N_MONTHS} months")
print("=" * 90)

# Collect trades for each pair
all_trades = {}
for pair, params in PAIRS.items():
    trades = collect_trades(pair, params)
    all_trades[pair] = trades
    print(f"\n{pair}: {len(trades)} historical trades")
    print(f"  Mean: {trades.mean()*100:.3f}%")
    print(f"  Std: {trades.std()*100:.3f}%")
    print(f"  Win rate: {(trades > 0).mean()*100:.1f}%")

# Combined trade pool
combined = np.concatenate([all_trades['SUI'], all_trades['OP']])
np.random.shuffle(combined)

print(f"\nCombined pool: {len(combined)} trades")

# Monte Carlo simulation
# Assume 3 trades per month (conservative estimate)
trades_per_month = 3
trades_per_sim = trades_per_month * N_MONTHS

monthly_returns = []
cumulative_returns = []
max_drawdowns = []

np.random.seed(42)

for sim in range(N_SIMULATIONS):
    # Resample trades with replacement
    sampled = np.random.choice(combined, size=trades_per_sim, replace=True)
    
    # Calculate monthly returns
    monthly = []
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    
    for m in range(N_MONTHS):
        month_trades = sampled[m * trades_per_month:(m + 1) * trades_per_month]
        month_return = month_trades.sum()  # Sum of trade returns
        monthly.append(month_return)
        cum *= (1 + month_return)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        max_dd = max(max_dd, dd)
    
    monthly_returns.append(monthly)
    cumulative_returns.append(cum - 1)  # Total return
    max_drawdowns.append(max_dd)

monthly_returns = np.array(monthly_returns)
cumulative_returns = np.array(cumulative_returns)
max_drawdowns = np.array(max_drawdowns)

# Statistics
print(f"\n{'=' * 90}")
print("MONTE CARLO RESULTS (12-month horizon, 3 trades/month)")
print(f"{'=' * 90}")

print(f"\nTotal Return Distribution:")
print(f"  Mean: {cumulative_returns.mean()*100:.1f}%")
print(f"  Median: {np.median(cumulative_returns)*100:.1f}%")
print(f"  Std Dev: {cumulative_returns.std()*100:.1f}%")
print(f"  5th percentile: {np.percentile(cumulative_returns, 5)*100:.1f}%")
print(f"  25th percentile: {np.percentile(cumulative_returns, 25)*100:.1f}%")
print(f"  75th percentile: {np.percentile(cumulative_returns, 75)*100:.1f}%")
print(f"  95th percentile: {np.percentile(cumulative_returns, 95)*100:.1f}%")

print(f"\nProbability of Profit: {(cumulative_returns > 0).mean()*100:.1f}%")
print(f"Probability of >10%: {(cumulative_returns > 0.10).mean()*100:.1f}%")
print(f"Probability of >25%: {(cumulative_returns > 0.25).mean()*100:.1f}%")
print(f"Probability of >50%: {(cumulative_returns > 0.50).mean()*100:.1f}%")
print(f"Probability of Loss >20%: {(cumulative_returns < -0.20).mean()*100:.1f}%")

print(f"\nMax Drawdown Distribution:")
print(f"  Mean: {max_drawdowns.mean()*100:.1f}%")
print(f"  Median: {np.median(max_drawdowns)*100:.1f}%")
print(f"  95th percentile: {np.percentile(max_drawdowns, 95)*100:.1f}%")
print(f"  Worst case (99th): {np.percentile(max_drawdowns, 99)*100:.1f}%")

# Monthly average
avg_monthly = monthly_returns.mean(axis=0)
print(f"\nExpected Monthly Returns:")
for i, m in enumerate(avg_monthly):
    print(f"  Month {i+1}: {m*100:.2f}%")
print(f"  Average: {avg_monthly.mean()*100:.2f}%/month")
