"""
Regime-Specific Performance: SUI + OP
=======================================
How does the MR strategy perform in different regimes?
- RISK_OFF: BTC < 200-SMA, low vol
- BEARISH: BTC < 200-SMA, high vol
- RANGING: BTC > 200-SMA, low vol
- BULLISH: BTC > 200-SMA, high vol

This helps us know when to trade vs when to sit out.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133

PAIRS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.75'},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.5'},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def load_btc():
    return pd.read_parquet(DATA_DIR / 'binance_BTC_USDT_240m.parquet')


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


def compute_regime(btc_df):
    """Compute regime for each bar based on BTC."""
    btc_c = btc_df['close'].values
    btc_sma200 = btc_df['close'].rolling(200).mean().values
    btc_ret20 = btc_df['close'].pct_change(20).values
    btc_vol20 = btc_df['close'].pct_change().rolling(20).std().values * np.sqrt(6*365)  # Annualized
    
    regimes = []
    for i in range(len(btc_c)):
        if np.isnan(btc_sma200[i]) or np.isnan(btc_ret20[i]) or np.isnan(btc_vol20[i]):
            regimes.append('UNKNOWN')
            continue
        
        above_sma = btc_c[i] > btc_sma200[i]
        high_vol = btc_vol20[i] > 0.40  # 40% annualized vol threshold
        
        if not above_sma and not high_vol:
            regimes.append('RISK_OFF')
        elif not above_sma and high_vol:
            regimes.append('BEARISH')
        elif above_sma and not high_vol:
            regimes.append('RANGING')
        else:
            regimes.append('BULLISH')
    
    return regimes


def get_stop_distance(stop_type, entry_price, atr_value):
    if stop_type == 'fixed_0.5':
        return entry_price * 0.005
    elif stop_type == 'fixed_0.75':
        return entry_price * 0.0075
    return entry_price * 0.005


def run_backtest_with_regime(pair, params, df, btc_df):
    c, o, h, l, rsi, bb_l, vol_ratio, atr = compute_indicators(df)
    regimes = compute_regime(btc_df)
    
    # Align lengths
    min_len = min(len(c), len(regimes))
    c, o, h, l, rsi, bb_l, vol_ratio, atr = [arr[:min_len] for arr in [c, o, h, l, rsi, bb_l, vol_ratio, atr]]
    regimes = regimes[:min_len]
    
    trades_by_regime = {r: [] for r in ['RISK_OFF', 'BEARISH', 'RANGING', 'BULLISH']}
    
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        
        regime = regimes[i]
        if regime == 'UNKNOWN':
            continue
        
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_dist = get_stop_distance(params['stop'], entry_price, atr[entry_bar])
            stop_price = entry_price - stop_dist
            target_price = entry_price * (1 + params['target'])
            
            trade_pnl = None
            for j in range(1, 16):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trade_pnl = -stop_dist/entry_price - FRICTION
                    break
                if h[bar] >= target_price:
                    trade_pnl = params['target'] - FRICTION
                    break
            
            if trade_pnl is None:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trade_pnl = (exit_price - entry_price) / entry_price - FRICTION
            
            trades_by_regime[regime].append(trade_pnl)
    
    return trades_by_regime


def calc_regime_stats(trades_dict):
    results = {}
    for regime, trades in trades_dict.items():
        t = np.array(trades) if trades else np.array([])
        if len(t) < 3:
            results[regime] = {'n': 0, 'pf': 0, 'exp': 0, 'wr': 0}
            continue
        w = t[t > 0]
        ls = t[t <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
        results[regime] = {
            'n': len(t),
            'pf': round(float(pf), 3),
            'exp': round(float(t.mean() * 100), 3),
            'wr': round(float(len(w) / len(t) * 100), 1),
        }
    return results


print("=" * 90)
print("REGIME-SPECIFIC PERFORMANCE: SUI + OP")
print("=" * 90)

btc_df = load_btc()

regime_totals = {r: {'n': 0, 'wins': 0, 'pnls': []} for r in ['RISK_OFF', 'BEARISH', 'RANGING', 'BULLISH']}

for pair, params in PAIRS.items():
    print(f"\n{'─' * 90}")
    print(f"{pair}")
    print(f"{'─' * 90}")
    
    df = load_data(pair)
    trades_by_regime = run_backtest_with_regime(pair, params, df, btc_df)
    stats = calc_regime_stats(trades_by_regime)
    
    print(f"{'Regime':<15} {'N':<8} {'PF':<10} {'Exp%':<12} {'WR':<10} {'Verdict'}")
    print("-" * 65)
    
    for regime in ['RISK_OFF', 'BEARISH', 'RANGING', 'BULLISH']:
        s = stats[regime]
        verdict = "TRADE" if s['exp'] > 0.5 and s['pf'] > 1.2 else "CAUTIOUS" if s['exp'] > 0 else "AVOID"
        print(f"{regime:<15} {s['n']:<8} {s['pf']:<10.3f} {s['exp']:<11.3f}% {s['wr']:<9.1f}% {verdict}")
        
        # Accumulate totals
        regime_totals[regime]['n'] += s['n']
        regime_totals[regime]['pnls'].extend(trades_by_regime[regime])

print(f"\n{'=' * 90}")
print("PORTFOLIO REGIME SUMMARY (SUI + OP Combined)")
print(f"{'=' * 90}")

print(f"\n{'Regime':<15} {'Total N':<10} {'Avg Exp%':<12} {'Recommendation'}")
print("-" * 60)

for regime in ['RISK_OFF', 'BEARISH', 'RANGING', 'BULLISH']:
    pnls = np.array(regime_totals[regime]['pnls']) if regime_totals[regime]['pnls'] else np.array([])
    n = len(pnls)
    if n > 0:
        avg_exp = pnls.mean() * 100
        rec = "TRADE FULL" if avg_exp > 1.0 else "TRADE REDUCED" if avg_exp > 0.3 else "SIT OUT"
    else:
        avg_exp = 0
        rec = "NO DATA"
    print(f"{regime:<15} {n:<10} {avg_exp:<11.3f}% {rec}")
