#!/usr/bin/env python3
"""
Fresh Backtest - April 2026
=============================
Re-validate Kraken MR and Jupiter H3-B on current market data.

Objective: Verify edges still hold in current regime before paper trading.
"""
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

# Add project to path
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

OUTPUT_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
OUTPUT_DIR.mkdir(exist_ok=True)


def fetch_ohlcv(pair: str, interval: str, days: int = 90) -> pd.DataFrame:
    """Fetch OHLCV from Binance public API (reliable, deep history)."""
    import urllib.request
    import urllib.parse
    import json
    
    # SOL/USDT -> SOLUSDT, BTC/USD -> BTCUSDT
    symbol = pair.replace('/', '')
    if symbol.endswith('USDT'):
        pass  # Already correct
    elif symbol.endswith('USD'):
        symbol = symbol.replace('USD', 'USDT', 1)  # Only replace once at end
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': min(days * 24 // _interval_hours(interval) + 100, 1000)
    }
    
    url = f"https://api.binance.com/api/v3/klines?{urllib.parse.urlencode(params)}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'IG88/1.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        
        if isinstance(data, dict) and 'code' in data:
            print(f"  Error fetching {pair}: {data.get('msg', 'unknown')}")
            return pd.DataFrame()
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        df.set_index('timestamp', inplace=True)
        return df[['open', 'high', 'low', 'close', 'volume']]
    
    except Exception as e:
        print(f"  Exception for {pair}: {e}")
        return pd.DataFrame()


def _interval_hours(interval: str) -> int:
    """Convert interval string to hours."""
    if interval.endswith('h'):
        return int(interval[:-1])
    if interval.endswith('d'):
        return int(interval[:-1]) * 24
    if interval == '4h':
        return 4
    return 1


def mean_reversion_backtest(df: pd.DataFrame, pair: str, params: dict = None) -> dict:
    """
    Mean Reversion strategy on 4H candles.
    
    Entry: RSI < 30 AND price < lower Bollinger Band
    Exit: RSI > 70 OR price > upper Bollinger Band
    Stop: Fixed ATR multiple
    """
    if params is None:
        params = {'rsi_period': 14, 'bb_period': 20, 'bb_std': 2.0, 'atr_period': 14}
    
    if len(df) < 100:
        return {'pair': pair, 'trades': 0, 'error': 'insufficient data'}
    
    # Calculate indicators
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(params['rsi_period']).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(params['rsi_period']).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['bb_mid'] = df['close'].rolling(params['bb_period']).mean()
    df['bb_std'] = df['close'].rolling(params['bb_period']).std()
    df['bb_upper'] = df['bb_mid'] + params['bb_std'] * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - params['bb_std'] * df['bb_std']
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(params['atr_period']).mean()
    
    # Strategy logic
    trades = []
    position = None
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        
        if position is None:
            # Entry conditions
            if (row['rsi'] < 30 and 
                row['close'] < row['bb_lower'] and
                row['volume'] > 0):
                
                entry_price = row['close']
                atr = row['atr']
                
                position = {
                    'entry_price': entry_price,
                    'entry_idx': i,
                    'stop_loss': entry_price - 2.0 * atr,
                    'take_profit': entry_price + 3.0 * atr,
                    'entry_rsi': row['rsi'],
                }
        
        elif position is not None:
            # Exit conditions
            stop_hit = row['low'] <= position['stop_loss']
            tp_hit = row['high'] >= position['take_profit']
            rsi_exit = row['rsi'] > 70
            bb_exit = row['close'] > row['bb_upper']
            
            if stop_hit or tp_hit or rsi_exit or bb_exit:
                if stop_hit:
                    exit_price = position['stop_loss']
                elif tp_hit:
                    exit_price = position['take_profit']
                else:
                    exit_price = row['close']
                
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                
                trades.append({
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'bars_held': i - position['entry_idx'],
                    'exit_type': 'STOP' if stop_hit else 'TP' if tp_hit else 'RSI' if rsi_exit else 'BB',
                })
                
                position = None
    
    # Calculate metrics
    if not trades:
        return {'pair': pair, 'trades': 0}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    return {
        'pair': pair,
        'trades': len(trades),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'total_pnl_pct': sum(pnls),
        'avg_pnl_pct': np.mean(pnls),
        'sharpe': np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0,
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
        'expectancy': np.mean(pnls),
        'max_drawdown': min(pnls) if pnls else 0,
    }


def h3b_backtest(df: pd.DataFrame, pair: str, params: dict = None) -> dict:
    """
    H3-B Volume Ignition strategy.
    
    Entry: RSI crosses above 30 + Volume spike + EMA alignment
    Exit: RSI > 70 OR ATR trailing stop
    """
    if params is None:
        params = {'ema_fast': 9, 'ema_slow': 21, 'rsi_period': 14, 'vol_mult': 1.5}
    
    if len(df) < 100:
        return {'pair': pair, 'trades': 0, 'error': 'insufficient data'}
    
    # Calculate indicators
    df['ema_fast'] = df['close'].ewm(span=params['ema_fast']).mean()
    df['ema_slow'] = df['close'].ewm(span=params['ema_slow']).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(params['rsi_period']).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(params['rsi_period']).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['vol_ma'] = df['volume'].rolling(20).mean()
    
    # ATR for trailing stop
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Strategy
    trades = []
    position = None
    trailing_stop = None
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        if position is None:
            # Entry: RSI crosses above 30, volume spike, EMA bullish
            rsi_cross = prev['rsi'] < 30 and row['rsi'] >= 30
            vol_spike = row['volume'] > params['vol_mult'] * row['vol_ma']
            ema_bull = row['ema_fast'] > row['ema_slow']
            
            if rsi_cross and vol_spike and ema_bull:
                position = {
                    'entry_price': row['close'],
                    'entry_idx': i,
                    'high_since_entry': row['high'],
                }
                trailing_stop = row['close'] - 2.0 * row['atr']
        
        elif position is not None:
            # Update trailing stop
            position['high_since_entry'] = max(position['high_since_entry'], row['high'])
            new_stop = position['high_since_entry'] - 2.0 * row['atr']
            trailing_stop = max(trailing_stop, new_stop)
            
            # Exit conditions
            stop_hit = row['low'] <= trailing_stop
            rsi_exit = row['rsi'] > 70
            
            if stop_hit or rsi_exit:
                exit_price = trailing_stop if stop_hit else row['close']
                pnl_pct = (exit_price / position['entry_price'] - 1) * 100
                
                trades.append({
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'bars_held': i - position['entry_idx'],
                    'exit_type': 'TRAIL' if stop_hit else 'RSI',
                })
                
                position = None
                trailing_stop = None
    
    # Calculate metrics
    if not trades:
        return {'pair': pair, 'trades': 0}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    return {
        'pair': pair,
        'trades': len(trades),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'total_pnl_pct': sum(pnls),
        'avg_pnl_pct': np.mean(pnls),
        'sharpe': np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0,
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
        'expectancy': np.mean(pnls),
        'max_drawdown': min(pnls) if pnls else 0,
    }


def run_fresh_backtests():
    """Run fresh backtests on current market data."""
    print("=" * 80)
    print("FRESH BACKTEST - APRIL 2026")
    print("=" * 80)
    
    # Test pairs from config
    pairs = ['SOL/USDT', 'AVAX/USDT', 'NEAR/USDT', 'LINK/USDT', 'ETH/USDT', 'BTC/USDT']
    
    print("\n[1] KRAKEN MEAN REVERSION (4H)")
    print("-" * 60)
    
    mr_results = []
    for pair in pairs:
        print(f"  Testing {pair}...")
        df = fetch_ohlcv(pair, '4h', days=90)
        if not df.empty:
            result = mean_reversion_backtest(df, pair)
            mr_results.append(result)
            if result['trades'] > 0:
                print(f"    Trades: {result['trades']}, WR: {result['win_rate']:.1%}, PF: {result['profit_factor']:.2f}, PnL: {result['total_pnl_pct']:.1f}%")
            else:
                print(f"    No trades")
        else:
            print(f"    No data")
    
    print("\n[2] JUPITER H3-B (4H)")
    print("-" * 60)
    
    h3b_results = []
    for pair in pairs:
        print(f"  Testing {pair}...")
        df = fetch_ohlcv(pair, '4h', days=90)
        if not df.empty:
            result = h3b_backtest(df, pair)
            h3b_results.append(result)
            if result['trades'] > 0:
                print(f"    Trades: {result['trades']}, WR: {result['win_rate']:.1%}, PF: {result['profit_factor']:.2f}, PnL: {result['total_pnl_pct']:.1f}%")
            else:
                print(f"    No trades")
        else:
            print(f"    No data")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print("\n--- Mean Reversion ---")
    valid_mr = [r for r in mr_results if r['trades'] >= 10]
    if valid_mr:
        avg_wr = np.mean([r['win_rate'] for r in valid_mr])
        avg_pf = np.mean([r['profit_factor'] for r in valid_mr if r['profit_factor'] != np.inf])
        total_trades = sum(r['trades'] for r in valid_mr)
        print(f"  Pairs with 10+ trades: {len(valid_mr)}")
        print(f"  Total trades: {total_trades}")
        print(f"  Avg win rate: {avg_wr:.1%}")
        print(f"  Avg profit factor: {avg_pf:.2f}")
    else:
        print("  No pairs with sufficient trades")
    
    print("\n--- H3-B Volume Ignition ---")
    valid_h3b = [r for r in h3b_results if r['trades'] >= 5]
    if valid_h3b:
        avg_wr = np.mean([r['win_rate'] for r in valid_h3b])
        avg_pf = np.mean([r['profit_factor'] for r in valid_h3b if r['profit_factor'] != np.inf])
        total_trades = sum(r['trades'] for r in valid_h3b)
        print(f"  Pairs with 5+ trades: {len(valid_h3b)}")
        print(f"  Total trades: {total_trades}")
        print(f"  Avg win rate: {avg_wr:.1%}")
        print(f"  Avg profit factor: {avg_pf:.2f}")
    else:
        print("  No pairs with sufficient trades")
    
    # Save results
    import json
    output = {
        'date': datetime.now(timezone.utc).isoformat(),
        'mean_reversion': mr_results,
        'h3b': h3b_results,
    }
    with open(OUTPUT_DIR / 'fresh_backtest_2026_04_14.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print("\nResults saved to data/fresh_backtest_2026_04_14.json")
    
    return mr_results, h3b_results


if __name__ == '__main__':
    run_fresh_backtests()
