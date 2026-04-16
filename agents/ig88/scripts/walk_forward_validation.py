#!/usr/bin/env python3
"""
Comprehensive Walk-Forward Validation for Trading Strategies
Tests 310 viable strategies across multiple splits, symbols, and market regimes.
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re
from dataclasses import dataclass, asdict
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# Configuration
DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h')
STRATEGIES_FILE = Path('/Users/nesbitt/dev/factory/agents/ig88/data/new_strategies.json')
OUTPUT_FILE = Path('/Users/nesbitt/dev/factory/agents/ig88/data/walk_forward_validation.json')

# Available symbols with 1h data
AVAILABLE_SYMBOLS = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX', 'NEAR', 'ADA', 'ARB', 'DOGE', 
                     'BNB', 'ENA', 'LIT', 'PEPE', 'SUI', 'TAO', 'TRUMP', 'WLD', 'XMR', 'XRP', 'ZEC',
                     'BIO', 'PAXG', 'PENGU']

# Slippage assumption
SLIPPAGE_PCT = 0.0005  # 0.05%

@dataclass
class TradeResult:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    direction: str
    pnl_pct: float
    slippage_cost: float

@dataclass 
class BacktestResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    total_return: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    trades_per_year: float
    profitable: bool
    sharpe_ratio: float = 0.0

class StrategyEngine:
    """Implements all strategy types"""
    
    @staticmethod
    def parse_strategy_params(strat_str: str) -> Tuple[str, Dict]:
        """Parse strategy string like 'ATR_BO(atr_period=14,atr_mult=1.5,lookback=20)'"""
        match = re.match(r'(\w+)\((.*?)\)', strat_str)
        if not match:
            raise ValueError(f"Invalid strategy format: {strat_str}")
        
        strat_type = match.group(1)
        params_str = match.group(2)
        
        params = {}
        if params_str:
            for param in params_str.split(','):
                if '=' in param:
                    key, val = param.split('=')
                    try:
                        params[key.strip()] = float(val.strip())
                    except:
                        params[key.strip()] = val.strip()
        
        return strat_type, params
    
    @staticmethod
    def atr_bo_strategy(df: pd.DataFrame, params: Dict, direction: str, 
                        trail_pct: float, hold_hours: int) -> List[Dict]:
        """ATR Breakout Strategy"""
        atr_period = int(params.get('atr_period', 14))
        atr_mult = params.get('atr_mult', 1.5)
        lookback = int(params.get('lookback', 20))
        
        # Calculate ATR
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        tr = np.maximum(high[1:] - low[1:], 
               np.maximum(np.abs(high[1:] - close[:-1]),
                         np.abs(low[1:] - close[:-1])))
        tr = np.concatenate([[0], tr])
        
        atr = pd.Series(tr).rolling(atr_period).mean().values
        
        # Calculate breakout levels
        upper = df['high'].rolling(lookback).max().values
        lower = df['low'].rolling(lookback).min().values
        
        signals = []
        in_trade = False
        entry_price = 0
        entry_idx = 0
        stop_price = 0
        
        for i in range(max(atr_period, lookback) + 1, len(df)):
            if np.isnan(atr[i]) or np.isnan(upper[i]) or np.isnan(lower[i]):
                continue
                
            current_close = close[i]
            current_atr = atr[i]
            
            if not in_trade:
                if direction == 'LNG':
                    # Long breakout: price breaks above upper band
                    if current_close > upper[i-1]:
                        entry_price = current_close
                        stop_price = entry_price - (atr_mult * current_atr)
                        entry_idx = i
                        in_trade = True
                        
                elif direction == 'SHT':
                    # Short breakout: price breaks below lower band
                    if current_close < lower[i-1]:
                        entry_price = current_close
                        stop_price = entry_price + (atr_mult * current_atr)
                        entry_idx = i
                        in_trade = True
            else:
                # Manage trade
                bars_held = i - entry_idx
                exit_trade = False
                exit_reason = ''
                
                if direction == 'LNG':
                    # Update trailing stop
                    if trail_pct > 0:
                        new_stop = current_close * (1 - trail_pct)
                        stop_price = max(stop_price, new_stop)
                    
                    # Check exit conditions
                    if current_close <= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                        
                elif direction == 'SHT':
                    # Update trailing stop
                    if trail_pct > 0:
                        new_stop = current_close * (1 + trail_pct)
                        stop_price = min(stop_price, new_stop)
                    
                    # Check exit conditions
                    if current_close >= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                
                if exit_trade:
                    exit_price = stop_price if exit_reason == 'stop' else current_close
                    
                    if direction == 'LNG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    signals.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'direction': direction,
                        'pnl_pct': pnl_pct,
                        'entry_time': df.index[entry_idx],
                        'exit_time': df.index[i]
                    })
                    
                    in_trade = False
        
        return signals
    
    @staticmethod
    def rsi_simple_strategy(df: pd.DataFrame, params: Dict, direction: str,
                           trail_pct: float, hold_hours: int) -> List[Dict]:
        """RSI Simple Strategy"""
        rsi_period = int(params.get('rsi_period', 14))
        oversold = params.get('oversold', 30)
        overbought = params.get('overbought', 70)
        
        # Calculate RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        signals = []
        in_trade = False
        entry_price = 0
        entry_idx = 0
        stop_price = 0
        
        for i in range(rsi_period + 1, len(df)):
            if pd.isna(rsi.iloc[i]):
                continue
                
            current_close = df['close'].iloc[i]
            current_rsi = rsi.iloc[i]
            
            if not in_trade:
                if direction == 'LNG':
                    # Long on oversold RSI
                    if current_rsi < oversold:
                        entry_price = current_close
                        stop_price = entry_price * (1 - trail_pct) if trail_pct > 0 else entry_price * 0.97
                        entry_idx = i
                        in_trade = True
                        
                elif direction == 'SHT':
                    # Short on overbought RSI
                    if current_rsi > overbought:
                        entry_price = current_close
                        stop_price = entry_price * (1 + trail_pct) if trail_pct > 0 else entry_price * 1.03
                        entry_idx = i
                        in_trade = True
            else:
                bars_held = i - entry_idx
                exit_trade = False
                exit_reason = ''
                
                if direction == 'LNG':
                    if trail_pct > 0:
                        new_stop = current_close * (1 - trail_pct)
                        stop_price = max(stop_price, new_stop)
                    
                    if current_close <= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_rsi > overbought:
                        exit_trade = True
                        exit_reason = 'signal'
                        
                elif direction == 'SHT':
                    if trail_pct > 0:
                        new_stop = current_close * (1 + trail_pct)
                        stop_price = min(stop_price, new_stop)
                    
                    if current_close >= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_rsi < oversold:
                        exit_trade = True
                        exit_reason = 'signal'
                
                if exit_trade:
                    exit_price = stop_price if exit_reason == 'stop' else current_close
                    
                    if direction == 'LNG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    signals.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'direction': direction,
                        'pnl_pct': pnl_pct,
                        'entry_time': df.index[entry_idx],
                        'exit_time': df.index[i]
                    })
                    
                    in_trade = False
        
        return signals
    
    @staticmethod
    def volspike_strategy(df: pd.DataFrame, params: Dict, direction: str,
                         trail_pct: float, hold_hours: int) -> List[Dict]:
        """Volume Spike Strategy"""
        vol_period = int(params.get('vol_period', 20))
        vol_mult = params.get('vol_mult', 2.0)
        lookback = int(params.get('lookback', 10))
        
        # Calculate volume metrics
        vol_ma = df['volume'].rolling(vol_period).mean()
        vol_std = df['volume'].rolling(vol_period).std()
        
        signals = []
        in_trade = False
        entry_price = 0
        entry_idx = 0
        stop_price = 0
        
        for i in range(vol_period + 1, len(df)):
            if pd.isna(vol_ma.iloc[i]) or pd.isna(vol_std.iloc[i]):
                continue
                
            current_close = df['close'].iloc[i]
            current_vol = df['volume'].iloc[i]
            
            # Volume spike detection
            vol_threshold = vol_ma.iloc[i] + (vol_std.iloc[i] * vol_mult)
            
            if not in_trade:
                if direction == 'LNG':
                    # Long on volume spike with upward price movement
                    if current_vol > vol_threshold and df['close'].iloc[i] > df['close'].iloc[i-1]:
                        entry_price = current_close
                        stop_price = entry_price * (1 - trail_pct) if trail_pct > 0 else entry_price * 0.97
                        entry_idx = i
                        in_trade = True
                        
                elif direction == 'SHT':
                    # Short on volume spike with downward price movement
                    if current_vol > vol_threshold and df['close'].iloc[i] < df['close'].iloc[i-1]:
                        entry_price = current_close
                        stop_price = entry_price * (1 + trail_pct) if trail_pct > 0 else entry_price * 1.03
                        entry_idx = i
                        in_trade = True
            else:
                bars_held = i - entry_idx
                exit_trade = False
                exit_reason = ''
                
                if direction == 'LNG':
                    if trail_pct > 0:
                        new_stop = current_close * (1 - trail_pct)
                        stop_price = max(stop_price, new_stop)
                    
                    if current_close <= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                        
                elif direction == 'SHT':
                    if trail_pct > 0:
                        new_stop = current_close * (1 + trail_pct)
                        stop_price = min(stop_price, new_stop)
                    
                    if current_close >= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                
                if exit_trade:
                    exit_price = stop_price if exit_reason == 'stop' else current_close
                    
                    if direction == 'LNG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    signals.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'direction': direction,
                        'pnl_pct': pnl_pct,
                        'entry_time': df.index[entry_idx],
                        'exit_time': df.index[i]
                    })
                    
                    in_trade = False
        
        return signals
    
    @staticmethod
    def bb_mr_strategy(df: pd.DataFrame, params: Dict, direction: str,
                      trail_pct: float, hold_hours: int) -> List[Dict]:
        """Bollinger Band Mean Reversion Strategy"""
        bb_period = int(params.get('bb_period', 20))
        bb_std = params.get('bb_std', 2.0)
        
        # Calculate Bollinger Bands
        sma = df['close'].rolling(bb_period).mean()
        std = df['close'].rolling(bb_period).std()
        upper_band = sma + (std * bb_std)
        lower_band = sma - (std * bb_std)
        
        signals = []
        in_trade = False
        entry_price = 0
        entry_idx = 0
        stop_price = 0
        
        for i in range(bb_period + 1, len(df)):
            if pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
                continue
                
            current_close = df['close'].iloc[i]
            
            if not in_trade:
                if direction == 'LNG':
                    # Long when price touches lower band (mean reversion)
                    if current_close <= lower_band.iloc[i]:
                        entry_price = current_close
                        stop_price = entry_price * (1 - trail_pct) if trail_pct > 0 else entry_price * 0.97
                        entry_idx = i
                        in_trade = True
                        
                elif direction == 'SHT':
                    # Short when price touches upper band
                    if current_close >= upper_band.iloc[i]:
                        entry_price = current_close
                        stop_price = entry_price * (1 + trail_pct) if trail_pct > 0 else entry_price * 1.03
                        entry_idx = i
                        in_trade = True
            else:
                bars_held = i - entry_idx
                exit_trade = False
                exit_reason = ''
                
                if direction == 'LNG':
                    if trail_pct > 0:
                        new_stop = current_close * (1 - trail_pct)
                        stop_price = max(stop_price, new_stop)
                    
                    if current_close <= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_close >= sma.iloc[i]:
                        exit_trade = True
                        exit_reason = 'mean'
                        
                elif direction == 'SHT':
                    if trail_pct > 0:
                        new_stop = current_close * (1 + trail_pct)
                        stop_price = min(stop_price, new_stop)
                    
                    if current_close >= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_close <= sma.iloc[i]:
                        exit_trade = True
                        exit_reason = 'mean'
                
                if exit_trade:
                    exit_price = stop_price if exit_reason == 'stop' else current_close
                    
                    if direction == 'LNG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    signals.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'direction': direction,
                        'pnl_pct': pnl_pct,
                        'entry_time': df.index[entry_idx],
                        'exit_time': df.index[i]
                    })
                    
                    in_trade = False
        
        return signals
    
    @staticmethod
    def vwap_dev_strategy(df: pd.DataFrame, params: Dict, direction: str,
                         trail_pct: float, hold_hours: int) -> List[Dict]:
        """VWAP Deviation Strategy"""
        vwap_period = int(params.get('vwap_period', 20))
        dev_mult = params.get('dev_mult', 1.5)
        
        # Calculate VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).rolling(vwap_period).sum() / df['volume'].rolling(vwap_period).sum()
        
        # Calculate deviation bands
        dev = (typical_price - vwap).rolling(vwap_period).std()
        upper_dev = vwap + (dev * dev_mult)
        lower_dev = vwap - (dev * dev_mult)
        
        signals = []
        in_trade = False
        entry_price = 0
        entry_idx = 0
        stop_price = 0
        
        for i in range(vwap_period + 1, len(df)):
            if pd.isna(vwap.iloc[i]) or pd.isna(upper_dev.iloc[i]) or pd.isna(lower_dev.iloc[i]):
                continue
                
            current_close = df['close'].iloc[i]
            
            if not in_trade:
                if direction == 'LNG':
                    # Long when price is significantly below VWAP
                    if current_close <= lower_dev.iloc[i]:
                        entry_price = current_close
                        stop_price = entry_price * (1 - trail_pct) if trail_pct > 0 else entry_price * 0.97
                        entry_idx = i
                        in_trade = True
                        
                elif direction == 'SHT':
                    # Short when price is significantly above VWAP
                    if current_close >= upper_dev.iloc[i]:
                        entry_price = current_close
                        stop_price = entry_price * (1 + trail_pct) if trail_pct > 0 else entry_price * 1.03
                        entry_idx = i
                        in_trade = True
            else:
                bars_held = i - entry_idx
                exit_trade = False
                exit_reason = ''
                
                if direction == 'LNG':
                    if trail_pct > 0:
                        new_stop = current_close * (1 - trail_pct)
                        stop_price = max(stop_price, new_stop)
                    
                    if current_close <= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_close >= vwap.iloc[i]:
                        exit_trade = True
                        exit_reason = 'vwap'
                        
                elif direction == 'SHT':
                    if trail_pct > 0:
                        new_stop = current_close * (1 + trail_pct)
                        stop_price = min(stop_price, new_stop)
                    
                    if current_close >= stop_price:
                        exit_trade = True
                        exit_reason = 'stop'
                    elif bars_held >= hold_hours:
                        exit_trade = True
                        exit_reason = 'time'
                    elif current_close <= vwap.iloc[i]:
                        exit_trade = True
                        exit_reason = 'vwap'
                
                if exit_trade:
                    exit_price = stop_price if exit_reason == 'stop' else current_close
                    
                    if direction == 'LNG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    signals.append({
                        'entry_idx': entry_idx,
                        'exit_idx': i,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'direction': direction,
                        'pnl_pct': pnl_pct,
                        'entry_time': df.index[entry_idx],
                        'exit_time': df.index[i]
                    })
                    
                    in_trade = False
        
        return signals

def load_symbol_data(symbol: str) -> Optional[pd.DataFrame]:
    """Load OHLCV data for a symbol"""
    # Try different file name patterns — PRIORITY: deep 60m data first
    # DO NOT use _1h.parquet files (truncated to 500 bars, created Apr 15 2026)
    patterns = [
        f'binance_{symbol}_USDT_60m.parquet',
        f'binance_{symbol}USDT_60m.parquet',
        f'binance_{symbol}USD_1440m.parquet',
        f'binance_{symbol}USDT_1440m.parquet',
    ]
    
    for pattern in patterns:
        filepath = DATA_DIR / pattern
        if filepath.exists():
            try:
                df = pd.read_parquet(filepath)
                if len(df) > 500:  # Minimum data requirement
                    return df
            except Exception as e:
                continue
    
    return None

def run_backtest(df: pd.DataFrame, strategy_type: str, params: Dict, 
                direction: str, trail_pct: float, hold_hours: int,
                slippage: float = 0) -> BacktestResult:
    """Run backtest for a strategy"""
    
    engine = StrategyEngine()
    
    # Select strategy function
    if strategy_type == 'ATR_BO':
        trades = engine.atr_bo_strategy(df, params, direction, trail_pct, hold_hours)
    elif strategy_type == 'RSI_Simple':
        trades = engine.rsi_simple_strategy(df, params, direction, trail_pct, hold_hours)
    elif strategy_type == 'VolSpike':
        trades = engine.volspike_strategy(df, params, direction, trail_pct, hold_hours)
    elif strategy_type == 'BB_MR':
        trades = engine.bb_mr_strategy(df, params, direction, trail_pct, hold_hours)
    elif strategy_type == 'VWAP_Dev':
        trades = engine.vwap_dev_strategy(df, params, direction, trail_pct, hold_hours)
    else:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)
    
    if not trades:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)
    
    # Apply slippage
    for trade in trades:
        trade['slippage_cost'] = slippage * 2  # Entry and exit
        trade['pnl_pct'] -= trade['slippage_cost']
    
    # Calculate metrics
    pnls = [t['pnl_pct'] for t in trades]
    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p <= 0]
    
    total_return = sum(pnls)
    win_rate = len(winning) / len(pnls) if pnls else 0
    
    gross_profit = sum(winning) if winning else 0
    gross_loss = abs(sum(losing)) if losing else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
    
    avg_win = np.mean(winning) if winning else 0
    avg_loss = np.mean(losing) if losing else 0
    
    # Calculate max drawdown
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = running_max - cumulative
    max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
    
    # Calculate trades per year
    if trades:
        first_date = trades[0]['entry_time']
        last_date = trades[-1]['exit_time']
        years = (last_date - first_date).total_seconds() / (365.25 * 24 * 3600)
        trades_per_year = len(trades) / years if years > 0 else len(trades)
    else:
        trades_per_year = 0
    
    # Calculate Sharpe ratio (simplified)
    if len(pnls) > 1:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if np.std(pnls) > 0 else 0
    else:
        sharpe = 0
    
    return BacktestResult(
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_return=total_return,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_drawdown=max_drawdown,
        trades_per_year=trades_per_year,
        profitable=total_return > 0,
        sharpe_ratio=sharpe
    )

def get_market_regime(df: pd.DataFrame, start_idx: int, end_idx: int) -> str:
    """Determine market regime for a period"""
    subset = df.iloc[start_idx:end_idx]
    if len(subset) < 10:
        return 'unknown'
    
    start_price = subset['close'].iloc[0]
    end_price = subset['close'].iloc[-1]
    price_change = (end_price - start_price) / start_price
    
    # Calculate volatility
    returns = subset['close'].pct_change().dropna()
    volatility = returns.std()
    
    if price_change > 0.1:
        return 'bull'
    elif price_change < -0.1:
        return 'bear'
    elif volatility > 0.02:
        return 'volatile'
    else:
        return 'sideways'

def walk_forward_validation(symbol: str, strategy_type: str, params: Dict,
                           direction: str, trail_pct: float, hold_hours: int,
                           splits: List[Tuple[float, float]]) -> Dict:
    """Run walk-forward validation with multiple splits"""
    
    df = load_symbol_data(symbol)
    if df is None:
        return {'error': f'No data for {symbol}'}
    
    results = {
        'splits': {},
        'regime_results': defaultdict(list),
        'cross_symbol_test': {}
    }
    
    # Test on different splits
    for split_pct, split_name in splits:
        split_idx = int(len(df) * split_pct)
        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]
        
        # Run on test set (out-of-sample)
        test_result = run_backtest(test_df, strategy_type, params, direction, trail_pct, hold_hours)
        
        # Run with slippage
        test_result_slippage = run_backtest(test_df, strategy_type, params, direction, trail_pct, hold_hours, SLIPPAGE_PCT)
        
        # Get regime for test period
        regime = get_market_regime(df, split_idx, len(df))
        
        results['splits'][split_name] = {
            'train_size': len(train_df),
            'test_size': len(test_df),
            'test_result': asdict(test_result),
            'test_result_slippage': asdict(test_result_slippage),
            'regime': regime,
            'profitable': test_result.profitable
        }
        
        results['regime_results'][regime].append(test_result.profitable)
    
    return results

def test_cross_symbol_stability(strategy_type: str, params: Dict, direction: str,
                               trail_pct: float, hold_hours: int,
                               test_symbols: List[str]) -> Dict:
    """Test strategy on multiple symbols"""
    
    results = {}
    profitable_symbols = 0
    
    for symbol in test_symbols:
        df = load_symbol_data(symbol)
        if df is None:
            continue
        
        # Use 70/30 split for cross-symbol testing
        split_idx = int(len(df) * 0.7)
        test_df = df.iloc[split_idx:]
        
        result = run_backtest(test_df, strategy_type, params, direction, trail_pct, hold_hours)
        
        results[symbol] = {
            'profitable': result.profitable,
            'total_return': result.total_return,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor,
            'trades': result.total_trades
        }
        
        if result.profitable:
            profitable_symbols += 1
    
    return {
        'symbol_results': results,
        'profitable_symbols': profitable_symbols,
        'total_symbols': len(results),
        'stability_score': profitable_symbols / len(results) if results else 0
    }

def score_strategy(split_results: Dict, cross_symbol_results: Dict,
                  original_pf: float) -> Dict:
    """Score strategy on robustness criteria"""
    
    scores = {
        'split_stability': 0,
        'cross_symbol_stability': 0,
        'slippage_resilience': 0,
        'regime_independence': 0,
        'total_score': 0,
        'is_robust': False
    }
    
    # 1. Split stability (profitable in 2/3 or 3/3 splits)
    profitable_splits = sum(1 for s in split_results['splits'].values() if s['profitable'])
    if profitable_splits >= 2:
        scores['split_stability'] = 1
    
    # 2. Cross-symbol stability (works on 3+ symbols)
    if cross_symbol_results['profitable_symbols'] >= 3:
        scores['cross_symbol_stability'] = 1
    
    # 3. Slippage resilience (PF drops < 10%)
    pf_with_slippage = []
    pf_without_slippage = []
    
    for split_data in split_results['splits'].values():
        pf_without = split_data['test_result']['profit_factor']
        pf_with = split_data['test_result_slippage']['profit_factor']
        
        if pf_without > 0 and pf_with > 0:
            pf_without_slippage.append(pf_without)
            pf_with_slippage.append(pf_with)
    
    if pf_without_slippage and pf_with_slippage:
        avg_pf_without = np.mean(pf_without_slippage)
        avg_pf_with = np.mean(pf_with_slippage)
        
        if avg_pf_without > 0:
            pf_drop = (avg_pf_without - avg_pf_with) / avg_pf_without
            if pf_drop < 0.1:  # Less than 10% drop
                scores['slippage_resilience'] = 1
    
    # 4. Regime independence (works in both bull and bear)
    regime_profits = defaultdict(list)
    for split_data in split_results['splits'].values():
        regime = split_data['regime']
        regime_profits[regime].append(split_data['profitable'])
    
    bull_profitable = any(regime_profits.get('bull', []))
    bear_profitable = any(regime_profits.get('bear', []))
    
    if bull_profitable and bear_profitable:
        scores['regime_independence'] = 1
    
    # Total score
    scores['total_score'] = sum(scores[k] for k in ['split_stability', 'cross_symbol_stability', 
                                                     'slippage_resilience', 'regime_independence'])
    
    # Must pass at least 2/4 criteria
    scores['is_robust'] = scores['total_score'] >= 2
    
    return scores

def main():
    print("=" * 80)
    print("COMPREHENSIVE WALK-FORWARD VALIDATION")
    print("=" * 80)
    
    # Load strategies
    with open(STRATEGIES_FILE) as f:
        all_strategies = json.load(f)
    
    # Filter for viable strategies
    viable_strategies = [s for s in all_strategies 
                        if s['pf'] > 1.5 and s['trades_yr'] > 10 and s['wr'] > 0.5]
    
    print(f"\nTotal strategies: {len(all_strategies)}")
    print(f"Viable strategies (PF>1.5, >10 trades/yr, WR>50%): {len(viable_strategies)}")
    
    # Test symbols (available in data)
    test_symbols = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX', 'NEAR', 'ADA', 'ARB', 'DOGE', 'BNB']
    
    # Filter symbols that have data
    available_test_symbols = []
    for sym in test_symbols:
        if load_symbol_data(sym) is not None:
            available_test_symbols.append(sym)
    
    print(f"Available test symbols: {available_test_symbols}")
    
    # Split configurations
    splits = [
        (0.5, '50_50'),
        (0.6, '60_40'),
        (0.7, '70_30')
    ]
    
    # Process each strategy
    results = []
    robust_count = 0
    
    for idx, strategy in enumerate(viable_strategies):
        print(f"\n[{idx+1}/{len(viable_strategies)}] Testing: {strategy['strat']} on {strategy['sym']}")
        
        try:
            # Parse strategy
            strat_type, params = StrategyEngine.parse_strategy_params(strategy['strat'])
            
            # Run walk-forward validation on original symbol
            split_results = walk_forward_validation(
                strategy['sym'], strat_type, params, 
                strategy['dir'], strategy['trail'], strategy['hold'],
                splits
            )
            
            if 'error' in split_results:
                print(f"  Error: {split_results['error']}")
                continue
            
            # Run cross-symbol stability test
            # Test on other symbols (exclude original)
            other_symbols = [s for s in available_test_symbols if s != strategy['sym']]
            
            cross_symbol_results = test_cross_symbol_stability(
                strat_type, params, strategy['dir'],
                strategy['trail'], strategy['hold'],
                other_symbols[:5]  # Test on 5 other symbols
            )
            
            # Score the strategy
            scores = score_strategy(split_results, cross_symbol_results, strategy['pf'])
            
            # Compile results
            result = {
                'original_index': idx,
                'symbol': strategy['sym'],
                'strategy': strategy['strat'],
                'direction': strategy['dir'],
                'original_pf': strategy['pf'],
                'original_wr': strategy['wr'],
                'original_trades_yr': strategy['trades_yr'],
                'trail': strategy['trail'],
                'hold': strategy['hold'],
                'split_results': split_results,
                'cross_symbol_results': cross_symbol_results,
                'robustness_scores': scores,
                'is_robust': scores['is_robust']
            }
            
            results.append(result)
            
            if scores['is_robust']:
                robust_count += 1
                print(f"  ROBUST! Score: {scores['total_score']}/4")
                print(f"    Split stability: {scores['split_stability']}")
                print(f"    Cross-symbol: {scores['cross_symbol_stability']} ({cross_symbol_results['profitable_symbols']}/5)")
                print(f"    Slippage resilience: {scores['slippage_resilience']}")
                print(f"    Regime independence: {scores['regime_independence']}")
            else:
                print(f"  Not robust. Score: {scores['total_score']}/4")
            
        except Exception as e:
            print(f"  Error processing strategy: {e}")
            continue
    
    # Sort by robustness score and original PF
    results.sort(key=lambda x: (-x['robustness_scores']['total_score'], -x['original_pf']))
    
    # Create final output
    output = {
        'metadata': {
            'total_strategies_tested': len(results),
            'robust_strategies_found': robust_count,
            'test_symbols': available_test_symbols,
            'slippage_applied': SLIPPAGE_PCT,
            'splits_tested': ['50/50', '60/40', '70/30'],
            'robustness_criteria': {
                'split_stability': 'Profitable in 2/3 or 3/3 splits',
                'cross_symbol_stability': 'Works on 3+ symbols',
                'slippage_resilience': 'PF drops < 10% with 0.05% slippage',
                'regime_independence': 'Works in both bull and bear markets'
            },
            'minimum_criteria': 'Must pass at least 2/4 criteria'
        },
        'robust_strategies': [r for r in results if r['is_robust']],
        'all_results': results
    }
    
    # Save results
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total strategies tested: {len(results)}")
    print(f"Robust strategies found: {robust_count}")
    print(f"\nTop 10 Robust Strategies:")
    
    for i, result in enumerate(output['robust_strategies'][:10]):
        print(f"\n{i+1}. {result['strategy']} on {result['symbol']} ({result['direction']})")
        print(f"   Original PF: {result['original_pf']:.2f}, WR: {result['original_wr']:.1%}")
        print(f"   Robustness Score: {result['robustness_scores']['total_score']}/4")
        print(f"   Split stability: {result['robustness_scores']['split_stability']}")
        print(f"   Cross-symbol: {result['robustness_scores']['cross_symbol_stability']}")
        print(f"   Slippage resilient: {result['robustness_scores']['slippage_resilience']}")
        print(f"   Regime independent: {result['robustness_scores']['regime_independence']}")
    
    print(f"\nResults saved to: {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
