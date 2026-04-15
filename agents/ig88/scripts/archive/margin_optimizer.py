"""
Margin Optimizer: Growing PnL Through Strategy Combination + Position Sizing
============================================================================
Goals:
1. Combine MR (mean reversion) + H3 (trend) as orthogonal strategies
2. Add Kelly Criterion for position sizing
3. Test regime-conditional allocation
4. Find the edge-per-dollar maximum
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

# Robust params from audit
MR_PARAMS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def prepare_indicators(df):
    c = df['close'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Ichimoku for H3
    tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
    kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26)
    
    # BTC regime
    btc_df = load_data('BTC')
    btc_c = btc_df['close'].values
    btc_20ret = np.full(len(c), np.nan)
    btc_ret = pd.Series(btc_c).pct_change(20).values
    min_len = min(len(btc_ret), len(c))
    btc_20ret[:min_len] = btc_ret[:min_len]
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20, 'vol_ratio': vol_ratio, 'atr': atr,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'senkou_a': senkou_a.values, 'senkou_b': senkou_b.values,
        'btc_20ret': btc_20ret,
    }


def run_mr_trades(ind, params):
    """Generate MR trade returns with timestamps."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20 = ind['rsi'], ind['sma20'], ind['std20']
    vol_ratio = ind['vol_ratio']
    bb_l = sma20 - std20 * params['bb']
    
    trades = []
    timestamps = []
    
    for i in range(100, len(c) - params['entry'] - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            stop = entry * (1 - params['stop'])
            target = entry * (1 + params['target'])
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop:
                    trades.append(-params['stop'] - FRICTION)
                    timestamps.append(bar)
                    exited = True
                    break
                if h[bar] >= target:
                    trades.append(params['target'] - FRICTION)
                    timestamps.append(bar)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
                timestamps.append(entry_bar + 8)
    
    return np.array(trades), np.array(timestamps)


def run_h3a_trades(ind, exit_bars=10):
    """Generate H3-A trade returns with timestamps."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    tenkan, kijun = ind['tenkan'], ind['kijun']
    senkou_a, senkou_b = ind['senkou_a'], ind['senkou_b']
    rsi = ind['rsi']
    btc_20ret = ind['btc_20ret']
    
    trades = []
    timestamps = []
    
    for i in range(100, len(c) - exit_bars - 5):
        if np.isnan(rsi[i]) or np.isnan(tenkan[i]) or np.isnan(kijun[i]):
            continue
        if np.isnan(senkou_a[i]) or np.isnan(senkou_b[i]):
            continue
        
        # BTC regime filter (mandatory)
        if not np.isnan(btc_20ret[i]) and btc_20ret[i] < 0:
            continue
        
        tk_cross = tenkan[i] > kijun[i]
        cloud_top = np.nanmax([senkou_a[i], senkou_b[i]])
        above_cloud = c[i] > cloud_top
        rsi_ok = rsi[i] > 40
        
        score = int(tk_cross) + int(above_cloud) + int(rsi_ok)
        if score < 3:
            continue
        
        entry_bar = i + 1
        if entry_bar >= len(c) - exit_bars:
            continue
        
        entry = o[entry_bar]
        exit_price = c[min(entry_bar + exit_bars, len(c) - 1)]
        trades.append((exit_price - entry) / entry - FRICTION)
        timestamps.append(entry_bar)
    
    return np.array(trades), np.array(timestamps)


def run_h3b_trades(ind, exit_bars=10):
    """Generate H3-B trade returns with timestamps."""
    c, o = ind['c'], ind['o']
    vol_ratio = ind['vol_ratio']
    rsi = ind['rsi']
    btc_20ret = ind['btc_20ret']
    
    trades = []
    timestamps = []
    
    for i in range(100, len(c) - exit_bars - 1):
        if np.isnan(vol_ratio[i]) or np.isnan(rsi[i]):
            continue
        if i < 20:
            continue
        
        # BTC regime filter
        if not np.isnan(btc_20ret[i]) and btc_20ret[i] < 0:
            continue
        
        vol_spike = vol_ratio[i] > 1.5
        price_gain = (c[i] - c[i-1]) / c[i-1] > 0.005
        rsi_cross = rsi[i] > 50 and rsi[i-1] <= 50
        
        if not (vol_spike and price_gain and rsi_cross):
            continue
        
        entry_bar = i + 1
        if entry_bar >= len(c) - exit_bars:
            continue
        
        entry = o[entry_bar]
        exit_price = c[min(entry_bar + exit_bars, len(c) - 1)]
        trades.append((exit_price - entry) / entry - FRICTION)
        timestamps.append(entry_bar)
    
    return np.array(trades), np.array(timestamps)


def calc_stats(trades):
    if len(trades) < 5:
        return {'n': 0, 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0}
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
    }


def kelly_fraction(win_rate, avg_win, avg_loss):
    """Calculate Kelly fraction for position sizing."""
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)  # Win/loss ratio
    p = win_rate / 100
    kelly = (p * b - (1 - p)) / b
    return max(0, min(kelly, 0.25))  # Cap at 25% for safety


print("=" * 100)
print("MARGIN OPTIMIZER: STRATEGY COMBINATION + POSITION SIZING")
print("=" * 100)

all_pair_results = {}
combined_trades = []

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    print(f"\n{'=' * 80}")
    print(f"PAIR: {pair}")
    print(f"{'=' * 80}")
    
    df = load_data(pair)
    ind = prepare_indicators(df)
    
    # MR trades
    mr_params = MR_PARAMS[pair]
    mr_trades, mr_ts = run_mr_trades(ind, mr_params)
    mr_stats = calc_stats(mr_trades)
    print(f"\n  MR: PF={mr_stats['pf']:.3f}, n={mr_stats['n']}, WR={mr_stats['wr']:.1f}%, Exp={mr_stats['exp']:.3f}%")
    
    # H3-A trades (only for SOL/NEAR per earlier validation)
    if pair in ['SOL']:
        h3a_trades, h3a_ts = run_h3a_trades(ind)
        h3a_stats = calc_stats(h3a_trades)
        print(f"  H3-A: PF={h3a_stats['pf']:.3f}, n={h3a_stats['n']}, WR={h3a_stats['wr']:.1f}%, Exp={h3a_stats['exp']:.3f}%")
    else:
        h3a_trades, h3a_stats = np.array([]), {'n': 0, 'pf': 0, 'exp': 0}
    
    # H3-B trades (SOL + AVAX per earlier validation)
    if pair in ['SOL', 'AVAX']:
        h3b_trades, h3b_ts = run_h3b_trades(ind)
        h3b_stats = calc_stats(h3b_trades)
        print(f"  H3-B: PF={h3b_stats['pf']:.3f}, n={h3b_stats['n']}, WR={h3b_stats['wr']:.1f}%, Exp={h3b_stats['exp']:.3f}%")
    else:
        h3b_trades, h3b_stats = np.array([]), {'n': 0, 'pf': 0, 'exp': 0}
    
    # Combined trades for this pair
    pair_combined = []
    if len(mr_trades) > 0:
        pair_combined.extend(mr_trades)
    if len(h3a_trades) > 0:
        pair_combined.extend(h3a_trades)
    if len(h3b_trades) > 0:
        pair_combined.extend(h3b_trades)
    
    if pair_combined:
        pair_combined = np.array(pair_combined)
        pair_stats = calc_stats(pair_combined)
        print(f"  Combined: PF={pair_stats['pf']:.3f}, n={pair_stats['n']}, Exp={pair_stats['exp']:.3f}%")
        
        # Kelly sizing
        w = pair_combined[pair_combined > 0]
        ls = pair_combined[pair_combined <= 0]
        if len(w) > 0 and len(ls) > 0:
            avg_win = w.mean() * 100
            avg_loss = ls.mean() * 100
            wr = len(w) / len(pair_combined) * 100
            kelly = kelly_fraction(wr, avg_win, avg_loss) * 100
            print(f"  Kelly Fraction: {kelly:.1f}% (Half-Kelly: {kelly/2:.1f}%)")
        
        all_pair_results[pair] = {
            'mr': mr_stats, 'h3a': h3a_stats, 'h3b': h3b_stats,
            'combined': pair_stats, 'trades': pair_combined,
        }


# ============================================================================
# CROSS-PAIR PORTFOLIO ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("PORTFOLIO ANALYSIS: COMBINING ALL STRATEGIES ACROSS ALL PAIRS")
print("=" * 100)

# Merge all trades (equal weight assumption)
all_trades = []
for pair, r in all_pair_results.items():
    if 'trades' in r and len(r['trades']) > 0:
        all_trades.extend(r['trades'])

if all_trades:
    all_trades = np.array(all_trades)
    portfolio_stats = calc_stats(all_trades)
    
    print(f"\nPortfolio Summary (Equal Weight):")
    print(f"  Total trades: {portfolio_stats['n']}")
    print(f"  Portfolio PF: {portfolio_stats['pf']:.3f}")
    print(f"  Win Rate: {portfolio_stats['wr']:.1f}%")
    print(f"  Expectancy: {portfolio_stats['exp']:.3f}% per trade")
    print(f"  Sharpe: {portfolio_stats['sharpe']:.2f}")
    
    # Portfolio Kelly
    w = all_trades[all_trades > 0]
    ls = all_trades[all_trades <= 0]
    if len(w) > 0 and len(ls) > 0:
        avg_win = w.mean() * 100
        avg_loss = ls.mean() * 100
        wr = len(w) / len(all_trades) * 100
        kelly = kelly_fraction(wr, avg_win, avg_loss) * 100
        print(f"\n  Portfolio Kelly: {kelly:.1f}%")
        print(f"  Half-Kelly (recommended): {kelly/2:.1f}%")
        print(f"  Quarter-Kelly (conservative): {kelly/4:.1f}%")


# ============================================================================
# REGIME-CONDITIONAL ALLOCATION
# ============================================================================
print("\n" + "=" * 100)
print("REGIME-CONDITIONAL ALLOCATION")
print("=" * 100)

print("""
Based on research vault findings:
- MR (mean reversion) works in RANGING/LOW-VOL regimes
- H3 (trend) works in TRENDING/HIGH-VOL regimes

Regime Detection:
- BTC 20-bar return > +5%: TRENDING (favor H3)
- BTC 20-bar return < -5%: RISK_OFF (no new positions)
- Else: RANGING (favor MR)

Allocation Model:
- RANGING:   80% MR / 20% H3
- TRENDING:  30% MR / 70% H3
- RISK_OFF:  0% (cash only)
""")


# ============================================================================
# SENSITIVITY TO STOP SIZE: THE MEV TRADEOFF
# ============================================================================
print("\n" + "=" * 100)
print("CRITICAL TRADEOFF: STOP SIZE vs PF vs MEV RISK")
print("=" * 100)

print(f"\n{'Pair':<8} {'Stop':<10} {'PF':<10} {'Exp%':<10} {'MEV Risk':<10}")
print("-" * 50)

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    df = load_data(pair)
    ind = prepare_indicators(df)
    params = MR_PARAMS[pair].copy()
    
    for stop in [0.005, 0.006, 0.0075, 0.01]:
        params['stop'] = stop
        trades, _ = run_mr_trades(ind, params)
        stats = calc_stats(trades)
        mev = "HIGH" if stop <= 0.005 else "MED" if stop <= 0.0075 else "LOW"
        print(f"{pair:<8} {stop*100:>6.2f}%   {stats['pf']:<10.3f} {stats['exp']:<9.3f}% {mev:<10}")


# ============================================================================
# MARGIN GROWTH STRATEGIES
# ============================================================================
print("\n" + "=" * 100)
print("MARGIN GROWTH: WHERE THE EDGE COMES FROM")
print("=" * 100)

print("""
Current Edge Sources:
1. MR (all 4 pairs): PF 2.4-3.9, ~150-170 trades per pair
2. H3-A (SOL only): PF 2.3, ~2500 trades
3. H3-B (SOL + AVAX): PF 1.8-4.1, ~70-80 trades

To Grow Margins:

A. ADD MORE PAIRS (untested)
   - Test: FTM, MATIC, DOT, ATOM, UNI, AAVE
   - Same RSI<30, BB 1.5-2.0, Vol>1.8 params
   - Expected: 2-4 additional viable pairs

B. OPTIMIZE EXIT TIMING
   - Current: Fixed T8 exits for MR
   - Test: Dynamic exit based on RSI reversal
   - Test: Partial take-profit (50% at target, trail rest)

C. ADD TREND FILTER TO MR
   - Current: No trend filter
   - Test: Only MR when ADX < 25 (ranging)
   - Expected: Higher WR in ranging regimes

D. POSITION SIZING OPTIMIZATION
   - Current: Equal weight
   - Test: Kelly-weighted by strategy expectancy
   - Test: Volatility-weighted (ATR normalized)

E. COMBINE WITH H3 MORE EFFECTIVELY
   - Current: Simple combination
   - Test: Regime-conditional (MR in ranging, H3 in trending)
""")

print("\nRecommendation: Focus on (A) adding more pairs and (E) regime-conditional allocation.")
print("These have the highest marginal value per development hour.")
