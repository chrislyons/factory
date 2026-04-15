"""
Volume & Volatility Distribution Analysis
==========================================
Test: Do volume/volatility patterns cluster at candle boundaries?

Hypothesis: If many bots act at candle close (:00), we should see:
1. Volume spikes at candle open/close vs mid-candle
2. Higher volatility (ATR%) at boundaries
3. More "false signals" at boundaries (higher whipsaw rate)

This tests whether there IS bot clustering, and whether we can exploit it.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

def load_15m_data(pair='SOLUSDT'):
    """Load 15m data for fine-grained volume analysis."""
    path = DATA_DIR / f'binance_{pair}_15m.parquet'
    if not path.exists():
        # Try alternative names
        for suffix in ['15m', '1m', '5m']:
            path = DATA_DIR / f'binance_{pair}_{suffix}.parquet'
            if path.exists():
                df = pd.read_parquet(path)
                print(f"  Loaded {pair} {suffix}: {len(df)} bars")
                return df, suffix
        print(f"  No 15m/1m/5m data for {pair}")
        return None, None
    
    df = pd.read_parquet(path)
    print(f"  Loaded {pair} 15m: {len(df)} bars")
    return df, '15m'

def analyze_candle_distribution(df, suffix):
    """
    Analyze how volume/volatility is distributed WITHIN the 4h candle.
    
    Group bars by their position within the 4h candle:
    - Position 0: 0-15min (candle open)
    - Position 1: 15-30min
    - Position 2: 30-45min
    - Position 3: 45-60min
    - ...
    - Position 15: 3h45m-4h (candle close)
    
    For 15m data: 16 positions in a 4h candle
    """
    df = df.copy()
    
    # Determine bar position within 4h candle
    if suffix == '15m':
        bars_per_4h = 16
    elif suffix == '5m':
        bars_per_4h = 48
    elif suffix == '1m':
        bars_per_4h = 240
    else:
        return None
    
    # Get minute of day for each bar
    df['minute'] = df.index.hour * 60 + df.index.minute
    
    # Position within 4h candle (0-15 for 15m bars)
    # 4h candles start at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
    df['candle_position'] = ((df['minute'] % 240) // (240 // bars_per_4h)).astype(int)
    
    # Compute per-bar metrics
    df['bar_range'] = (df['high'] - df['low']) / df['close'] * 100  # % range
    df['body_pct'] = abs(df['close'] - df['open']) / df['close'] * 100  # body size
    df['upper_wick'] = (df['high'] - df[['close', 'open']].max(axis=1)) / df['close'] * 100
    df['lower_wick'] = (df[['close', 'open']].min(axis=1) - df['low']) / df['close'] * 100
    
    # Compute volume relative to 20-bar average
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma20']
    
    return df, bars_per_4h

def print_distribution_analysis(df, bars_per_4h, pair_name):
    """Print volume/volatility by position within candle."""
    
    print(f"\n{pair_name} Volume Distribution (% of avg):")
    print(f"{'Pos':>4} {'Time':>8} {'Vol%':>6} {'Range%':>7} {'Body%':>7} {'Samples':>8}")
    print("-" * 45)
    
    results = []
    for pos in range(bars_per_4h):
        pos_data = df[df['candle_position'] == pos]
        if len(pos_data) < 50:
            continue
        
        minute_start = pos * (240 // bars_per_4h)
        hour = minute_start // 60
        minute = minute_start % 60
        time_str = f"+{hour}:{minute:02d}"
        
        vol_avg = pos_data['vol_ratio'].mean() * 100
        range_avg = pos_data['bar_range'].mean()
        body_avg = pos_data['body_pct'].mean()
        samples = len(pos_data)
        
        results.append({
            'pos': pos,
            'time': time_str,
            'vol_pct': vol_avg,
            'range_pct': range_avg,
            'body_pct': body_avg,
            'samples': samples,
        })
        
        # Visual indicator
        vol_bar = '#' * int(vol_avg / 5)
        print(f"{pos:4d} {time_str:>8} {vol_avg:5.1f}% {range_avg:6.3f}% {body_avg:6.3f}% {samples:8d} {vol_bar}")
    
    return results

def test_signal_quality_by_position(df, bars_per_4h):
    """
    Test if signals at different positions within the candle have different quality.
    
    We need 4h indicators + 15m position data.
    For simplicity, we'll use the 15m data to compute 4h indicators.
    """
    # Resample to 4h
    ohlcv_4h = df.resample('4h').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    # RSI
    delta = ohlcv_4h['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    ohlcv_4h['rsi'] = (100 - (100 / (1 + gain / loss)))
    
    # BB
    ohlcv_4h['sma20'] = ohlcv_4h['close'].rolling(20).mean()
    ohlcv_4h['std20'] = ohlcv_4h['close'].rolling(20).std()
    ohlcv_4h['bb_lower'] = ohlcv_4h['sma20'] - ohlcv_4h['std20']
    ohlcv_4h['bb_upper'] = ohlcv_4h['sma20'] + ohlcv_4h['std20']
    
    # ATR
    tr = pd.concat([
        ohlcv_4h['high'] - ohlcv_4h['low'],
        (ohlcv_4h['high'] - ohlcv_4h['close'].shift()).abs(),
        (ohlcv_4h['low'] - ohlcv_4h['close'].shift()).abs()
    ], axis=1).max(axis=1)
    ohlcv_4h['atr_pct'] = (tr.rolling(14).mean() / ohlcv_4h['close']) * 100
    
    # For each 4h candle, find the FIRST 15m bar that triggered the signal
    # and see where in the candle it occurred
    
    signal_positions = {'long': [], 'short': []}
    
    for i in range(20, len(ohlcv_4h) - 1):
        row = ohlcv_4h.iloc[i]
        
        if pd.isna(row['rsi']):
            continue
        
        # LONG signal
        if row['rsi'] < 35 and row['close'] < row['bb_lower']:
            candle_start = ohlcv_4h.index[i]
            candle_end = candle_start + pd.Timedelta(hours=4)
            
            # Find which 15m bar first went below BB
            mask = (df.index >= candle_start) & (df.index < candle_end)
            candle_15m = df[mask]
            
            for j, (_, bar) in enumerate(candle_15m.iterrows()):
                if bar['close'] < row['bb_lower']:
                    position = j / bars_per_4h  # 0 to 1
                    signal_positions['long'].append(position)
                    break
        
        # SHORT signal
        elif row['rsi'] > 65 and row['close'] > row['bb_upper']:
            candle_start = ohlcv_4h.index[i]
            candle_end = candle_start + pd.Timedelta(hours=4)
            
            mask = (df.index >= candle_start) & (df.index < candle_end)
            candle_15m = df[mask]
            
            for j, (_, bar) in enumerate(candle_15m.iterrows()):
                if bar['close'] > row['bb_upper']:
                    position = j / bars_per_4h
                    signal_positions['short'].append(position)
                    break
    
    return signal_positions

print("="*80)
print("VOLUME & VOLATILITY DISTRIBUTION ANALYSIS")
print("="*80)
print("\nHypothesis: Bot clustering at candle boundaries creates exploitable patterns.")
print("Evidence would be: higher volume/volatility at candle open/close.\n")

pairs = ['SOLUSDT', 'BTCUSDT', 'ETHUSDT']

all_volume_results = {}
all_signal_positions = {}

for pair in pairs:
    print(f"\n{'='*60}")
    print(f"  {pair}")
    print(f"{'='*60}")
    
    df, suffix = load_15m_data(pair)
    if df is None:
        continue
    
    result = analyze_candle_distribution(df, suffix)
    if result is None:
        print(f"  Cannot analyze - need 15m or finer data")
        continue
    
    df_analyzed, bars_per_4h = result
    volume_results = print_distribution_analysis(df_analyzed, bars_per_4h, pair)
    all_volume_results[pair] = volume_results
    
    # Signal position analysis
    print(f"\n  Analyzing where signals first trigger within candles...")
    signal_positions = test_signal_quality_by_position(df_analyzed, bars_per_4h)
    all_signal_positions[pair] = signal_positions
    
    for sig_type, positions in signal_positions.items():
        if positions:
            print(f"  {sig_type.upper()} signals: {len(positions)} total")
            print(f"    Avg position: {np.mean(positions)*100:.1f}% through candle")
            print(f"    Early (0-25%): {sum(1 for p in positions if p < 0.25)} ({sum(1 for p in positions if p < 0.25)/len(positions)*100:.1f}%)")
            print(f"    Mid (25-75%): {sum(1 for p in positions if 0.25 <= p < 0.75)} ({sum(1 for p in positions if 0.25 <= p < 0.75)/len(positions)*100:.1f}%)")
            print(f"    Late (75-100%): {sum(1 for p in positions if p >= 0.75)} ({sum(1 for p in positions if p >= 0.75)/len(positions)*100:.1f}%)")

print("\n" + "="*80)
print("AGGREGATE VOLUME DISTRIBUTION")
print("="*80)

# Aggregate across pairs
if all_volume_results:
    print(f"\n{'Position':>10} {'Avg Vol%':>10} {'Interpretation':>30}")
    print("-" * 55)
    
    # Get average volume by position across all pairs
    max_pos = max(len(r) for r in all_volume_results.values())
    
    for pos in range(min(max_pos, 16)):  # First 16 positions (first 4h worth)
        vol_values = []
        for pair, results in all_volume_results.items():
            if pos < len(results):
                vol_values.append(results[pos]['vol_pct'])
        
        if vol_values:
            avg_vol = np.mean(vol_values)
            
            if pos == 0:
                interpretation = "Candle OPEN"
            elif pos <= 2:
                interpretation = "Early candle"
            elif pos <= 13:
                interpretation = "Mid candle"
            elif pos == 14:
                interpretation = "Late candle"
            else:
                interpretation = "Candle CLOSE"
            
            bar = '#' * int(avg_vol / 3)
            print(f"{pos:10d} {avg_vol:9.1f}% {interpretation:>30} {bar}")

print("\n" + "="*80)
print("KEY FINDINGS")
print("="*80)
print("""
Look for:
1. Volume SPIKE at position 0 (candle open) or 15 (candle close)
2. Volume DIP in mid-candle (positions 6-10)
3. Signal triggers clustered at certain positions

If volume is uniform: NO bot clustering (no edge to exploit)
If volume spikes at boundaries: Bot clustering exists (potential edge)
""")
