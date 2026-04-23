#!/usr/bin/env python3
"""
Compound Returns Backtest — Proper position sizing with compounding.
Tests different risk fractions and leverage to find maximum PnL%.
"""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')
from src.quant import indicators as ind

DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h'
ATR_PERIOD = 14; SMA_PERIOD = 100; LONG_MULT = 2.0; SHORT_MULT = 1.5

# Robust pairs only (WF-validated)
LONG_PAIRS = ['NEAR_USDT','AVAX_USDT','ETH_USDT','LINK_USDT','BTC_USD','ATOM_USDT','SUI_USDT']
SHORT_PAIRS = ['AVAX_USDT','ATOM_USDT']

def load_4h(symbol):
    for f in [f'binance_{symbol}_240m.parquet', f'binance_{symbol}_240m_resampled.parquet']:
        fp = os.path.join(DATA_DIR, f)
        if os.path.exists(fp):
            df = pd.read_parquet(fp)
            if 'time' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df['time'], unit='s')
            return df[['open','high','low','close','volume']].sort_index()
    return None

def calc(df):
    df = df.copy()
    h=df['high'].values; l=df['low'].values; c=df['close'].values
    df['atr'] = ind.atr(h,l,c,ATR_PERIOD)
    df['sma100'] = ind.sma(c,SMA_PERIOD)
    return df.dropna()

def bt_long(df, mult=LONG_MULT):
    """Returns list of (pnl_pct, duration_bars) tuples."""
    trades = []; in_pos = False; ep = 0.0; entry_bar = 0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] <= df['sma100'].iloc[i-1] and df['close'].iloc[i] > df['sma100'].iloc[i]:
                w = df['close'].iloc[i:i+2]
                if len(w) < 2: continue
                if w.iloc[1] > df['sma100'].iloc[i] * 1.005:
                    ep = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    in_pos = True; entry_bar = i
        else:
            if df['low'].iloc[i] <= ep - mult * df['atr'].iloc[entry_bar]:
                pnl = ((ep - mult * df['atr'].iloc[entry_bar])/ep - 1)*100
                trades.append((pnl, i - entry_bar)); in_pos = False
            elif df['close'].iloc[i] < df['sma100'].iloc[i]:
                pnl = (df['close'].iloc[i]/ep - 1)*100
                trades.append((pnl, i - entry_bar)); in_pos = False
    return trades

def bt_short(df, mult=SHORT_MULT):
    trades = []; in_pos = False; ep = 0.0; entry_bar = 0
    for i in range(1, len(df)):
        if not in_pos:
            if df['close'].iloc[i-1] >= df['sma100'].iloc[i-1] and df['close'].iloc[i] < df['sma100'].iloc[i]:
                w = df['close'].iloc[i:i+2]
                if len(w) < 2: continue
                if w.iloc[1] < df['sma100'].iloc[i] * 0.995:
                    ep = df['open'].iloc[i+2] if i+2 < len(df) else df['close'].iloc[i]
                    in_pos = True; entry_bar = i
        else:
            if df['high'].iloc[i] >= ep + mult * df['atr'].iloc[entry_bar]:
                pnl = (1 - (ep + mult * df['atr'].iloc[entry_bar])/ep)*100
                trades.append((pnl, i - entry_bar)); in_pos = False
            elif df['close'].iloc[i] > df['sma100'].iloc[i]:
                pnl = (1 - df['close'].iloc[i]/ep)*100
                trades.append((pnl, i - entry_bar)); in_pos = False
    return trades


def compound_backtest(trades_by_pair, starting_capital, risk_fraction, leverage, fee_rt=0.0014):
    """
    Proper compound backtest.
    - risk_fraction: % of capital allocated per trade (0.1 = 10%)
    - leverage: multiplier on allocated capital
    - fee_rt: round-trip fee as decimal
    
    Returns: final_capital, total_return%, max_dd%, sharpe, trade_returns[]
    """
    capital = starting_capital
    peak = capital
    max_dd = 0
    trade_returns = []  # as % of total capital
    
    # Merge all trades chronologically and simulate
    # For simplicity, we process pair by pair (parallel positions)
    # Each trade risks risk_fraction * leverage of capital
    
    exposure = risk_fraction * leverage  # Effective capital deployed per trade
    
    # Collect all individual trade returns as fraction of total capital
    all_returns = []
    for pair, trades in trades_by_pair.items():
        for pnl_pct, duration in trades:
            # PnL as fraction of total capital = (pnl_pct/100) * exposure
            ret = (pnl_pct / 100) * exposure - fee_rt
            all_returns.append(ret)
    
    # Sort by... well, trades happen in parallel across pairs
    # So we apply them in the order they occurred
    # For simplicity, apply sequentially (conservative — underestimates compounding)
    
    for ret in all_returns:
        capital *= (1 + ret)
        peak = max(peak, capital)
        dd = (peak - capital) / peak
        max_dd = max(max_dd, dd)
        trade_returns.append(ret)
    
    total_return = (capital / starting_capital - 1) * 100
    
    # Sharpe (annualized)
    if len(trade_returns) > 1:
        avg_ret = np.mean(trade_returns)
        std_ret = np.std(trade_returns)
        # Assume ~30 trades per year
        sharpe = avg_ret / (std_ret + 1e-10) * np.sqrt(30)
    else:
        sharpe = 0
    
    return capital, total_return, max_dd * 100, sharpe, trade_returns


# Load all trades
print("="*100)
print("COMPOUND RETURNS ANALYSIS — 4H ATR Breakout")
print("="*100)

all_long_trades = {}
all_short_trades = {}
all_trades = {}

for sym in LONG_PAIRS:
    df = load_4h(sym)
    if df is None or len(df) < 2000: continue
    df = calc(df)
    years = len(df) / (6*365)
    trades = bt_long(df)
    all_long_trades[sym] = trades
    all_trades[sym] = trades
    pnls = [t[0] for t in trades]
    print(f"  {sym.replace('_USDT','').replace('_USD',''):<6s} LONG  n={len(trades):>4d} avg={np.mean(pnls):>+.2f}%  total_simple={sum(pnls):>+.1f}%  ({years:.1f}yr)")

for sym in SHORT_PAIRS:
    df = load_4h(sym)
    if df is None or len(df) < 2000: continue
    df = calc(df)
    years = len(df) / (6*365)
    trades = bt_short(df)
    all_short_trades[sym] = trades
    all_trades[sym + '_S'] = trades
    pnls = [t[0] for t in trades]
    print(f"  {sym.replace('_USDT',''):<6s} SHORT n={len(trades):>4d} avg={np.mean(pnls):>+.2f}%  total_simple={sum(pnls):>+.1f}%  ({years:.1f}yr)")

# Compound analysis across different risk/leverage combos
print(f"\n{'='*100}")
print("COMPOUND RETURNS BY RISK FRACTION × LEVERAGE")
print(f"{'='*100}")
print(f"\n  {'Risk':>6s} {'Lev':>4s} {'Expo':>6s}  {'Final$':>10s} {'Return':>8s} {'MaxDD':>7s} {'Sharpe':>7s}  {'$500→':>8s}  {'Trades':>7s}")
print(f"  {'-'*75}")

START = 10000.0  # Base capital for simulation
results = []

for risk_pct in [10, 15, 20, 25, 30, 40, 50]:
    for leverage in [1, 2, 3, 5, 10]:
        risk = risk_pct / 100
        final, ret, dd, sharpe, trade_rets = compound_backtest(
            all_trades, START, risk, leverage, fee_rt=0.0014
        )
        
        # Project to $500
        proj_500 = 500 * (1 + ret/100)
        
        results.append({
            'risk': risk_pct, 'leverage': leverage,
            'exposure': risk_pct * leverage,
            'final': final, 'return': ret, 'dd': dd,
            'sharpe': sharpe, 'proj_500': proj_500,
            'n_trades': len(trade_rets)
        })
        
        if risk_pct in [10, 20, 30, 50] and leverage in [1, 3, 5, 10]:
            print(f"  {risk_pct:>5d}% {leverage:>3d}x {risk_pct*leverage:>5d}%  ${final:>10,.0f} {ret:>+7.0f}% {dd:>6.1f}% {sharpe:>6.2f}  ${proj_500:>8,.0f}  {len(trade_rets):>6d}")

# Best combos for $500 → $10K target
print(f"\n{'='*100}")
print("PATHS TO $10K FROM $500 (sorted by return)")
print(f"{'='*100}")

for r in sorted(results, key=lambda x: x['return'], reverse=True):
    if r['proj_500'] >= 10000:
        print(f"  Risk {r['risk']}% × {r['leverage']}x = {r['exposure']}% exposure → ${r['proj_500']:,.0f}  (Return: {r['return']:+.0f}%, MaxDD: {r['dd']:.1f}%, Sharpe: {r['sharpe']:.2f})")

# Find minimum risk to hit $10K
print(f"\n  Minimum risk/leverage combos to reach $10K from $500:")
for r in sorted(results, key=lambda x: x['exposure']):
    if r['proj_500'] >= 10000:
        print(f"  → Risk {r['risk']}% × {r['leverage']}x = {r['exposure']}% exposure  (Return: {r['return']:+.0f}%, DD: {r['dd']:.1f}%)")
        break

# Walk-forward compound test
print(f"\n{'='*100}")
print("WALK-FORWARD COMPOUND TEST (3-split)")
print(f"{'='*100}")

for sym in ['NEAR_USDT','AVAX_USDT','ETH_USDT','LINK_USDT']:
    df = load_4h(sym)
    if df is None: continue
    df = calc(df)
    n = len(df); sz = n // 4
    
    for risk_pct, leverage in [(20, 3), (25, 3), (30, 5)]:
        risk = risk_pct / 100
        oos_capitals = []
        
        for k in range(3):
            test_df = df.iloc[sz*(k+1):min(sz*(k+2), n)]
            if len(test_df) < 200: continue
            trades = bt_long(test_df)
            if not trades: continue
            
            capital = 10000
            exposure = risk * leverage
            for pnl_pct, _ in trades:
                ret = (pnl_pct/100) * exposure - 0.0014
                capital *= (1 + ret)
            oos_capitals.append(capital)
        
        if oos_capitals:
            avg_final = np.mean(oos_capitals)
            avg_ret = (avg_final/10000 - 1) * 100
            name = sym.replace('_USDT','')
            print(f"  {name:<6s} Risk {risk_pct}%×{leverage}x: OOS compound = {avg_ret:>+.0f}% (avg of {len(oos_capitals)} splits)")
