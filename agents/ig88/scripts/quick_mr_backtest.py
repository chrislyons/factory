#!/usr/bin/env python3
"""
QUICK MR (Compound Machine) — Short-Duration, High-Leverage Mean Reversion
Walk-forward 5 splits across ETH, LINK, SOL, BTC, AVAX on 240m data.

Entry: RSI<35, close < lower BB, reversal candle (close > open), volume > 1.2x avg
Exit: +2% TP, -1% SL, 3 bars (12h) time stop
Leverage: 3x
Friction: 0.14% round-trip (Jupiter)
Funding: 0.01%/hr * hold_hours
"""

import json
import os
import numpy as np
import pandas as pd

# === CONFIG ===
DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data'
OUTPUT = '/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/quick_mr.json'
FRICTION = 0.0014          # 0.14% round-trip
FUNDING_PER_HR = 0.0001    # 0.01%/hr
LEVERAGE = 3
TP_PCT = 0.02              # 2% take profit
SL_PCT = 0.01              # 1% stop loss
TIME_EXIT_BARS = 3         # 12 hours max (3 x 4h bars)
RSI_THRESH = 35
VOL_MULT = 1.2             # volume > 1.2x average
N_SPLITS = 5

PAIRS = {
    'ETH':  'binance_ETHUSDT_240m_resampled.parquet',
    'LINK': 'binance_LINKUSDT_240m_resampled.parquet',
    'SOL':  'binance_SOLUSDT_240m_resampled.parquet',
    'BTC':  'binance_BTCUSDT_240m_resampled.parquet',
    'AVAX': 'binance_AVAXUSDT_240m_resampled.parquet',
}

def compute_rsi(closes, period=14):
    """Compute RSI."""
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.values

def compute_bollinger(closes, period=20, n_std=2):
    """Compute Bollinger Bands."""
    s = pd.Series(closes)
    sma = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = sma + n_std * std
    lower = sma - n_std * std
    return upper.values, lower.values, sma.values

def run_backtest(df):
    """
    Quick MR backtest.
    Entry: RSI<35, close < lower BB, reversal candle (close > open), volume > 1.2x avg
    Exit: +2% TP, -1% SL, 3 bars time stop
    Leverage: 3x, friction on entry+exit, funding per hour of hold.
    """
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    volumes = df['volume'].values
    n = len(df)

    # Indicators
    rsi = compute_rsi(closes)
    bb_upper, bb_lower, bb_sma = compute_bollinger(closes)
    vol_avg = pd.Series(volumes).rolling(20).mean().values

    # Pre-compute conditions
    reversal_candle = closes > opens  # bullish reversal (green candle)
    vol_ok = volumes > VOL_MULT * vol_avg
    rsi_ok = rsi < RSI_THRESH
    bb_break = closes < bb_lower

    trades = []
    i = 25  # warmup for indicators

    while i < n:
        if (i < n and
            not np.isnan(rsi[i]) and
            not np.isnan(bb_lower[i]) and
            not np.isnan(vol_avg[i]) and
            rsi_ok[i] and
            bb_break[i] and
            reversal_candle[i] and
            vol_ok[i]):

            entry_price = closes[i]
            entry_idx = i
            tp_price = entry_price * (1 + TP_PCT)
            sl_price = entry_price * (1 - SL_PCT)

            exit_price = None
            exit_reason = None
            bars_held = 0

            for j in range(i + 1, min(i + 1 + TIME_EXIT_BARS, n)):
                bars_held = j - entry_idx
                # Check SL first
                if lows[j] <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    i = j + 1
                    break
                if highs[j] >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    i = j + 1
                    break
            else:
                # Time exit
                exit_idx = min(i + TIME_EXIT_BARS, n - 1)
                bars_held = exit_idx - entry_idx
                exit_price = closes[exit_idx]
                exit_reason = 'TIME'
                i = exit_idx + 1

            if exit_price is not None:
                # Raw PnL percentage
                raw_pnl = (exit_price - entry_price) / entry_price
                # Apply leverage
                lev_pnl = raw_pnl * LEVERAGE
                # Subtract friction (applied once at entry+exit)
                hold_hours = bars_held * 4  # 240m = 4h per bar
                funding_cost = FUNDING_PER_HR * hold_hours * LEVERAGE
                net_pnl = lev_pnl - FRICTION - funding_cost

                trades.append({
                    'entry_idx': entry_idx,
                    'entry_price': round(entry_price, 4),
                    'exit_price': round(exit_price, 4),
                    'raw_pnl_pct': round(raw_pnl * 100, 4),
                    'lev_pnl_pct': round(lev_pnl * 100, 4),
                    'net_pnl_pct': round(net_pnl * 100, 4),
                    'friction_pct': round(FRICTION * 100, 4),
                    'funding_pct': round(funding_cost * 100, 4),
                    'exit_reason': exit_reason,
                    'bars_held': bars_held,
                })
                continue
        i += 1

    return trades

def compute_metrics(trades, initial_capital=10000):
    """Compute performance metrics with compounding."""
    if len(trades) == 0:
        return {
            'pf': 0, 'wr': 0, 'n_trades': 0,
            'avg_net_pnl_pct': 0, 'total_return_pct': 0,
            'max_dd_pct': 0, 'final_capital': initial_capital,
            'avg_win_pct': 0, 'avg_loss_pct': 0,
            'tp_exits': 0, 'sl_exits': 0, 'time_exits': 0,
            'avg_bars_held': 0,
        }

    net_pnls = np.array([t['net_pnl_pct'] / 100.0 for t in trades])
    wins = net_pnls[net_pnls > 0]
    losses = net_pnls[net_pnls <= 0]

    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0

    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0)
    wr = len(wins) / len(net_pnls)

    # Compounding equity curve
    equity = [initial_capital]
    for pnl in net_pnls:
        equity.append(equity[-1] * (1 + pnl))
    equity = np.array(equity)

    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    max_dd_pct = dd.max() * 100

    final_capital = equity[-1]
    total_return_pct = (final_capital / initial_capital - 1) * 100

    # Annualize: trades per year from 240m data
    # ~2190 candles/year at 240m, but trade frequency varies
    tp_exits = sum(1 for t in trades if t['exit_reason'] == 'TP')
    sl_exits = sum(1 for t in trades if t['exit_reason'] == 'SL')
    time_exits = sum(1 for t in trades if t['exit_reason'] == 'TIME')

    return {
        'pf': round(pf, 3),
        'wr': round(wr, 3),
        'n_trades': len(trades),
        'avg_net_pnl_pct': round(np.mean([t['net_pnl_pct'] for t in trades]), 4),
        'total_return_pct': round(total_return_pct, 2),
        'max_dd_pct': round(max_dd_pct, 2),
        'final_capital': round(final_capital, 2),
        'avg_win_pct': round(wins.mean() * 100, 4) if len(wins) > 0 else 0,
        'avg_loss_pct': round(losses.mean() * 100, 4) if len(losses) > 0 else 0,
        'tp_exits': tp_exits,
        'sl_exits': sl_exits,
        'time_exits': time_exits,
        'avg_bars_held': round(np.mean([t['bars_held'] for t in trades]), 2),
    }

def walk_forward_single_asset(df, n_splits=5):
    """Run walk-forward validation on a single asset."""
    n = len(df)
    segment_size = n // n_splits
    results = []

    for split in range(n_splits):
        split_start = split * segment_size
        split_end = (split + 1) * segment_size if split < n_splits - 1 else n

        split_data = df.iloc[split_start:split_end].copy()
        split_n = len(split_data)

        is_end = int(split_n * 0.7)
        df_is = split_data.iloc[:is_end]
        df_oos = split_data.iloc[is_end:]

        # Run on IS
        is_trades = run_backtest(df_is)
        is_metrics = compute_metrics(is_trades)

        # Run on OOS
        oos_trades = run_backtest(df_oos)
        oos_metrics = compute_metrics(oos_trades)

        results.append({
            'split': split + 1,
            'is_period': f"{df_is.index[0]} to {df_is.index[-1]}",
            'oos_period': f"{df_oos.index[0]} to {df_oos.index[-1]}",
            'is_candles': len(df_is),
            'oos_candles': len(df_oos),
            'is_metrics': is_metrics,
            'oos_metrics': oos_metrics,
        })

    return results

def annualized_return_from_trades(trades, bars_per_year=2190):
    """Estimate annualized return assuming trades are spread across the period."""
    if len(trades) == 0:
        return 0
    net_pnls = [t['net_pnl_pct'] / 100.0 for t in trades]
    total_bars_held = sum(t['bars_held'] for t in trades)
    # Compound all trade returns
    compound = 1.0
    for pnl in net_pnls:
        compound *= (1 + pnl)
    # Scale to annual: if total_bars_held bars produced compound return,
    # annualized = compound^(bars_per_year / total_bars_held) - 1
    if total_bars_held > 0:
        ann = (compound ** (bars_per_year / total_bars_held) - 1) * 100
    else:
        ann = 0
    return round(ann, 2)

def main():
    print("=" * 70)
    print("QUICK MR (Compound Machine) — Walk-Forward Validation")
    print("=" * 70)
    print(f"  Entry: RSI<{RSI_THRESH}, BB break, reversal candle, vol>{VOL_MULT}x")
    print(f"  Exit: +{TP_PCT*100}% TP, -{SL_PCT*100}% SL, {TIME_EXIT_BARS} bars time stop")
    print(f"  Leverage: {LEVERAGE}x | Friction: {FRICTION*100}% | Funding: {FUNDING_PER_HR*100}%/hr")
    print(f"  Walk-forward: {N_SPLITS} splits, 70/30 IS/OOS")
    print()

    all_results = {}
    all_oos_trades_by_asset = {}

    for pair_name, filename in PAIRS.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  SKIP {pair_name}: file not found {filepath}")
            continue

        print(f"\n{'='*70}")
        print(f"  {pair_name} — {filename}")
        print(f"{'='*70}")

        df = pd.read_parquet(filepath)
        df = df.sort_index()
        print(f"  Data: {len(df)} candles, {df.index[0]} to {df.index[-1]}")

        # Walk-forward
        wf_results = walk_forward_single_asset(df, n_splits=N_SPLITS)

        # Aggregate OOS
        all_oos_trades = []
        split_summaries = []
        for r in wf_results:
            om = r['oos_metrics']
            split_summaries.append({
                'split': r['split'],
                'oos_pf': om['pf'],
                'oos_wr': om['wr'],
                'oos_n_trades': om['n_trades'],
                'oos_return_pct': om['total_return_pct'],
                'oos_max_dd_pct': om['max_dd_pct'],
                'is_pf': r['is_metrics']['pf'],
                'is_wr': r['is_metrics']['wr'],
                'is_n_trades': r['is_metrics']['n_trades'],
            })
            print(f"  Split {r['split']}: IS PF={r['is_metrics']['pf']:.2f} WR={r['is_metrics']['wr']:.2f} N={r['is_metrics']['n_trades']} | "
                  f"OOS PF={om['pf']:.2f} WR={om['wr']:.2f} N={om['n_trades']} Ret={om['total_return_pct']:.1f}% DD={om['max_dd_pct']:.1f}%")

        oos_pfs = [s['oos_pf'] for s in split_summaries if s['oos_n_trades'] > 0]
        oos_wrs = [s['oos_wr'] for s in split_summaries if s['oos_n_trades'] > 0]
        total_oos_trades = sum(s['oos_n_trades'] for s in split_summaries)

        avg_pf = np.mean(oos_pfs) if oos_pfs else 0
        avg_wr = np.mean(oos_wrs) if oos_wrs else 0

        all_results[pair_name] = {
            'splits': wf_results,
            'split_summaries': split_summaries,
            'avg_oos_pf': round(avg_pf, 3),
            'avg_oos_wr': round(avg_wr, 3),
            'total_oos_trades': total_oos_trades,
        }
        all_oos_trades_by_asset[pair_name] = total_oos_trades

        print(f"\n  {pair_name} AGGREGATE: avg OOS PF={avg_pf:.3f}, WR={avg_wr:.3f}, trades={total_oos_trades}")

    # === Cross-asset aggregate ===
    print(f"\n{'='*70}")
    print("CROSS-ASSET AGGREGATE OOS RESULTS")
    print(f"{'='*70}")

    all_avg_pfs = []
    all_avg_wrs = []
    grand_total_trades = 0
    for name, res in all_results.items():
        all_avg_pfs.append(res['avg_oos_pf'])
        all_avg_wrs.append(res['avg_oos_wr'])
        grand_total_trades += res['total_oos_trades']

    cross_avg_pf = np.mean(all_avg_pfs) if all_avg_pfs else 0
    cross_avg_wr = np.mean(all_avg_wrs) if all_avg_wrs else 0

    # Estimate annualized return from aggregate WR and PF
    # At 3x leverage, 2% TP, 1% SL:
    # Win = 2% * 3 - friction - funding ~ 6% - 0.14% - 0.12% = 5.74%
    # Loss = 1% * 3 + friction + funding ~ 3% + 0.14% + 0.06% = 3.20%
    # But actual returns depend on walk-forward results

    # Use a simpler heuristic: assume ~3 trades/week across all assets
    trades_per_week_est = grand_total_trades / max(1, len(all_results)) / (len(df) / (6 * 7))  # rough
    trades_per_year_est = grand_total_trades * (2190 / len(df)) if len(df) > 0 else 0

    # Breakeven analysis
    # Net win per trade at TP: 0.02*3 - 0.0014 - 0.0012 = 0.0574 (5.74%)
    # Net loss per trade at SL: 0.01*3 + 0.0014 + 0.0006 = 0.0320 (3.20%)
    net_win = TP_PCT * LEVERAGE - FRICTION - FUNDING_PER_HR * 4 * LEVERAGE  # ~1 bar avg for TP
    net_loss = SL_PCT * LEVERAGE + FRICTION + FUNDING_PER_HR * 1 * LEVERAGE  # ~0.5 bar avg for SL
    breakeven_wr = net_loss / (net_win + net_loss)

    print(f"  Per-asset avg OOS PF:  {cross_avg_pf:.3f}")
    print(f"  Per-asset avg OOS WR:  {cross_avg_wr:.3f}")
    print(f"  Grand total OOS trades: {grand_total_trades}")
    print(f"  Net win per TP trade:  {net_win*100:.2f}%")
    print(f"  Net loss per SL trade: {net_loss*100:.2f}%")
    print(f"  Breakeven WR:          {breakeven_wr*100:.1f}%")
    print(f"  Trades/year estimate:  {trades_per_year_est:.0f}")

    # Annualized return estimate using compound formula
    if cross_avg_wr > 0 and cross_avg_pf > 0:
        # Expected value per trade
        ev_per_trade = cross_avg_wr * net_win - (1 - cross_avg_wr) * net_loss
        # Compound over estimated trades per year
        if ev_per_trade > 0 and trades_per_year_est > 0:
            compound_annual = ((1 + ev_per_trade) ** trades_per_year_est - 1) * 100
        else:
            compound_annual = 0
    else:
        ev_per_trade = 0
        compound_annual = 0

    print(f"  EV per trade:          {ev_per_trade*100:.3f}%")
    print(f"  Est. annualized return: {compound_annual:.1f}%")

    # Verdict
    if cross_avg_pf >= 1.5 and cross_avg_wr >= breakeven_wr:
        verdict = "VALIDATE"
        recommendation = "Quick MR shows edge above breakeven WR with PF > 1.5. Proceed to paper trading with tight risk limits."
    elif cross_avg_pf >= 1.2:
        verdict = "MARGINAL"
        recommendation = "Edge is marginal. May work with tighter execution. Paper trade on small size with strict monitoring."
    else:
        verdict = "KILL"
        recommendation = "Quick MR does not survive walk-forward validation. Edge does not persist OOS at short duration. Stick with standard MR or abandon."

    print(f"\n  VERDICT: {verdict}")
    print(f"  {recommendation}")

    # === Save ===
    output = {
        'strategy': 'Quick MR (Compound Machine)',
        'description': 'Short-duration mean reversion with 3x leverage, 2% TP, 1% SL, 3-bar time stop',
        'parameters': {
            'entry': f'RSI<{RSI_THRESH}, close < lower BB, reversal candle (green), volume > {VOL_MULT}x avg',
            'tp_pct': TP_PCT * 100,
            'sl_pct': SL_PCT * 100,
            'time_exit_bars': TIME_EXIT_BARS,
            'leverage': LEVERAGE,
            'friction_round_trip': FRICTION,
            'funding_per_hr': FUNDING_PER_HR,
        },
        'data': {
            'timeframe': '240m (resampled from 60m)',
            'pairs': list(PAIRS.keys()),
            'files': PAIRS,
        },
        'walk_forward': {
            'method': f'{N_SPLITS} splits, 70/30 IS/OOS',
            'per_asset': all_results,
        },
        'aggregate': {
            'avg_oos_pf': round(cross_avg_pf, 3),
            'avg_oos_wr': round(cross_avg_wr, 3),
            'grand_total_oos_trades': grand_total_trades,
            'net_win_pct': round(net_win * 100, 3),
            'net_loss_pct': round(net_loss * 100, 3),
            'breakeven_wr': round(breakeven_wr, 3),
            'ev_per_trade_pct': round(ev_per_trade * 100, 4),
            'est_annualized_return_pct': round(compound_annual, 1),
            'trades_per_year_est': round(trades_per_year_est, 0),
        },
        'verdict': verdict,
        'recommendation': recommendation,
        'breakeven_analysis': {
            'formula': 'breakeven_WR = net_loss / (net_win + net_loss)',
            'at_45pct_wr': {
                'pf': round((0.45 * net_win) / (0.55 * net_loss), 3) if net_loss > 0 else 0,
                'ev_per_trade_pct': round((0.45 * net_win - 0.55 * net_loss) * 100, 4),
            },
            'at_50pct_wr': {
                'pf': round((0.50 * net_win) / (0.50 * net_loss), 3) if net_loss > 0 else 0,
                'ev_per_trade_pct': round((0.50 * net_win - 0.50 * net_loss) * 100, 4),
            },
        },
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {OUTPUT}")
    print(f"\nFINAL VERDICT: {verdict}")

if __name__ == '__main__':
    main()
