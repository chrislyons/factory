"""
ARB Anomaly Investigation
==========================
Why is ARB's PF 5.60 and WR 71% when all other pairs are 50% or lower?
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02


def get_session(hour):
    if 0 <= hour < 8: return 'ASIA'
    elif 8 <= hour < 13: return 'LONDON'
    elif 13 <= hour < 16: return 'LONDON_NY'
    elif 16 <= hour < 21: return 'NY'
    else: return 'OFF_HOURS'


def load_data(pair):
    df = pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    if isinstance(df.index, pd.DatetimeIndex):
        df['session'] = df.index.hour.map(get_session)
    else:
        df = df.reset_index()
        df['session'] = [(i * 4) % 24 for i in range(len(df))]
        df['session'] = df['session'].map(get_session)
    return df


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
    
    session = df['session'].values
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session


def run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, filter_session=None):
    """Return detailed trade info."""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if filter_session and session[i] not in filter_session:
            continue
        if rsi[i] < 20 and c[i] < bb_lower[i] and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * 0.75
            target_price = entry_price + atr[entry_bar] * 2.5
            
            result = None
            exit_bar = None
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    result = -atr[entry_bar] * 0.75 / entry_price - FRICTION
                    exit_bar = bar
                    break
                if h[bar] >= target_price:
                    result = atr[entry_bar] * 2.5 / entry_price - FRICTION
                    exit_bar = bar
                    break
            
            if result is None:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                result = (exit_price - entry_price) / entry_price - FRICTION
                exit_bar = entry_bar + 15
            
            trades.append({
                'signal_bar': i,
                'entry_bar': entry_bar,
                'exit_bar': exit_bar,
                'entry_price': entry_price,
                'stop': stop_price,
                'target': target_price,
                'rsi': rsi[i],
                'bb_dist': (c[i] - bb_lower[i]) / c[i] * 100,
                'vol_ratio': vol_ratio[i],
                'atr_pct': atr[entry_bar] / entry_price * 100,
                'session': session[i],
                'result': result,
                'exit_type': 'stop' if l[exit_bar] <= stop_price else ('target' if h[exit_bar] >= target_price else 'time'),
            })
    
    return trades


print("=" * 120)
print("ARB ANOMALY INVESTIGATION")
print("=" * 120)

# Load ARB data
df = load_data('ARB')
c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)

print(f"\nDATA SUMMARY:")
print(f"  Total bars: {len(df)}")
print(f"  Date range: {len(df) * 4 / 24:.0f} days")
print(f"  Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")

# Get all trades with ASIA+NY filter
trades = run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, ['ASIA', 'NY'])

print(f"\nTRADE COUNT:")
print(f"  ASIA+NY trades: {len(trades)}")
print(f"  Without filter: {len(run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, None))}")

# Trade-by-trade breakdown
print(f"\nTRADE-BY-TRADE BREAKDOWN:")
print(f"{'#':<4} {'Rsi':<6} {'BB%':<8} {'Vol':<6} {'ATR%':<7} {'Sess':<8} {'Exit':<8} {'PnL%':<8} {'Cum%'}")
print("-" * 75)

cumulative = 0
for i, t in enumerate(trades):
    cumulative += t['result']
    print(f"{i+1:<4} {t['rsi']:<6.1f} {t['bb_dist']:<7.2f} {t['vol_ratio']:<5.2f}x {t['atr_pct']:<6.2f} {t['session']:<8} {t['exit_type']:<8} {t['result']*100:>+6.2f}%  {cumulative*100:>+6.2f}%")

# Trade statistics
results = np.array([t['result'] for t in trades])
wins = results[results > 0]
losses = results[results <= 0]

print(f"\nTRADE STATISTICS:")
print(f"  Total trades: {len(trades)}")
print(f"  Wins: {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
print(f"  Losses: {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
print(f"  Avg win: {wins.mean()*100:.2f}%")
print(f"  Avg loss: {losses.mean()*100:.2f}%")
print(f"  Total PnL: {results.sum()*100:.2f}%")
print(f"  Expectancy: {results.mean()*100:.3f}%")
print(f"  PF: {wins.sum() / abs(losses.sum()):.2f}")

# Exit type breakdown
print(f"\nEXIT TYPE BREAKDOWN:")
for exit_type in ['stop', 'target', 'time']:
    type_trades = [t for t in trades if t['exit_type'] == exit_type]
    if type_trades:
        type_results = np.array([t['result'] for t in type_trades])
        print(f"  {exit_type}: {len(type_trades)} trades, {type_results.mean()*100:.2f}% avg")

# Compare to same logic WITHOUT session filter
print(f"\n{'=' * 120}")
print("COMPARISON: With vs Without Session Filter")
print(f"{'=' * 120}")

all_trades = run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, None)
all_results = np.array([t['result'] for t in all_trades])
asia_ny_results = np.array([t['result'] for t in trades])

print(f"\nWithout filter:")
print(f"  Trades: {len(all_trades)}")
print(f"  WR: {(all_results > 0).mean()*100:.1f}%")
print(f"  PF: {all_results[all_results > 0].sum() / abs(all_results[all_results <= 0].sum()):.2f}")
print(f"  Exp: {all_results.mean()*100:.2f}%")

print(f"\nWith ASIA+NY filter:")
print(f"  Trades: {len(trades)}")
print(f"  WR: {(asia_ny_results > 0).mean()*100:.1f}%")
print(f"  PF: {asia_ny_results[asia_ny_results > 0].sum() / abs(asia_ny_results[asia_ny_results <= 0].sum()):.2f}")
print(f"  Exp: {asia_ny_results.mean()*100:.3f}%")

# Check if ARB's data is different from other pairs
print(f"\n{'=' * 120}")
print("DATA QUALITY CHECK: ARB vs Other Pairs")
print(f"{'=' * 120}")

for pair in ['ARB', 'AVAX', 'AAVE', 'SUI', 'ATOM']:
    try:
        df_p = load_data(pair)
    except:
        continue
    
    # Compute returns
    returns = df_p['close'].pct_change().dropna()
    
    print(f"\n{pair}:")
    print(f"  Bars: {len(df_p)}")
    print(f"  Mean 4h return: {returns.mean()*100:.4f}%")
    print(f"  Vol: {returns.std()*100:.2f}%")
    print(f"  Max drawdown: {(df_p['close'] / df_p['close'].cummax() - 1).min()*100:.1f}%")
    print(f"  Mean volume: {df_p['volume'].mean():.0f}")
    
    # Count extreme moves (potential data anomalies)
    extreme = (returns.abs() > 0.15).sum()
    print(f"  Extreme moves (>15%): {extreme}")

# Walk-forward sensitivity test
print(f"\n{'=' * 120}")
print("WALK-FORWARD SENSITIVITY: ARB")
print(f"{'=' * 120}")

print(f"\nTesting different splits to check stability:")

for split in [(0.5, 0.7, 1.0), (0.6, 0.8, 1.0), (0.7, 0.85, 1.0), (0.4, 0.6, 0.8)]:
    train_end = int(len(c) * split[0])
    test_end = int(len(c) * split[1])
    val_end = int(len(c) * split[2])
    
    for period_name, start, end in [('Train', 0, train_end), 
                                     ('Test', train_end, test_end),
                                     ('Val', test_end, val_end)]:
        period_trades = run_mr_detailed(c[start:end], o[start:end], h[start:end], l[start:end],
                                        rsi[start:end], bb_lower[start:end], atr[start:end], 
                                        vol_ratio[start:end], session[start:end], ['ASIA', 'NY'])
        if period_trades:
            period_results = np.array([t['result'] for t in period_trades])
            w = period_results[period_results > 0]
            ls = period_results[period_results <= 0]
            pf = w.sum() / abs(ls.sum()) if len(ls) > 0 else 999
            print(f"  Split {split[0]*100:.0f}/{split[1]*100:.0f} - {period_name}: N={len(period_trades)} Exp={period_results.mean()*100:.2f}% PF={pf:.2f}")
        else:
            print(f"  Split {split[0]*100:.0f}/{split[1]*100:.0f} - {period_name}: N=0")
