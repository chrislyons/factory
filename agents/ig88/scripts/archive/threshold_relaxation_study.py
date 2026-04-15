#!/usr/bin/env python3
"""
Threshold Relaxation Study
===========================
Find optimal entry threshold balance between signal frequency and edge.

Current thresholds are SO strict that signals are rare (0 in 120+ scanner cycles).
This study tests progressively looser thresholds to find the sweet spot:
- More signals = more data = faster validation
- But looser thresholds = potentially lower PF

We also incorporate REAL friction modeling to ensure EV stays positive.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import json
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
OUTPUT_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# ============================================
# REAL FRICTION MODEL (Kraken Spot)
# ============================================
# Maker: 0.16% (limit order, adds liquidity)
# Taker: 0.26% (market order, takes liquidity)
# Spread: ~0.05-0.10% on liquid pairs, ~0.15-0.30% on illiquid
# Slippage: ~0.05% on liquid, ~0.15% on illiquid

FRICTION_PROFILES = {
    'kraken_maker': {
        'commission': 0.0016,   # 0.16% maker fee
        'spread': 0.0007,       # 0.07% avg spread (liquid pairs)
        'slippage': 0.0005,     # 0.05% slippage on limit fills
        'total_rt': 0.0038,     # 0.38% round-trip (in + out)
    },
    'kraken_taker': {
        'commission': 0.0026,   # 0.26% taker fee
        'spread': 0.0007,       # 0.07% avg spread
        'slippage': 0.0010,     # 0.10% slippage on market
        'total_rt': 0.0050,     # 0.50% round-trip
    },
    'kraken_illiquid': {
        'commission': 0.0016,   # 0.16% maker
        'spread': 0.0020,       # 0.20% spread (illiquid)
        'slippage': 0.0015,     # 0.15% slippage
        'total_rt': 0.0066,     # 0.66% round-trip
    },
}

# Current strict thresholds
CURRENT_THRESHOLDS = {
    'STRONG':  {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'pair_vol': 'liquid'},
    'MEDIUM':  {'rsi': 22, 'bb': 0.12, 'vol': 1.2, 'pair_vol': 'liquid'},
    'WEAK':    {'rsi': 25, 'bb': 0.15, 'vol': 1.2, 'pair_vol': 'liquid'},
}

# Threshold relaxation levels
RELAXATION_LEVELS = {
    'strict': {'rsi_mult': 1.0, 'bb_mult': 1.0, 'vol_mult': 1.0, 'label': 'Current (Strict)'},
    'moderate': {'rsi_mult': 1.3, 'bb_mult': 1.5, 'vol_mult': 0.9, 'label': 'Moderate Relaxation'},
    'aggressive': {'rsi_mult': 1.6, 'bb_mult': 2.0, 'vol_mult': 0.8, 'label': 'Aggressive Relaxation'},
    'very_aggressive': {'rsi_mult': 2.0, 'bb_mult': 3.0, 'vol_mult': 0.7, 'label': 'Very Aggressive'},
    'frequency_focus': {'rsi_mult': 2.5, 'bb_mult': 4.0, 'vol_mult': 0.6, 'label': 'Max Frequency'},
}

# Pair classification
STRONG_PAIRS = ['ARB', 'SUI', 'AVAX', 'MATIC', 'UNI']
MEDIUM_PAIRS = ['DOT', 'ALGO', 'ATOM', 'FIL']
WEAK_PAIRS = ['ADA', 'INJ', 'LINK', 'LTC', 'AAVE', 'SNX']
ALL_PAIRS = STRONG_PAIRS + MEDIUM_PAIRS + WEAK_PAIRS


def load_data(pair):
    """Load OHLCV data from parquet."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        df = pd.read_parquet(path)
        # Ensure columns are lowercase
        df.columns = [c.lower() for c in df.columns]
        return df
    return None


def compute_indicators(df):
    """Compute RSI, BB%, ATR, Volume ratio."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values
    
    # RSI (14-period)
    delta = np.diff(c, prepend=c[0])
    gain = pd.Series(delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = pd.Series(-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = np.nan_to_num(rsi, nan=50)
    
    # Bollinger Band % (2σ, 20-period)
    sma20 = pd.Series(c).rolling(20).mean().values
    std20 = pd.Series(c).rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    # ATR (14-period)
    tr = np.maximum(h - l, 
           np.maximum(np.abs(h - np.roll(c, 1)), 
                      np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Volume ratio (current / 20-period avg)
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / (vol_sma + 1e-10)
    
    # Regime detection (ATR% over 20-bar average)
    atr_pct = atr / c * 100
    atr_pct_avg = pd.Series(atr_pct).rolling(20).mean().values
    atr_pct_ratio = atr_pct / (atr_pct_avg + 0.01)
    
    return {
        'close': c, 'high': h, 'low': l, 'volume': v,
        'rsi': rsi, 'bb_pct': bb_pct, 'atr': atr,
        'vol_ratio': vol_ratio, 'atr_pct_ratio': atr_pct_ratio,
    }


def get_thresholds(pair, relaxation_level):
    """Get entry thresholds for a pair at given relaxation level."""
    level = RELAXATION_LEVELS[relaxation_level]
    
    # Get base thresholds based on pair tier
    if pair in STRONG_PAIRS:
        base = CURRENT_THRESHOLDS['STRONG']
    elif pair in MEDIUM_PAIRS:
        base = CURRENT_THRESHOLDS['MEDIUM']
    else:
        base = CURRENT_THRESHOLDS['WEAK']
    
    # Apply relaxation multipliers
    # RSI: higher threshold = more signals (looser)
    # BB%: higher threshold = more signals (looser)
    # Volume: lower threshold = more signals (looser)
    return {
        'rsi': min(45, int(base['rsi'] * level['rsi_mult'])),
        'bb': min(0.40, base['bb'] * level['bb_mult']),
        'vol': max(0.5, base['vol'] * level['vol_mult']),
    }


def backtest_pair(pair, relaxation_level, friction_profile='kraken_maker'):
    """Run backtest for a pair with given thresholds and friction."""
    df = load_data(pair)
    if df is None or len(df) < 200:
        return None
    
    ind = compute_indicators(df)
    thresholds = get_thresholds(pair, relaxation_level)
    friction = FRICTION_PROFILES[friction_profile]['total_rt']
    
    # Find entries
    c = ind['close']
    rsi = ind['rsi']
    bb_pct = ind['bb_pct']
    vol_ratio = ind['vol_ratio']
    atr = ind['atr']
    h = ind['high']
    l = ind['low']
    
    trades = []
    entry_bars = []
    
    # Use bars 100+ to ensure indicators are stable
    for i in range(100, len(c) - 30):
        # Entry condition (T+2 entry to match backtest convention)
        if (rsi[i] < thresholds['rsi'] and 
            bb_pct[i] < thresholds['bb'] and 
            vol_ratio[i] > thresholds['vol']):
            
            entry_bar = i + 2  # T+2 entry
            if entry_bar >= len(c) - 25:
                continue
                
            entry_price = c[entry_bar]
            if np.isnan(entry_price) or entry_price <= 0:
                continue
            
            # Stop/target based on ATR
            atr_val = atr[entry_bar] if not np.isnan(atr[entry_bar]) else entry_price * 0.02
            stop_pct = 1.0 if pair in STRONG_PAIRS else 1.25
            target_pct = 2.5 if pair in STRONG_PAIRS else 2.0
            
            stop_price = entry_price - atr_val * stop_pct
            target_price = entry_price + atr_val * target_pct
            
            # Check exit within 25 bars
            for j in range(1, 26):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                
                if l[bar] <= stop_price:
                    # Stop loss hit
                    ret = -stop_pct / 100 - friction
                    trades.append(ret)
                    entry_bars.append(entry_bar)
                    break
                elif h[bar] >= target_price:
                    # Target hit
                    ret = target_pct / 100 - friction
                    trades.append(ret)
                    entry_bars.append(entry_bar)
                    break
            else:
                # Time exit at bar 25
                exit_price = c[min(entry_bar + 25, len(c) - 1)]
                ret = (exit_price - entry_price) / entry_price - friction
                trades.append(ret)
                entry_bars.append(entry_bar)
    
    if not trades:
        return {
            'pair': pair, 'n': 0, 'pf': 0, 'wr': 0,
            'avg_win': 0, 'avg_loss': 0, 'ev': 0,
            'thresholds': thresholds,
        }
    
    trades = np.array(trades)
    wins = trades[trades > 0]
    losses = trades[trades <= 0]
    
    gross_wins = np.sum(wins) if len(wins) > 0 else 0
    gross_losses = -np.sum(losses) if len(losses) > 0 else 1e-10
    pf = gross_wins / gross_losses if gross_losses > 0 else 0
    
    wr = len(wins) / len(trades) * 100 if len(trades) > 0 else 0
    avg_win = np.mean(wins) * 100 if len(wins) > 0 else 0
    avg_loss = np.mean(losses) * 100 if len(losses) > 0 else 0
    ev = np.mean(trades) * 100
    
    return {
        'pair': pair,
        'n': len(trades),
        'pf': pf,
        'wr': wr,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'ev': ev,
        'trades_per_year': len(trades) / ((len(df) - 200) / (6 * 365)),  # 4h bars -> years
        'thresholds': thresholds,
    }


def run_study():
    """Run full threshold relaxation study."""
    print("=" * 80)
    print("THRESHOLD RELAXATION STUDY")
    print("=" * 80)
    
    results = {}
    
    for level_name, level_config in RELAXATION_LEVELS.items():
        print(f"\n{'='*60}")
        print(f"Testing: {level_config['label']}")
        print(f"RSI x{level_config['rsi_mult']}, BB x{level_config['bb_mult']}, Vol x{level_config['vol_mult']}")
        print(f"{'='*60}")
        
        level_results = []
        
        for pair in ALL_PAIRS:
            result = backtest_pair(pair, level_name)
            if result and result['n'] > 0:
                level_results.append(result)
                print(f"  {pair:6s}: n={result['n']:3d}, PF={result['pf']:.2f}, WR={result['wr']:.1f}%, EV={result['ev']:.3f}%")
        
        if level_results:
            # Aggregate metrics
            total_trades = sum(r['n'] for r in level_results)
            weighted_pf = sum(r['pf'] * r['n'] for r in level_results) / total_trades if total_trades > 0 else 0
            weighted_wr = sum(r['wr'] * r['n'] for r in level_results) / total_trades if total_trades > 0 else 0
            weighted_ev = sum(r['ev'] * r['n'] for r in level_results) / total_trades if total_trades > 0 else 0
            
            # Estimate monthly trades (12 pairs)
            avg_trades_per_pair = np.mean([r['n'] for r in level_results])
            est_monthly_trades = avg_trades_per_pair * 12 / 5  # 5 years of data
            
            print(f"\n  AGGREGATE:")
            print(f"    Total backtest trades: {total_trades}")
            print(f"    Avg trades/pair: {avg_trades_per_pair:.1f}")
            print(f"    Est. monthly trades: {est_monthly_trades:.1f}")
            print(f"    Weighted PF: {weighted_pf:.2f}")
            print(f"    Weighted WR: {weighted_wr:.1f}%")
            print(f"    Weighted EV: {weighted_ev:.3f}%")
            
            results[level_name] = {
                'label': level_config['label'],
                'total_trades': total_trades,
                'avg_trades_per_pair': avg_trades_per_pair,
                'est_monthly_trades': est_monthly_trades,
                'weighted_pf': weighted_pf,
                'weighted_wr': weighted_wr,
                'weighted_ev': weighted_ev,
                'per_pair': level_results,
            }
    
    return results


def project_6_month_returns(results):
    """Project 6-month returns for each threshold level."""
    print("\n" + "=" * 80)
    print("6-MONTH RETURN PROJECTIONS BY THRESHOLD LEVEL")
    print("=" * 80)
    
    initial_capital = 10000
    risk_per_trade = 0.015  # 1.5% risk per trade
    np.random.seed(42)
    n_sim = 10000
    n_months = 6
    
    projections = []
    
    for level_name, data in results.items():
        trades_per_month = max(4, int(data['est_monthly_trades']))
        total_trades = trades_per_month * n_months
        
        # PF and WR from backtest
        pf = data['weighted_pf']
        wr = data['weighted_wr'] / 100
        
        # EV per trade
        stop = 0.01
        if pf > 0 and wr > 0 and wr < 1:
            target = pf * (1 - wr) * stop / wr
            friction = 0.0038  # Kraken maker
            ev = (wr * (target - friction)) - ((1 - wr) * (stop + friction/2))
        else:
            ev = -0.001
        
        # Monte Carlo
        final_values = []
        for _ in range(n_sim):
            equity = initial_capital
            for _ in range(total_trades):
                if np.random.random() < wr:
                    pnl = equity * (target - 0.0038) if target > 0 else 0
                else:
                    pnl = -equity * stop
                equity += pnl
            final_values.append(equity)
        
        final_values = np.array(final_values)
        
        proj = {
            'level': level_name,
            'label': data['label'],
            'trades_per_month': trades_per_month,
            'total_trades': total_trades,
            'pf': pf,
            'wr': data['weighted_wr'],
            'ev_pct': ev * 100,
            'p_profit': np.mean(final_values > initial_capital) * 100,
            'exp_return': (np.mean(final_values) / initial_capital - 1) * 100,
            'p_10pct': np.mean(final_values > initial_capital * 1.10) * 100,
            'p_loss_10': np.mean(final_values < initial_capital * 0.90) * 100,
            'median_return': (np.median(final_values) / initial_capital - 1) * 100,
        }
        projections.append(proj)
        
        print(f"\n{data['label']}:")
        print(f"  Trades/month: {trades_per_month} | PF: {pf:.2f} | WR: {data['weighted_wr']:.1f}%")
        print(f"  P(profit): {proj['p_profit']:.1f}% | Expected: {proj['exp_return']:+.1f}% | P(>10%): {proj['p_10pct']:.1f}%")
    
    return projections


def friction_analysis():
    """Analyze friction impact and mitigation strategies."""
    print("\n" + "=" * 80)
    print("FRICTION ANALYSIS & MITIGATION")
    print("=" * 80)
    
    print("\n--- REAL-WORLD FRICTION BREAKDOWN ---")
    
    scenarios = [
        ("Liquid pair, limit order (ideal)", 'kraken_maker'),
        ("Liquid pair, market order", 'kraken_taker'),
        ("Illiquid pair, limit order", 'kraken_illiquid'),
    ]
    
    for name, profile_key in scenarios:
        profile = FRICTION_PROFILES[profile_key]
        print(f"\n{name}:")
        print(f"  Commission (round-trip): {profile['commission']*2*100:.2f}%")
        print(f"  Spread (round-trip):     {profile['spread']*2*100:.2f}%")
        print(f"  Slippage (round-trip):   {profile['slippage']*2*100:.2f}%")
        print(f"  TOTAL ROUND-TRIP:        {profile['total_rt']*100:.2f}%")
    
    print("\n--- FRICTION MITIGATION STRATEGIES ---")
    print("""
1. LIMIT ORDERS ONLY (mandatory)
   - Avoid taker fees (0.26% vs 0.16%)
   - Savings: 0.20% per trade = 0.40% round-trip
   
2. PAIR SELECTION BY LIQUIDITY
   - STRONG: ARB, SUI, AVAX, MATIC, UNI (spread < 0.10%)
   - MEDIUM: DOT, ALGO, ATOM, FIL (spread 0.10-0.15%)
   - WEAK: Avoid or use smaller size (spread > 0.15%)
   
3. SIZE LIMITS BY PAIR LIQUIDITY
   - Check order book depth before entry
   - Max order: 0.1% of 24h volume to limit slippage
   
4. TIME-OF-DAY OPTIMIZATION
   - Avoid low-liquidity hours (00:00-06:00 UTC)
   - Best liquidity: 13:00-21:00 UTC (US + EU overlap)
   
5. ORDER MANAGEMENT
   - Place limit at mid-price, not bid
   - Cancel if not filled in 5 minutes
   - Use IOC (Immediate-or-Cancel) to avoid partial fills
   
6. AVOID FUNDING RATE COSTS (perps only)
   - Close positions before funding (every 8h on most perps)
   - Or take the opposite funding position as hedge
""")
    
    # Calculate net EV with friction mitigation
    print("\n--- EV IMPACT OF FRICTION MITIGATION ---")
    
    # Base case: 0.50% friction (taker)
    base_ev = 0.002 * 100  #假设 base EV of 0.2%
    mitigated_ev = (0.002 + 0.0038) * 100  # with 0.38% friction saved
    
    print(f"  With taker friction (0.50%):  EV = {(0.002 - 0.0050/2)*100:.3f}% per trade")
    print(f"  With maker friction (0.38%):  EV = {(0.002 - 0.0038/2)*100:.3f}% per trade")
    print(f"  Friction savings:             +{(0.0050 - 0.0038)/2*100:.3f}% per trade")
    print(f"  Annual impact (120 trades):   +{(0.0050 - 0.0038)/2*100*120:.1f}% of capital")


def main():
    """Run full study."""
    start_time = datetime.now(timezone.utc)
    
    # Run threshold study
    results = run_study()
    
    # Project returns
    projections = project_6_month_returns(results)
    
    # Friction analysis
    friction_analysis()
    
    # Save results
    output = {
        'timestamp': start_time.isoformat(),
        'results': {k: v for k, v in results.items()},
        'projections': projections,
    }
    
    output_path = OUTPUT_DIR / 'threshold_relaxation_study.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n\nResults saved to: {output_path}")
    
    # Summary table
    print("\n" + "=" * 80)
    print("SUMMARY: THRESHOLD LEVEL vs OUTCOMES")
    print("=" * 80)
    print(f"\n{'Level':<20} {'Trades/mo':>10} {'PF':>8} {'WR':>8} {'P(profit)':>10} {'Exp Return':>12}")
    print("-" * 70)
    for p in projections:
        print(f"{p['label']:<20} {p['trades_per_month']:>10} {p['pf']:>8.2f} {p['wr']:>7.1f}% {p['p_profit']:>9.1f}% {p['exp_return']:>+11.1f}%")
    
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"\nStudy completed in {elapsed:.1f}s")


if __name__ == '__main__':
    main()
