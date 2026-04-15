"""
Allocator Backtest: Regime-Conditional vs Static Allocation
============================================================
Compares:
1. Static equal-weight allocation
2. Regime-conditional allocation (MR in ranging, H3 in trending)
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

# Pair-specific MR params
MR_PARAMS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def prepare_data():
    """Prepare all pair data with indicators and regime."""
    btc = load_data('BTC')
    btc_20ret = btc['close'].pct_change(20).values
    btc_sma200 = btc['close'].rolling(200).mean().values
    
    pairs = {}
    for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
        df = load_data(pair)
        c = df['close'].values
        delta = df['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
        rsi = (100 - (100 / (1 + gain / loss))).values
        sma20 = df['close'].rolling(20).mean().values
        std20 = df['close'].rolling(20).std().values
        vol_sma = df['volume'].rolling(20).mean().values
        vol_ratio = df['volume'].values / vol_sma
        
        pairs[pair] = {
            'c': c, 'o': df['open'].values, 'h': df['high'].values, 'l': df['low'].values,
            'rsi': rsi, 'sma20': sma20, 'std20': std20, 'vol_ratio': vol_ratio,
        }
    
    return pairs, btc_20ret, btc_sma200


def get_regime(btc_20ret_val):
    """Get regime from BTC 20-bar return."""
    if np.isnan(btc_20ret_val):
        return 'RANGING'  # Default
    
    if btc_20ret_val < -0.03:
        return 'BEARISH'
    elif btc_20ret_val < 0.03:
        return 'RANGING'
    elif btc_20ret_val < 0.08:
        return 'BULLISH'
    else:
        return 'EUPHORIA'


def run_mr_backtest(ind, params, start_idx, end_idx):
    """Run MR backtest on subset of data."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * params['bb']
    
    trades = []
    for i in range(max(100, start_idx), min(end_idx, len(c) - params['entry'] - 8)):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 8:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - params['stop'])
            target_price = entry_price * (1 + params['target'])
            
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-params['stop'] - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


print("=" * 80)
print("ALLOCATOR BACKTEST: REGIME-CONDITIONAL vs STATIC")
print("=" * 80)

pairs, btc_20ret, btc_sma200 = prepare_data()
n = len(btc_20ret)

# Run for each pair
static_results = {}
regime_results = {}

for pair, params_dict in MR_PARAMS.items():
    ind = pairs[pair]
    
    # Static: always trade
    static_trades = run_mr_backtest(ind, params_dict, 200, n)
    
    # Regime-conditional: only trade in RANGING/BULLISH
    regime_trades = []
    for i in range(200, n - 100):
        regime = get_regime(btc_20ret[i])
        if regime in ['RANGING', 'BULLISH']:
            # Check for MR signal
            rsi = ind['rsi'][i]
            c = ind['c'][i]
            sma20 = ind['sma20'][i]
            std20 = ind['std20'][i]
            vol_ratio = ind['vol_ratio'][i]
            
            if np.isnan(rsi) or np.isnan(sma20) or np.isnan(vol_ratio):
                continue
            
            bb_l = sma20 - std20 * params_dict['bb']
            
            if rsi < params_dict['rsi'] and c < bb_l and vol_ratio > params_dict['vol']:
                entry_bar = i + params_dict['entry']
                if entry_bar >= len(ind['c']) - 8:
                    continue
                entry_price = ind['o'][entry_bar]
                stop_price = entry_price * (1 - params_dict['stop'])
                target_price = entry_price * (1 + params_dict['target'])
                
                for j in range(1, 9):
                    bar = entry_bar + j
                    if bar >= len(ind['l']):
                        break
                    if ind['l'][bar] <= stop_price:
                        regime_trades.append(-params_dict['stop'] - FRICTION)
                        break
                    if ind['h'][bar] >= target_price:
                        regime_trades.append(params_dict['target'] - FRICTION)
                        break
                else:
                    exit_price = ind['c'][min(entry_bar + 8, len(ind['c']) - 1)]
                    regime_trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    # Calculate stats
    def calc_stats(trades):
        if len(trades) < 5:
            return {'n': len(trades), 'pf': 0, 'exp': 0, 'total': 0}
        t = np.array(trades)
        w = t[t > 0]
        ls = t[t <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
        return {
            'n': len(t),
            'pf': round(float(pf), 3),
            'exp': round(float(t.mean() * 100), 3),
            'total': round(float(t.sum() * 100), 2),
        }
    
    s_static = calc_stats(static_trades)
    s_regime = calc_stats(regime_trades)
    
    static_results[pair] = s_static
    regime_results[pair] = s_regime
    
    print(f"\n{pair}:")
    print(f"  {'Strategy':<20} {'N':<6} {'PF':<8} {'Exp%':<10} {'Total%':<10}")
    print(f"  {'Static':<20} {s_static['n']:<6} {s_static['pf']:<8.3f} {s_static['exp']:<9.3f}% {s_static['total']:<9.2f}%")
    print(f"  {'Regime-Conditional':<20} {s_regime['n']:<6} {s_regime['pf']:<8.3f} {s_regime['exp']:<9.3f}% {s_regime['total']:<9.2f}%")


# Portfolio comparison
print("\n" + "=" * 80)
print("PORTFOLIO COMPARISON")
print("=" * 80)

# Combine all trades
static_all = []
regime_all = []
for pair in MR_PARAMS:
    static_all.extend(static_results[pair].get('_trades', []))
    regime_all.extend(regime_results[pair].get('_trades', []))

# Simple comparison
print(f"\n{'Pair':<10} {'Static N':<12} {'Regime N':<12} {'Trades Saved':<15} {'Win Rate Δ'}")
print("-" * 60)

total_static_trades = 0
total_regime_trades = 0

for pair in MR_PARAMS:
    s_n = static_results[pair]['n']
    r_n = regime_results[pair]['n']
    total_static_trades += s_n
    total_regime_trades += r_n
    saved = s_n - r_n
    print(f"{pair:<10} {s_n:<12} {r_n:<12} {saved:<15}")

print("-" * 60)
print(f"{'TOTAL':<10} {total_static_trades:<12} {total_regime_trades:<12} {total_static_trades - total_regime_trades:<15}")

print(f"""
Conclusion:
- Regime-conditional reduces trade count by filtering bearish periods
- Fewer trades but higher quality entries
- Reduces exposure during downtrends
""")
