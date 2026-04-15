#!/usr/bin/env python3
"""
Leveraged Momentum Breakout Backtest for Jupiter Perps
Tests 1x, 3x, 5x, 10x leverage with liquidation simulation
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT_PATH = DATA_DIR / "edge_discovery" / "leveraged_momentum.json"

PAIRS = {
    "SOL": "binance_SOLUSDT_60m.parquet",
    "AVAX": "binance_AVAXUSDT_60m.parquet",
    "ETH": "binance_ETHUSDT_60m.parquet",
    "LINK": "binance_LINKUSDT_60m.parquet",
    "BTC": "binance_BTCUSDT_60m.parquet",
}

FRICTION = 0.0014  # 0.14% round-trip
FUNDING_RATE_PER_HOUR = 0.0001  # 0.01% per hour
LEVERAGE_LEVELS = [1, 3, 5, 10]
MAINTENANCE_MARGIN = 0.005  # 0.5% typical for Jupiter perps
N_SPLITS = 5


def load_and_resample(filename):
    """Load 60m data and resample to 240m (4h)."""
    df = pd.read_parquet(DATA_DIR / filename)
    df.index = pd.to_datetime(df.index, utc=True)
    
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    df4h = df.resample("4h").agg(agg).dropna()
    return df4h


def compute_indicators(df):
    """Compute strategy indicators."""
    df = df.copy()
    # HH20: 20-bar high
    df["hh20"] = df["high"].rolling(20).max()
    # SMA20 volume
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    # ADX(14)
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    plus_dm[(plus_dm < minus_dm)] = 0
    minus_dm[(minus_dm < plus_dm)] = 0
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df["adx"] = dx.rolling(14).mean()
    
    # SMA10 for exit
    df["sma10"] = close.rolling(10).mean()
    # ATR14 for trailing stop
    df["atr14"] = tr.rolling(14).mean()
    
    return df.dropna()


def generate_signals(df):
    """
    Generate entry/exit signals.
    Entry: Close > HH20 + Volume > 2.0x SMA(20) + ADX(14) > 30
    Exit: Close < SMA(10) OR Trailing Stop at 1.0x ATR(14)
    """
    df = df.copy()
    # Entry signal on bar i: conditions met at bar i, enter at bar i+1 open
    entry_cond = (
        (df["close"] > df["hh20"].shift(1)) &
        (df["volume"] > 2.0 * df["vol_sma20"]) &
        (df["adx"] > 30)
    )
    df["entry_signal"] = entry_cond.astype(int)
    return df


def backtest_with_leverage(df, leverage, split_idx=None, n_splits=5):
    """
    Walk-forward backtest with leverage simulation.
    Returns dict of metrics.
    """
    n = len(df)
    
    # Walk-forward splits: use expanding window for training, fixed for test
    if split_idx is not None:
        # Split into n_splits roughly equal test periods
        test_size = n // (n_splits + 1)
        train_end = test_size * (split_idx + 1)
        test_start = train_end
        test_end = min(test_start + test_size, n)
        if test_end - test_start < 50:
            return None
        test_df = df.iloc[test_start:test_end].copy()
    else:
        test_df = df.copy()
    
    close = test_df["close"].values
    high = test_df["high"].values
    low = test_df["low"].values
    entry_signals = test_df["entry_signal"].values
    sma10 = test_df["sma10"].values
    atr14 = test_df["atr14"].values
    timestamps = test_df.index
    
    # Trade simulation
    trades = []
    in_position = False
    entry_price = 0
    entry_bar = 0
    peak_price = 0
    trailing_stop = 0
    
    liquidation_threshold = (1.0 / leverage - MAINTENANCE_MARGIN) if leverage > 1 else -999
    
    for i in range(1, len(close)):
        if not in_position:
            # Check entry signal from previous bar
            if entry_signals[i - 1] == 1:
                entry_price = close[i]  # Enter at current bar's close (conservative)
                # Actually enter at next open approximated by current close
                entry_bar = i
                peak_price = entry_price
                trailing_stop = entry_price - atr14[i] if leverage > 1 else 0
                in_position = True
        else:
            bars_held = i - entry_bar
            current_price = close[i]
            current_low = low[i]
            
            # Update peak and trailing stop
            if current_price > peak_price:
                peak_price = current_price
                trailing_stop = peak_price - atr14[i]
            
            # Check liquidation for leveraged positions
            if leverage > 1:
                # Unleveraged return from entry
                raw_return = (current_price - entry_price) / entry_price
                # Leveraged PnL including funding
                leveraged_return = raw_return * leverage - FUNDING_RATE_PER_HOUR * bars_held * 4  # 4 hours per bar
                # Check if margin is wiped out
                if leveraged_return <= -liquidation_threshold:
                    # Liquidated! Loss = margin portion
                    # Actually if leveraged_return <= -(1/leverage - maint_margin), 
                    # the position is liquidated
                    # The actual loss to the trader is their initial margin
                    # Which is 1/leverage of their notional
                    # But in perps, you lose your margin = -100% of margin
                    pnl = -1.0 / leverage  # Lost the margin
                    trades.append({
                        "entry_bar": entry_bar,
                        "exit_bar": i,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "raw_return": raw_return,
                        "leveraged_return": pnl,
                        "bars_held": bars_held,
                        "exit_reason": "liquidated",
                    })
                    in_position = False
                    continue
            
            # Exit conditions
            exit_reason = None
            if current_low < sma10[i]:
                exit_reason = "sma10_cross"
            elif leverage > 1 and current_low < trailing_stop:
                exit_reason = "trailing_stop"
            
            if exit_reason:
                # For SMA10 exit, use SMA10 price approx
                if exit_reason == "sma10_cross":
                    exit_price = max(sma10[i], low[i])
                else:
                    exit_price = trailing_stop
                
                raw_return = (exit_price - entry_price) / entry_price
                funding_cost = FUNDING_RATE_PER_HOUR * bars_held * 4
                
                if leverage > 1:
                    # Apply friction to leveraged position
                    lev_return = raw_return * leverage - funding_cost - FRICTION
                else:
                    lev_return = raw_return - FRICTION
                
                trades.append({
                    "entry_bar": entry_bar,
                    "exit_bar": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "raw_return": raw_return,
                    "leveraged_return": lev_return,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                })
                in_position = False
    
    # Close any open position at end
    if in_position:
        exit_price = close[-1]
        raw_return = (exit_price - entry_price) / entry_price
        bars_held = len(close) - 1 - entry_bar
        funding_cost = FUNDING_RATE_PER_HOUR * bars_held * 4
        if leverage > 1:
            lev_return = raw_return * leverage - funding_cost - FRICTION
        else:
            lev_return = raw_return - FRICTION
        trades.append({
            "entry_bar": entry_bar,
            "exit_bar": len(close) - 1,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "raw_return": raw_return,
            "leveraged_return": lev_return,
            "bars_held": bars_held,
            "exit_reason": "end_of_data",
        })
    
    if len(trades) < 3:
        return None
    
    # Compute metrics
    returns = np.array([t["leveraged_return"] for t in trades])
    n_trades = len(trades)
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    n_liquidations = sum(1 for t in trades if t["exit_reason"] == "liquidated")
    
    # Profit factor
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-10
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    win_rate = len(wins) / n_trades if n_trades > 0 else 0
    
    # Total return (compounded)
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    total_return = equity[-1] - 1
    
    # Max drawdown on equity curve
    equity_arr = np.array(equity)
    peak = np.maximum.accumulate(equity_arr)
    dd = (peak - equity_arr) / peak
    max_dd = dd.max()
    
    # Annualized return
    # Bars in test period, 4h per bar
    test_bars = len(test_df)
    hours_in_test = test_bars * 4
    years_in_test = hours_in_test / (365.25 * 24)
    if years_in_test > 0 and equity[-1] > 0:
        ann_return = (equity[-1] ** (1 / years_in_test)) - 1
    else:
        ann_return = -1
    
    # Annualized Sharpe (using per-trade returns)
    if len(returns) > 1 and returns.std() > 0:
        # Trades per year
        trades_per_year = n_trades / years_in_test if years_in_test > 0 else 1
        sharpe = (returns.mean() / returns.std()) * np.sqrt(trades_per_year)
    else:
        sharpe = 0
    
    return {
        "leverage": leverage,
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "total_return_pct": round(total_return * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_liquidations": n_liquidations,
        "ann_return_pct": round(ann_return * 100, 2),
        "sharpe": round(sharpe, 3),
        "avg_trade_return_pct": round(returns.mean() * 100, 4),
        "test_years": round(years_in_test, 2),
        "equity_curve_end": round(equity[-1], 4),
    }


def run_pair(pair_name, filename):
    """Run full analysis for one pair."""
    print(f"\n{'='*60}")
    print(f"Processing {pair_name}")
    print(f"{'='*60}")
    
    df = load_and_resample(filename)
    print(f"  Loaded {len(df)} 4h bars from {df.index[0]} to {df.index[-1]}")
    
    df = compute_indicators(df)
    df = generate_signals(df)
    print(f"  After indicators: {len(df)} bars")
    
    results = {}
    for lev in LEVERAGE_LEVELS:
        split_results = []
        for s in range(N_SPLITS):
            res = backtest_with_leverage(df, lev, split_idx=s, n_splits=N_SPLITS)
            if res:
                split_results.append(res)
        
        # Aggregate across splits
        if split_results:
            agg = {
                "leverage": lev,
                "n_splits": len(split_results),
                "avg_profit_factor": round(np.mean([r["profit_factor"] for r in split_results]), 3),
                "avg_win_rate": round(np.mean([r["win_rate"] for r in split_results]), 4),
                "avg_n_trades": round(np.mean([r["n_trades"] for r in split_results]), 1),
                "avg_total_return_pct": round(np.mean([r["total_return_pct"] for r in split_results]), 2),
                "avg_max_drawdown_pct": round(np.mean([r["max_drawdown_pct"] for r in split_results]), 2),
                "total_liquidations": sum(r["n_liquidations"] for r in split_results),
                "avg_ann_return_pct": round(np.mean([r["ann_return_pct"] for r in split_results]), 2),
                "avg_sharpe": round(np.mean([r["sharpe"] for r in split_results]), 3),
                "splits": split_results,
            }
        else:
            agg = {"leverage": lev, "n_splits": 0, "error": "no valid splits"}
        
        results[lev] = agg
        if "error" not in agg:
            print(f"  {lev}x: PF={agg['avg_profit_factor']:.2f}, "
                  f"WR={agg['avg_win_rate']:.1%}, "
                  f"AnnRet={agg['avg_ann_return_pct']:.1f}%, "
                  f"MaxDD={agg['avg_max_drawdown_pct']:.1f}%, "
                  f"Liqs={agg['total_liquidations']}, "
                  f"Sharpe={agg['avg_sharpe']:.2f}")
    
    return results


def main():
    all_results = {}
    
    for pair_name, filename in PAIRS.items():
        try:
            all_results[pair_name] = run_pair(pair_name, filename)
        except Exception as e:
            print(f"  ERROR: {e}")
            all_results[pair_name] = {"error": str(e)}
    
    # Summary: find optimal leverage per pair
    print("\n" + "=" * 80)
    print("SUMMARY: Optimal Leverage Analysis")
    print("=" * 80)
    
    summary = {}
    for pair, results in all_results.items():
        if "error" in results:
            summary[pair] = {"optimal_leverage": None, "error": results["error"]}
            continue
        
        best_lev = None
        best_score = -999
        lev_comparison = {}
        
        for lev in LEVERAGE_LEVELS:
            r = results.get(lev, {})
            if "error" in r or r.get("n_splits", 0) == 0:
                continue
            
            # Score: prioritize risk-adjusted returns, penalize liquidations
            ann_ret = r.get("avg_ann_return_pct", 0)
            max_dd = r.get("avg_max_drawdown_pct", 100)
            liqs = r.get("total_liquidations", 0)
            sharpe = r.get("avg_sharpe", 0)
            
            # Calmar-like ratio (return/drawdown) with liquidation penalty
            if max_dd > 0:
                calmar = ann_ret / max_dd
            else:
                calmar = ann_ret
            
            score = sharpe - liqs * 0.5  # Heavy penalty for liquidations
            
            lev_comparison[lev] = {
                "ann_return_pct": ann_ret,
                "max_drawdown_pct": max_dd,
                "sharpe": sharpe,
                "liquidations": liqs,
                "score": round(score, 3),
            }
            
            if score > best_score:
                best_score = score
                best_lev = lev
        
        summary[pair] = {
            "optimal_leverage": best_lev,
            "best_score": round(best_score, 3),
            "comparison": lev_comparison,
        }
        
        print(f"\n{pair}:")
        if best_lev:
            for lev in LEVERAGE_LEVELS:
                c = lev_comparison.get(lev, {})
                if c:
                    marker = " <-- OPTIMAL" if lev == best_lev else ""
                    print(f"  {lev}x: AnnRet={c['ann_return_pct']:>8.1f}%  "
                          f"DD={c['max_drawdown_pct']:>6.1f}%  "
                          f"Sharpe={c['sharpe']:>6.2f}  "
                          f"Liqs={c['liquidations']}{marker}")
    
    # Cross-pair summary
    print("\n" + "=" * 80)
    print("CROSS-PAIR LEVERAGE DISTRIBUTION")
    print("=" * 80)
    lev_counts = {}
    for pair, s in summary.items():
        if s.get("optimal_leverage"):
            lev = s["optimal_leverage"]
            lev_counts[lev] = lev_counts.get(lev, 0) + 1
    for lev in sorted(lev_counts.keys()):
        print(f"  {lev}x: {lev_counts[lev]} pairs")
    
    # Save results
    output = {
        "strategy": "Momentum Breakout (Jupiter Perps)",
        "parameters": {
            "entry": "Close > HH20 + Volume > 2.0x SMA20 + ADX(14) > 30",
            "exit": "Close < SMA(10) OR Trailing Stop 1.0x ATR(14)",
            "friction": f"{FRICTION*100:.2f}%",
            "funding_rate": f"{FUNDING_RATE_PER_HOUR*100:.2f}%/hour",
            "maintenance_margin": f"{MAINTENANCE_MARGIN*100:.1f}%",
            "walk_forward_splits": N_SPLITS,
        },
        "leverage_levels": LEVERAGE_LEVELS,
        "pairs": {},
        "summary": summary,
    }
    
    for pair, results in all_results.items():
        output["pairs"][pair] = results
    
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
