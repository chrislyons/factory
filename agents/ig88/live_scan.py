#!/usr/bin/env python3
"""
Live Cross-Venue Market Scanner
Fetches real OHLCV data from Binance, runs orchestrator scan, and generates ATR breakout signals.
"""

import sys
import os
import json
import time
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np

sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

BASE_DIR = '/Users/nesbitt/dev/factory/agents/ig88'
DATA_DIR = os.path.join(BASE_DIR, 'data')
OHLCV_DIR = os.path.join(DATA_DIR, 'ohlcv', '1h')
SCANS_DIR = os.path.join(DATA_DIR, 'scans')

os.makedirs(OHLCV_DIR, exist_ok=True)
os.makedirs(SCANS_DIR, exist_ok=True)

SYMBOLS = ['BTC', 'ETH', 'SOL', 'LINK', 'NEAR', 'AVAX', 'ADA', 'DOGE', 'XRP', 'BNB']
ATR_SYMBOLS = ['BTC', 'ETH', 'SOL', 'LINK', 'NEAR']

BINANCE_API = 'https://api.binance.com/api/v3/klines'

# ============================================================
# STEP 1: Fetch Live OHLCV Data from Binance
# ============================================================

def fetch_binance_klines(symbol: str, interval: str = '1h', limit: int = 500) -> pd.DataFrame:
    """Fetch klines from Binance public API."""
    url = f'{BINANCE_API}?symbol={symbol}USDT&interval={interval}&limit={limit}'
    print(f'  Fetching {symbol}USDT from Binance...')
    
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    # Convert types
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    df['trades'] = df['trades'].astype(int)
    
    df.set_index('open_time', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'close_time']]
    
    return df

def fetch_all_symbols():
    """Fetch OHLCV for all symbols and save to parquet."""
    print('=' * 60)
    print('STEP 1: Fetching Live OHLCV Data from Binance')
    print('=' * 60)
    
    results = {}
    for symbol in SYMBOLS:
        try:
            df = fetch_binance_klines(symbol)
            filepath = os.path.join(OHLCV_DIR, f'binance_{symbol}USDT_1h.parquet')
            df.to_parquet(filepath, engine='pyarrow')
            print(f'  Saved {len(df)} bars to {filepath}')
            results[symbol] = df
            time.sleep(0.2)  # Rate limit courtesy
        except Exception as e:
            print(f'  ERROR fetching {symbol}: {e}')
    
    print(f'\nFetched {len(results)}/{len(SYMBOLS)} symbols successfully.')
    return results

# ============================================================
# STEP 2 & 3: Run Orchestrator Scan
# ============================================================

def run_orchestrator_scan():
    """Run the CrossVenueOrchestrator scan."""
    print('\n' + '=' * 60)
    print('STEP 2: Running Cross-Venue Orchestrator Scan')
    print('=' * 60)
    
    try:
        from src.orchestrator import CrossVenueOrchestrator
        orch = CrossVenueOrchestrator()
        report = orch.scan_all()
        return report, True
    except Exception as e:
        print(f'  Orchestrator scan failed: {e}')
        import traceback
        traceback.print_exc()
        return None, False

def print_scan_report(report):
    """Print formatted scan report."""
    print('\n' + '=' * 60)
    print('STEP 3: Scan Report')
    print('=' * 60)
    
    if report is None:
        print('  No report available from orchestrator.')
        return
    
    if isinstance(report, dict):
        # Signals per venue
        if 'signals_by_venue' in report:
            print('\n--- Signals Found Per Venue ---')
            for venue, signals in report.get('signals_by_venue', {}).items():
                print(f'  {venue}: {len(signals)} signals')
        
        # Top 10 signals
        if 'top_signals' in report:
            print('\n--- Top 10 Ranked Signals ---')
            for i, sig in enumerate(report.get('top_signals', [])[:10], 1):
                print(f'  {i}. {sig}')
        
        # Regime states
        if 'regime_states' in report:
            print('\n--- Regime States Per Venue ---')
            for venue, regime in report.get('regime_states', {}).items():
                print(f'  {venue}: {regime}')
        
        # Portfolio heat map
        if 'portfolio_heatmap' in report:
            print('\n--- Portfolio Heat Map ---')
            for key, val in report.get('portfolio_heatmap', {}).items():
                print(f'  {key}: {val}')
        
        # Print full report as JSON for anything else
        print('\n--- Full Report ---')
        try:
            print(json.dumps(report, indent=2, default=str))
        except:
            print(str(report))
    else:
        print(f'  Report type: {type(report)}')
        print(str(report))

# ============================================================
# STEP 4: Manual ATR Breakout Signals
# ============================================================

def compute_atr_breakout(df: pd.DataFrame, atr_period: int = 10) -> dict:
    """Compute ATR and check for breakout signals on the latest bar."""
    df = df.copy()
    
    # True Range
    df['prev_close'] = df['close'].shift(1)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['prev_close']),
            abs(df['low'] - df['prev_close'])
        )
    )
    
    # ATR using EMA (Wilder's smoothing)
    df['atr'] = df['tr'].ewm(alpha=1/atr_period, adjust=False).mean()
    
    # Signal conditions on the LAST completed bar (second to last row since last row might be incomplete)
    # Use the last row that has full data
    latest = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    prev = df.iloc[-3] if len(df) > 2 else df.iloc[-2]
    
    atr_val = latest['atr']
    close_now = latest['close']
    close_prev = prev['close']
    
    # LONG trigger: close < (prev_close - atr * 1.0)  -- dip buy
    long_trigger = close_prev - atr_val * 1.0
    long_signal = close_now < long_trigger
    
    # SHORT trigger: close > (prev_close + atr * 1.5)  -- momentum short
    short_trigger = close_prev + atr_val * 1.5
    short_signal = close_now > short_trigger
    
    return {
        'atr': round(atr_val, 6),
        'close': round(close_now, 6),
        'prev_close': round(close_prev, 6),
        'long_trigger': round(long_trigger, 6),
        'short_trigger': round(short_trigger, 6),
        'long_signal': bool(long_signal),
        'short_signal': bool(short_signal),
        'bar_time': str(latest.name) if hasattr(latest, 'name') else 'N/A',
    }

def run_atr_breakout_scan(data: dict):
    """Run ATR breakout scan on key symbols."""
    print('\n' + '=' * 60)
    print('STEP 4: ATR Breakout Signal Scan (Manual)')
    print('=' * 60)
    
    atr_results = {}
    active_signals = []
    
    for symbol in ATR_SYMBOLS:
        if symbol not in data:
            print(f'  {symbol}: No data available, skipping.')
            continue
        
        try:
            result = compute_atr_breakout(data[symbol])
            atr_results[symbol] = result
            
            signal_str = 'NO SIGNAL'
            if result['long_signal']:
                signal_str = '>>> LONG SIGNAL <<<'
                active_signals.append({'symbol': symbol, 'direction': 'LONG', **result})
            elif result['short_signal']:
                signal_str = '>>> SHORT SIGNAL <<<'
                active_signals.append({'symbol': symbol, 'direction': 'SHORT', **result})
            
            print(f'\n  {symbol}USDT:')
            print(f'    Bar Time:    {result["bar_time"]}')
            print(f'    Close:       {result["close"]}')
            print(f'    Prev Close:  {result["prev_close"]}')
            print(f'    ATR(10):     {result["atr"]}')
            print(f'    Long Trig:   {result["long_trigger"]} (buy if close < this)')
            print(f'    Short Trig:  {result["short_trigger"]} (sell if close > this)')
            print(f'    Status:      {signal_str}')
            
        except Exception as e:
            print(f'  {symbol}: ERROR - {e}')
    
    print(f'\n  Total Active ATR Breakout Signals: {len(active_signals)}')
    return atr_results, active_signals

# ============================================================
# STEP 5: Save Scan Report
# ============================================================

def save_report(orch_report, atr_results, active_signals, data):
    """Save comprehensive scan report to JSON."""
    print('\n' + '=' * 60)
    print('STEP 5: Saving Scan Report')
    print('=' * 60)
    
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(SCANS_DIR, f'live_scan_{timestamp}.json')
    
    # Build summary
    latest_prices = {}
    for sym, df in data.items():
        if len(df) > 0:
            row = df.iloc[-1]
            latest_prices[sym] = {
                'close': round(float(row['close']), 6),
                'high': round(float(row['high']), 6),
                'low': round(float(row['low']), 6),
                'volume': round(float(row['volume']), 2),
                'time': str(row.name),
            }
    
    report = {
        'scan_timestamp': timestamp,
        'scan_datetime_utc': datetime.now(timezone.utc).isoformat(),
        'symbols_scanned': SYMBOLS,
        'symbols_with_data': list(data.keys()),
        'latest_prices': latest_prices,
        'orchestrator_report': orch_report if orch_report else {'status': 'not_available'},
        'atr_breakout_results': atr_results,
        'active_atr_signals': active_signals,
        'summary': {
            'total_symbols': len(SYMBOLS),
            'symbols_fetched': len(data),
            'active_atr_signals': len(active_signals),
            'signal_symbols': [s['symbol'] for s in active_signals],
        }
    }
    
    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f'  Report saved to: {filepath}')
    return filepath

# ============================================================
# MAIN
# ============================================================

def main():
    print(f'LIVE CROSS-VENUE MARKET SCAN')
    print(f'Started: {datetime.now(timezone.utc).isoformat()}')
    print(f'Python: {sys.executable}')
    print()
    
    # Step 1: Fetch data
    data = fetch_all_symbols()
    
    if not data:
        print('ERROR: No data fetched. Cannot proceed.')
        return
    
    # Step 2 & 3: Orchestrator scan
    orch_report, orch_success = run_orchestrator_scan()
    print_scan_report(orch_report)
    
    # Step 4: ATR Breakout signals
    atr_results, active_signals = run_atr_breakout_scan(data)
    
    # Step 5: Save report
    filepath = save_report(orch_report, atr_results, active_signals, data)
    
    # Final summary
    print('\n' + '=' * 60)
    print('SCAN COMPLETE - SUMMARY')
    print('=' * 60)
    print(f'  Symbols fetched: {len(data)}/{len(SYMBOLS)}')
    print(f'  Orchestrator:    {"OK" if orch_success else "FAILED"}')
    print(f'  ATR Signals:     {len(active_signals)} active')
    for sig in active_signals:
        print(f'    -> {sig["symbol"]} {sig["direction"]} (ATR={sig["atr"]})')
    print(f'  Report:          {filepath}')
    print(f'  Finished:        {datetime.now(timezone.utc).isoformat()}')

if __name__ == '__main__':
    main()
