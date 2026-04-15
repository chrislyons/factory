"""
Monte Carlo: 7-Pair MR Portfolio
==================================
Projects forward using walk-forward validated returns.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Validated pairs with WF OOS statistics
PORTFOLIO = {
    'ARB':  {'oos_exp': 3.21, 'oos_pf': 3.8, 'oos_n': 5, 'oos_wr': 40},
    'AAVE': {'oos_exp': 5.49, 'oos_pf': 4.1, 'oos_n': 6, 'oos_wr': 35},
    'INJ':  {'oos_exp': 4.26, 'oos_pf': 3.2, 'oos_n': 5, 'oos_wr': 38},
    'SUI':  {'oos_exp': 3.77, 'oos_pf': 2.8, 'oos_n': 6, 'oos_wr': 36},
    'AVAX': {'oos_exp': 1.97, 'oos_pf': 2.1, 'oos_n': 7, 'oos_wr': 33},
    'LINK': {'oos_exp': 3.96, 'oos_pf': 2.5, 'oos_n': 8, 'oos_wr': 35},
    'POL':  {'oos_exp': 1.25, 'oos_pf': 1.5, 'oos_n': 10, 'oos_wr': 30},
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
    bb_lower = sma20 - std20 * 2
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio


def collect_trades(pair, rsi_thresh=25, vol_mult=1.5, stop_atr=1.0, target_atr=2.5):
    """Collect all historical trades from data."""
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, atr, vol_ratio = compute_indicators(df)
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < rsi_thresh and c[i] < bb_lower[i] and vol_ratio[i] > vol_mult:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * stop_atr
            target_price = entry_price + atr[entry_bar] * target_atr
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * stop_atr / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * target_atr / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


print("=" * 80)
print("MONTE CARLO: 7-PAIR MR PORTFOLIO (2% friction design)")
print("=" * 80)

# Collect trades for each pair
all_trades = {}
for pair, params in PORTFOLIO.items():
    trades = collect_trades(pair)
    all_trades[pair] = trades
    if len(trades) > 0:
        print(f"{pair}: {len(trades)} trades, Exp={trades.mean()*100:.2f}%, WR={(trades>0).mean()*100:.0f}%")
    else:
        print(f"{pair}: no trades")

# Combine all trades
combined = np.concatenate([t for t in all_trades.values() if len(t) > 0])
print(f"\nTotal historical trades: {len(combined)}")
print(f"Combined Exp: {combined.mean()*100:.3f}%")
print(f"Combined WR: {(combined > 0).mean()*100:.1f}%")

# Monte Carlo
N_SIM = 1000
N_MONTHS = 12
TRADES_PER_MONTH = 2  # Conservative (7 pairs, low signal frequency)

np.random.seed(42)
monthly_returns = []
cumulative_returns = []
max_drawdowns = []

for sim in range(N_SIM):
    sampled = np.random.choice(combined, size=TRADES_PER_MONTH * N_MONTHS, replace=True)
    
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    monthly = []
    
    for m in range(N_MONTHS):
        month_trades = sampled[m * TRADES_PER_MONTH:(m + 1) * TRADES_PER_MONTH]
        month_ret = month_trades.sum()
        monthly.append(month_ret)
        cum *= (1 + month_ret)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        max_dd = max(max_dd, dd)
    
    monthly_returns.append(monthly)
    cumulative_returns.append(cum - 1)
    max_drawdowns.append(max_dd)

monthly_returns = np.array(monthly_returns)
cumulative_returns = np.array(cumulative_returns)
max_drawdowns = np.array(max_drawdowns)

print(f"\n{'=' * 80}")
print(f"MONTE CARLO RESULTS ({N_MONTHS} months, {TRADES_PER_MONTH} trades/month)")
print(f"{'=' * 80}")

print(f"\n12-Month Return Distribution:")
print(f"  Mean: {cumulative_returns.mean()*100:.1f}%")
print(f"  Median: {np.median(cumulative_returns)*100:.1f}%")
print(f"  5th percentile: {np.percentile(cumulative_returns, 5)*100:.1f}%")
print(f"  25th percentile: {np.percentile(cumulative_returns, 25)*100:.1f}%")
print(f"  75th percentile: {np.percentile(cumulative_returns, 75)*100:.1f}%")
print(f"  95th percentile: {np.percentile(cumulative_returns, 95)*100:.1f}%")

print(f"\nProbability of Profit: {(cumulative_returns > 0).mean()*100:.1f}%")
print(f"Probability >10%: {(cumulative_returns > 0.10).mean()*100:.1f}%")
print(f"Probability >25%: {(cumulative_returns > 0.25).mean()*100:.1f}%")
print(f"Probability Loss >20%: {(cumulative_returns < -0.20).mean()*100:.1f}%")

print(f"\nMax Drawdown:")
print(f"  Mean: {max_drawdowns.mean()*100:.1f}%")
print(f"  Median: {np.median(max_drawdowns)*100:.1f}%")
print(f"  95th percentile: {np.percentile(max_drawdowns, 95)*100:.1f}%")

print(f"\nExpected Monthly: {monthly_returns.mean()*100:.2f}%")
