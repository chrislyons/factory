"""
Final Portfolio Construction Test
==================================
Test combined portfolio with strategy-per-pair optimization.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

def load_data(pair='SOL'):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        return pd.read_parquet(path)
    return None

def compute_indicators(df):
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
    
    return {'c': c, 'o': df['open'].values, 'h': h, 'l': l,
            'rsi': rsi, 'sma20': sma20, 'std20': std20,
            'vol_ratio': vol_ratio, 'atr': atr}

def run_portfolio_test():
    """Test the optimized portfolio allocation"""
    
    # Portfolio configuration (optimized from testing)
    portfolio = {
        'SOL':  {'weight': 0.40, 'strategy': 'MR', 'rsi': 40, 'bb_std': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.0025, 'target': 0.10},
        'NEAR': {'weight': 0.25, 'strategy': 'MR', 'rsi': 40, 'bb_std': 1.0, 'vol': 1.5, 'entry': 1, 'stop': 0.0025, 'target': 0.15},
        'LINK': {'weight': 0.15, 'strategy': 'MR', 'rsi': 38, 'bb_std': 0.5, 'vol': 1.1, 'entry': 0, 'stop': 0.0025, 'target': 0.15},
        'AVAX': {'weight': 0.15, 'strategy': 'MR', 'rsi': 32, 'bb_std': 0.5, 'vol': 1.3, 'entry': 0, 'stop': 0.0025, 'target': 0.15},
        # BTC: 0% allocation (market leader only)
        # ETH: 0% allocation (no edge)
    }
    
    print("="*90)
    print("FINAL PORTFOLIO TEST (Optimized Params)")
    print("="*90)
    
    all_trades = []
    pair_results = {}
    
    for pair, config in portfolio.items():
        df = load_data(pair)
        if df is None:
            continue
        
        ind = compute_indicators(df)
        c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
        bb_l = ind['sma20'] - ind['std20'] * config['bb_std']
        
        trades = []
        for i in range(100, len(c) - config['entry'] - 8):
            if np.isnan(ind['rsi'][i]) or np.isnan(bb_l[i]) or np.isnan(ind['vol_ratio'][i]):
                continue
            
            if ind['rsi'][i] < config['rsi'] and ind['c'][i] < bb_l[i] and ind['vol_ratio'][i] > config['vol']:
                entry_bar = i + config['entry']
                if entry_bar >= len(c) - 8:
                    continue
                
                entry = o[entry_bar]
                stop = entry * (1 - config['stop'])
                target = entry * (1 + config['target'])
                
                exited = False
                for j in range(1, 9):
                    bar = entry_bar + j
                    if bar >= len(l):
                        break
                    if l[bar] <= stop:
                        trades.append(-config['stop'] - FRICTION)
                        exited = True
                        break
                    elif h[bar] >= target:
                        trades.append(config['target'] - FRICTION)
                        exited = True
                        break
                
                if not exited:
                    exit_price = c[min(entry_bar + 8, len(c) - 1)]
                    trades.append((exit_price - entry) / entry - FRICTION)
        
        trades = np.array(trades) if trades else np.array([])
        
        if len(trades) > 0:
            w = trades[trades > 0]
            ls = trades[trades <= 0]
            pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
            wr = len(w) / len(trades) * 100
            exp = trades.mean() * 100
            
            pair_results[pair] = {
                'trades': len(trades),
                'pf': pf,
                'wr': wr,
                'exp': exp,
                'weight': config['weight'],
                'returns': trades,
            }
            
            all_trades.extend(trades * config['weight'])
            
            print(f"\n{pair} ({config['weight']*100:.0f}% allocation):")
            print(f"  Trades: {len(trades)}")
            print(f"  PF: {pf:.3f}")
            print(f"  WR: {wr:.1f}%")
            print(f"  Exp: {exp:.3f}% per trade")
            print(f"  Weighted Exp: {exp * config['weight']:.3f}%")
    
    # Portfolio aggregate
    all_trades = np.array(all_trades)
    if len(all_trades) > 0:
        w = all_trades[all_trades > 0]
        ls = all_trades[all_trades <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
        wr = len(w) / len(all_trades) * 100
        exp = all_trades.mean() * 100
        
        print("\n" + "="*90)
        print("PORTFOLIO AGGREGATE")
        print("="*90)
        print(f"Total weighted trades: {len(all_trades)}")
        print(f"Portfolio PF: {pf:.3f}")
        print(f"Portfolio WR: {wr:.1f}%")
        print(f"Portfolio Exp: {exp:.3f}% per trade")
        
        # Sharpe-like metric
        if all_trades.std() > 0:
            sharpe = all_trades.mean() / all_trades.std() * np.sqrt(252/8)
            print(f"Annualized Sharpe: {sharpe:.2f}")
        
        # Expected monthly return (rough)
        trades_per_month = len(all_trades) / 36  # ~3 years of 4h bars / 12 months
        monthly_ret = ((1 + exp/100) ** trades_per_month - 1) * 100
        print(f"Expected Monthly Return: {monthly_ret:.1f}%")
    
    print("\n" + "="*90)
    print("PORTFOLIO RECOMMENDATION")
    print("="*90)
    print("""
Based on optimized testing:

  PRIMARY ALLOCATION (95%):
    SOL   40%  MR (RSI<40, BB 1.5σ, Vol>1.5, T1, 0.25%/10%)
    NEAR  25%  MR (RSI<40, BB 1.0σ, Vol>1.5, T1, 0.25%/15%)
    LINK  15%  MR (RSI<38, BB 0.5σ, Vol>1.1, T0, 0.25%/15%)
    AVAX  15%  MR (RSI<32, BB 0.5σ, Vol>1.3, T0, 0.25%/15%)
    BTC    0%  Market leader monitor
    ETH    0%  No edge

  POSITION SIZING:
    $500 per position (pre-approval threshold)
    2x leverage (Jupiter perps)
    Max 2 concurrent positions initially

  RISK MANAGEMENT:
    Volatility circuit breaker: 5% move = tighten stops, 12% = close all
    Daily loss limit: 3% of portfolio
    Re-optimize quarterly
""")

run_portfolio_test()
