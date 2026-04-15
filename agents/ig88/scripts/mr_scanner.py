#!/usr/bin/env python3
"""
Mean Reversion Scanner — Automated Paper Trading Cycle
=======================================================
Scans 5 pairs (SOL, AVAX, ETH, LINK, BTC) for MR 4h signals.
NEAR disabled (0W/7L paper record).

Validated strategy (2561 trades, PF 3.01):
  Entry: RSI(14)<35, Close<BB_lower(1σ), Reversal candle (C>O), Vol>1.2x SMA20
  Exit: Adaptive stops/targets by ATR regime
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Paths
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.jsonl"
LOG_MD_PATH = DATA_DIR / "paper_trading_log_20260413.md"
SCRATCHPAD_PATH = Path("/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/scratchpad.md")

# Validated pairs
PAIRS = ['SOL', 'AVAX', 'ETH', 'LINK', 'BTC']  # NEAR disabled

# Validated MR parameters
RSI_THRESHOLD = 35
BB_STD = 1.0
VOL_MULTIPLIER = 1.2
POSITION_SIZE_USD = 500.0
FRICTION_PCT = 0.005  # Kraken spot maker round-trip

# Adaptive exit parameters by ATR regime
def get_exit_params(atr_pct: float) -> tuple[float, float]:
    """Get stop% and target% based on ATR regime."""
    if atr_pct < 0.02:
        return 0.015, 0.03    # Low Vol: 1.5% stop, 3% target
    elif atr_pct < 0.04:
        return 0.01, 0.075    # Mid Vol: 1% stop, 7.5% target
    else:
        return 0.005, 0.075   # High Vol: 0.5% stop, 7.5% target


def load_pair_data(pair: str) -> pd.DataFrame:
    """Load 4h OHLCV data for a pair."""
    for suffix in [f'{pair}USDT_240m', f'{pair}_USDT_240m']:
        path = DATA_DIR / f'binance_{suffix}.parquet'
        if path.exists():
            df = pd.read_parquet(path)
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index()
                df = df.rename(columns={df.columns[0]: 'timestamp'})
            df = df.sort_values('timestamp').reset_index(drop=True)
            return df
    raise FileNotFoundError(f"No 240m data for {pair}")


def compute_indicators(df: pd.DataFrame) -> dict:
    """Compute MR indicators."""
    c = df['close'].values.astype(float)
    o = df['open'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    v = df['volume'].values.astype(float)

    # RSI(14)
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values

    # Bollinger Bands (20, 1σ)
    sma20 = pd.Series(c).rolling(20).mean().values
    std20 = pd.Series(c).rolling(20).std().values
    bb_lower = sma20 - std20 * BB_STD

    # Volume ratio
    vol_sma20 = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma20

    # ATR(14)
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]),
                               np.abs(l[1:] - c[:-1])))
    atr = np.full(len(c), np.nan)
    if len(tr) >= 14:
        atr_vals = pd.Series(tr).rolling(14).mean().values
        atr[1:] = atr_vals
    atr_pct = atr / c

    return {
        'c': c, 'o': o, 'h': h, 'l': l, 'v': v,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'bb_lower': bb_lower, 'vol_ratio': vol_ratio,
        'atr': atr, 'atr_pct': atr_pct,
    }


def check_mr_signal(ind: dict) -> dict | None:
    """Check for MR signal on latest closed bar."""
    i = len(ind['c']) - 2
    if i < 20 or i >= len(ind['c']):
        return None

    rsi = ind['rsi'][i]
    c = ind['c'][i]
    o = ind['o'][i]
    bb_lower = ind['bb_lower'][i]
    vol_ratio = ind['vol_ratio'][i]
    atr_pct = ind['atr_pct'][i]

    if np.isnan(rsi) or np.isnan(bb_lower) or np.isnan(vol_ratio) or np.isnan(atr_pct):
        return None

    if rsi < RSI_THRESHOLD and c < bb_lower and c > o and vol_ratio > VOL_MULTIPLIER:
        stop_pct, target_pct = get_exit_params(atr_pct)
        entry_price = ind['o'][i + 1]  # T1 entry

        return {
            'entry_price': float(entry_price),
            'stop_price': float(entry_price * (1 - stop_pct)),
            'target_price': float(entry_price * (1 + target_pct)),
            'stop_pct': stop_pct,
            'target_pct': target_pct,
            'rsi': float(rsi),
            'bb_position': float((c - bb_lower) / ind['std20'][i]) if ind['std20'][i] > 0 else 0,
            'vol_ratio': float(vol_ratio),
            'atr_pct': float(atr_pct),
            'confidence': max(0.0, min(1.0, 1.0 - (rsi / RSI_THRESHOLD))),
        }
    return None


def load_open_trades() -> list[dict]:
    """Load open paper trades (outcome is None/null)."""
    if not PAPER_TRADES_PATH.exists():
        return []
    open_trades = []
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trade = json.loads(line)
                    if trade.get('outcome') is None:
                        open_trades.append(trade)
                except json.JSONDecodeError:
                    pass
    return open_trades


def load_all_trades() -> list[dict]:
    if not PAPER_TRADES_PATH.exists():
        return []
    trades = []
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return trades


def save_all_trades(trades: list[dict]):
    with open(PAPER_TRADES_PATH, 'w') as f:
        for t in trades:
            f.write(json.dumps(t) + '\n')


def close_trade(trade: dict, exit_price: float, exit_reason: str) -> dict:
    """Close a paper trade."""
    entry = trade['entry_price']
    size = trade.get('position_size_usd', POSITION_SIZE_USD)
    side = trade.get('side', 'long')
    leverage = trade.get('leverage', 1.0)

    if side in ('long', 'buy'):
        gross_pct = (exit_price - entry) / entry
    else:
        gross_pct = (entry - exit_price) / entry

    gross_pct *= leverage
    net_pct = gross_pct - FRICTION_PCT
    net_usd = net_pct * size

    trade['exit_price'] = round(exit_price, 6)
    trade['exit_timestamp'] = datetime.now(timezone.utc).isoformat()
    trade['exit_reason'] = exit_reason
    trade['pnl_pct'] = round(gross_pct * 100, 4)
    trade['pnl_usd'] = round(net_usd, 4)

    if exit_reason == 'stop_loss':
        trade['outcome'] = 'stop'
    elif exit_reason == 'take_profit':
        trade['outcome'] = 'target'
    elif exit_reason == 'time_stop':
        trade['outcome'] = 'time_stop'
    else:
        trade['outcome'] = 'win' if net_pct > 0 else 'loss'

    return trade


def main():
    now = datetime.now(timezone.utc)
    session_time = now.strftime("%Y-%m-%d %H:%M UTC")
    print(f"{'='*60}")
    print(f"MR Scanner — {session_time}")
    print(f"{'='*60}")

    results = {
        'session': session_time,
        'positions_closed': [],
        'signals_found': [],
        'trades_opened': [],
    }

    # --- Step 1: Load data and check open positions ---
    print(f"\n[Step 1] Loading data & checking positions...")

    # Load all pair data
    pair_data = {}
    for pair in PAIRS:
        try:
            pair_data[pair] = load_pair_data(pair)
        except FileNotFoundError as e:
            print(f"  ✗ {pair}: {e}")

    # Get latest closed bar prices and indicators
    current_prices = {}
    current_atrs = {}
    for pair, df in pair_data.items():
        ind = compute_indicators(df)
        i = len(ind['c']) - 2
        current_prices[pair] = float(ind['c'][i])
        current_atrs[pair] = float(ind['atr_pct'][i])

    print(f"  Latest prices: {', '.join(f'{k}=${v:.2f}' for k, v in current_prices.items())}")

    # Check open positions
    open_trades = load_open_trades()
    print(f"  Open positions: {len(open_trades)}")

    all_trades = load_all_trades()
    closed_this_cycle = 0

    for trade in open_trades:
        pair_raw = trade.get('pair', '')
        pair = pair_raw.replace('-PERP', '').replace('/USD', '').replace('USDT', '')
        price = current_prices.get(pair)
        if price is None:
            print(f"  ⚠ No price for {pair_raw}")
            continue

        entry = trade['entry_price']
        side = trade.get('side', 'long')
        stop = trade.get('stop_price') or trade.get('stop_level')
        target = trade.get('target_price') or trade.get('target_level')

        exited = False
        # Check stop
        if stop and side in ('long', 'buy') and price <= stop:
            close_trade(trade, price, 'stop_loss')
            print(f"  ✗ STOP: {pair_raw} ${entry:.4f} → ${price:.4f} ({trade['pnl_pct']:+.2f}%)")
            exited = True
        elif stop and side in ('short', 'sell') and price >= stop:
            close_trade(trade, price, 'stop_loss')
            print(f"  ✗ STOP: {pair_raw} ${entry:.4f} → ${price:.4f} ({trade['pnl_pct']:+.2f}%)")
            exited = True
        # Check target
        elif target and side in ('long', 'buy') and price >= target:
            close_trade(trade, price, 'take_profit')
            print(f"  ✓ TARGET: {pair_raw} ${entry:.4f} → ${price:.4f} ({trade['pnl_pct']:+.2f}%)")
            exited = True
        elif target and side in ('short', 'sell') and price <= target:
            close_trade(trade, price, 'take_profit')
            print(f"  ✓ TARGET: {pair_raw} ${entry:.4f} → ${price:.4f} ({trade['pnl_pct']:+.2f}%)")
            exited = True

        if exited:
            results['positions_closed'].append(trade)
            closed_this_cycle += 1
            # Update in all_trades list
            for i, t in enumerate(all_trades):
                if t.get('trade_id') == trade.get('trade_id'):
                    all_trades[i] = trade
                    break
        else:
            pnl = ((price - entry) / entry * 100) if side in ('long',) else ((entry - price) / entry * 100)
            print(f"  → {pair_raw}: entry ${entry:.4f}, now ${price:.4f} ({pnl:+.2f}%)")

    if closed_this_cycle > 0:
        save_all_trades(all_trades)
        print(f"  Saved {closed_this_cycle} closed trades")

    # Refresh open pairs
    open_trades = load_open_trades()
    open_pairs = {t.get('pair', '').replace('-PERP', '').replace('/USD', '') for t in open_trades}

    # --- Step 2: Scan for MR signals ---
    print(f"\n[Step 2] Scanning {len(pair_data)} pairs for MR signals...")

    for pair in PAIRS:
        if pair not in pair_data:
            continue

        ind = compute_indicators(pair_data[pair])
        i = len(ind['c']) - 2

        signal = check_mr_signal(ind)

        if signal is None:
            rsi_val = ind['rsi'][i]
            vol_val = ind['vol_ratio'][i]
            c_val = ind['c'][i]
            bb_val = ind['bb_lower'][i]
            bb_status = "BELOW" if c_val < bb_val else "ABOVE"
            rev = "YES" if c_val > ind['o'][i] else "NO"
            print(f"  — {pair}: RSI={rsi_val:.1f}, Vol={vol_val:.1f}x, BB={bb_status}, Rev={rev} — no signal")
        else:
            if pair in open_pairs:
                print(f"  ⚠ {pair}: SIGNAL but already open — skipping")
                continue

            results['signals_found'].append({'pair': pair, **signal})
            print(f"  ★ {pair}: MR SIGNAL!")
            print(f"    RSI={signal['rsi']:.1f}, Vol={signal['vol_ratio']:.1f}x, BB={signal['bb_position']:.2f}σ")
            print(f"    Entry=${signal['entry_price']:.4f}, Stop=${signal['stop_price']:.4f} ({signal['stop_pct']*100:.1f}%), Target=${signal['target_price']:.4f} ({signal['target_pct']*100:.1f}%)")

    # --- Step 3: Execute new trades ---
    print(f"\n[Step 3] Executing...")
    MAX_POS = 5
    current_open = len(open_trades)

    if not results['signals_found']:
        print("  No new signals to execute")
    else:
        for sig in results['signals_found']:
            if current_open >= MAX_POS:
                print(f"  ⚠ Max positions ({MAX_POS}) reached — skipping {sig['pair']}")
                continue

            pair = sig['pair']
            trade_id = f"paper_{now.strftime('%Y%m%d%H%M%S')}_{pair}_MR"
            trade = {
                'trade_id': trade_id,
                'entry_timestamp': now.isoformat(),
                'exit_timestamp': None,
                'venue': 'paper',
                'strategy': 'mean_reversion',
                'pair': f"{pair}-PERP",
                'side': 'long',
                'entry_price': sig['entry_price'],
                'stop_price': sig['stop_price'],
                'target_price': sig['target_price'],
                'stop_level': sig['stop_price'],
                'target_level': sig['target_price'],
                'position_size_usd': POSITION_SIZE_USD,
                'leverage': 1.0,
                'exit_price': None,
                'exit_reason': None,
                'outcome': None,
                'pnl_pct': None,
                'pnl_usd': None,
                'regime_state': 'RANGING',
                'notes': f"RSI={sig['rsi']:.1f}, Vol={sig['vol_ratio']:.1f}x, BB={sig['bb_position']:.2f}σ",
            }

            with open(PAPER_TRADES_PATH, 'a') as f:
                f.write(json.dumps(trade) + '\n')

            results['trades_opened'].append(trade)
            current_open += 1
            print(f"  ✓ OPENED: {trade_id}")
            print(f"    {pair} long @ ${sig['entry_price']:.4f}")
            print(f"    Stop: ${sig['stop_price']:.4f} | Target: ${sig['target_price']:.4f}")

    # --- Step 4: Summary ---
    all_trades = load_all_trades()
    # Closed trades have an outcome that is not None
    closed_trades = [t for t in all_trades if t.get('outcome') not in (None,)]
    open_trades = [t for t in all_trades if t.get('outcome') is None]

    wins = [t for t in closed_trades if t.get('outcome') in ('win', 'target')]
    losses = [t for t in closed_trades if t.get('outcome') in ('loss', 'stop', 'time_stop')]
    total_pnl = sum(t.get('pnl_usd', 0) or 0 for t in closed_trades)
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    portfolio = 10000 + total_pnl

    print(f"\n{'='*60}")
    print(f"SUMMARY — {session_time}")
    print(f"{'='*60}")
    print(f"  Closed: {len(closed_trades)} ({len(wins)}W / {len(losses)}L)")
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  Realized P&L: ${total_pnl:+.2f}")
    print(f"  Portfolio: ${portfolio:,.2f}")
    print(f"  Open: {len(open_trades)}")
    for t in open_trades:
        sym = t.get('pair', '?')
        print(f"    - {sym} @ ${t.get('entry_price', 0):.4f}")
    print(f"  Signals: {len(results['signals_found'])}")
    print(f"  Opened: {len(results['trades_opened'])}")
    print(f"  Closed this cycle: {len(results['positions_closed'])}")

    # --- Step 5: Update log file ---
    print(f"\n[Step 5] Updating logs...")

    log_entry = [
        f"",
        f"---",
        f"## Session Scan — {session_time}",
        f"",
    ]

    if results['positions_closed']:
        log_entry.append(f"### Positions Closed ({len(results['positions_closed'])})")
        for t in results['positions_closed']:
            sym = t.get('pair', '?')
            pnl = t.get('pnl_pct', 0)
            reason = t.get('exit_reason', '?')
            log_entry.append(f"| {sym} | {reason} | {pnl:+.2f}% | ${t.get('pnl_usd', 0):+.2f} |")
        log_entry.append("")

    if results['signals_found']:
        log_entry.append(f"### MR Signals ({len(results['signals_found'])})")
        for sig in results['signals_found']:
            log_entry.append(f"- **{sig['pair']}**: RSI={sig['rsi']:.1f}, Vol={sig['vol_ratio']:.1f}x, BB={sig['bb_position']:.2f}σ")
        log_entry.append("")

    if results['trades_opened']:
        log_entry.append(f"### Trades Opened ({len(results['trades_opened'])})")
        for t in results['trades_opened']:
            log_entry.append(f"| {t['pair']} | long | ${t['entry_price']:.4f} | ${t['stop_price']:.4f} | ${t['target_price']:.4f} |")
        log_entry.append("")

    if not results['signals_found'] and not results['positions_closed']:
        log_entry.append(f"### No Action — All pairs neutral")

    log_entry.extend([
        f"",
        f"### Cumulative",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Closed | {len(closed_trades)} ({len(wins)}W / {len(losses)}L) |",
        f"| Win Rate | {win_rate:.1f}% |",
        f"| P&L | **${total_pnl:+.2f}** |",
        f"| Portfolio | ${portfolio:,.2f} |",
        f"| Open | {len(open_trades)} |",
        f"",
    ])

    with open(LOG_MD_PATH, 'a') as f:
        f.write('\n'.join(log_entry))
    print(f"  Updated {LOG_MD_PATH}")

    # --- Step 6: Update scratchpad ---
    open_str = ""
    for t in open_trades:
        open_str += f"\n- {t.get('pair','?')} @ ${t.get('entry_price',0):.4f}"

    scratchpad_update = f"""
### MR Scanner — {session_time}
- Closed: {len(results['positions_closed'])} | Signals: {len(results['signals_found'])} | Opened: {len(results['trades_opened'])}
- Portfolio: ${portfolio:,.2f} | Open: {len(open_trades)}{open_str if open_str else ' (flat)'}
"""
    with open(SCRATCHPAD_PATH, 'a') as f:
        f.write(scratchpad_update)
    print(f"  Updated {SCRATCHPAD_PATH}")

    print(f"\nDone.")
    return results


if __name__ == '__main__':
    main()
