"""
exit_parameter_sweep.py — Exit parameter optimization for H3-A, H3-B, H3-Combined on SOL 4h.
Vary ATR stop (1.0x to 3.0x) and ATR target (2.0x to 8.0x).
Test ATR trailing stop variants (1.5x, 2.0x, 2.5x trail).
Find local peak PF configuration for each strategy.
Report optimal exit parameters and resulting OOS PF/WR.
Save results to data/research/exits/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import src.quant.indicators as ind
from src.quant.indicator_research import (
    SignalBacktester, backtest_signal,
    signals_vol_spike_break, signals_rsi_momentum_cross,
    signals_ichimoku_h3a,
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState
from src.quant.research_loop import ExitResearchBacktester

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
CAPITAL = 10_000.0
BAR_HOURS = 4.0
SPLIT = 0.70

def compute_stats(trades):
    """Return dict with n, wr, pf, p-value."""
    if not trades:
        return None
    eng = BacktestEngine(CAPITAL)
    eng.add_trades(trades)
    s = eng.compute_stats(venue=VENUE)
    return {
        "n": s.n_trades,
        "wr": s.win_rate,
        "pf": s.profit_factor,
        "sharpe": s.sharpe_ratio,
        "dd": s.max_drawdown_pct,
        "pnl": s.total_pnl_pct,
        "p": s.p_value,
    }

def run_sweep(strategy_name, mask, ts, o, h, l, c, v, regime):
    """Run parameter sweep for given strategy mask."""
    print(f"\n{'='*72}")
    print(f"EXIT PARAMETER SWEEP — {strategy_name}")
    print(f"{'='*72}")
    
    bt = ExitResearchBacktester(CAPITAL, BAR_HOURS)
    
    # Define exit method variants
    exit_methods = []
    # Fixed ATR stop/target combos (stop_mult, target_mult)
    stop_range = np.arange(1.0, 3.1, 0.5)  # 1.0, 1.5, 2.0, 2.5, 3.0
    target_range = np.arange(2.0, 8.1, 1.0)  # 2.0,3.0,4.0,5.0,6.0,7.0,8.0
    for stop_mult in stop_range:
        for target_mult in target_range:
            exit_methods.append(("atr_fixed", stop_mult, target_mult))
    
    # ATR trailing stop variants
    trail_range = [1.5, 2.0, 2.5]
    for trail_mult in trail_range:
        exit_methods.append(("atr_trail", trail_mult))
    
    # Other exit methods (already defined in EXIT_METHODS)
    other_methods = ["kijun_trail", "bb_mid", "time5", "time10"]
    for meth in other_methods:
        exit_methods.append((meth,))
    
    # Results storage
    results = []
    
    N = len(ts)
    SPLIT_IDX = int(N * SPLIT)
    
    for method in exit_methods:
        if method[0] == "atr_fixed":
            _, stop_mult, target_mult = method
            exit_method = "atr_custom"
            extra_args = {"atr_stop_mult": stop_mult, "atr_target_mult": target_mult}
            label = f"atr_{stop_mult:.1f}_{target_mult:.1f}"
        elif method[0] == "atr_trail":
            _, trail_mult = method
            exit_method = "atr_trail"
            extra_args = {"atr_trail_mult": trail_mult}
            label = f"atr_trail_{trail_mult:.1f}"
        else:
            exit_method = method[0]
            extra_args = {}
            label = exit_method
        
        # Train
        tr_trades = bt.run_exit(ts[:SPLIT_IDX], o[:SPLIT_IDX], h[:SPLIT_IDX],
                                l[:SPLIT_IDX], c[:SPLIT_IDX], v[:SPLIT_IDX],
                                regime[:SPLIT_IDX], mask[:SPLIT_IDX],
                                exit_method, **extra_args)
        # Test
        te_trades = bt.run_exit(ts[SPLIT_IDX:], o[SPLIT_IDX:], h[SPLIT_IDX:],
                                l[SPLIT_IDX:], c[SPLIT_IDX:], v[SPLIT_IDX:],
                                regime[SPLIT_IDX:], mask[SPLIT_IDX:],
                                exit_method, **extra_args)
        
        tr = compute_stats(tr_trades)
        te = compute_stats(te_trades)
        
        results.append({
            "label": label,
            "exit_method": exit_method,
            "extra_args": extra_args,
            "train": tr,
            "test": te,
        })
        
        # Print progress
        tr_pf = f"{tr['pf']:.3f}" if tr else "-"
        te_pf = f"{te['pf']:.3f}" if te else "-"
        te_p = f"{te['p']:.3f}" if te else "-"
        te_n = te['n'] if te else 0
        print(f"  {label:<20} Tr-PF {tr_pf:>7}  Te-PF {te_pf:>7}  Te-p {te_p:>7}  Te-n {te_n:>5}")
    
    # Find optimal configuration (local peak PF)
    valid = [r for r in results if r["test"] and r["test"]["n"] >= 5]
    if not valid:
        print(f"  No valid configurations for {strategy_name}")
        return None
    
    # Sort by OOS PF * (1 - p-value) to penalize insignificant results
    valid.sort(key=lambda x: x["test"]["pf"] * (1 - x["test"]["p"]), reverse=True)
    best = valid[0]
    
    print(f"\n  OPTIMAL CONFIG for {strategy_name}:")
    print(f"    Exit method: {best['label']}")
    print(f"    OOS PF: {best['test']['pf']:.3f}, WR: {best['test']['wr']:.3f}, n: {best['test']['n']}, p: {best['test']['p']:.3f}")
    if best.get("extra_args"):
        print(f"    Parameters: {best['extra_args']}")
    
    return {
        "strategy": strategy_name,
        "optimal": best,
        "all_results": results,
    }

def main():
    print("=" * 70)
    print("EXIT PARAMETER SWEEP — SOL 4h")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    
    # Load SOL 4h data
    try:
        df = load_binance("SOL/USDT", 240)
    except FileNotFoundError:
        print("SOL/USDT 4h data not found. Exiting.")
        return
    
    ts, o, h, l, c, v = df_to_arrays(df)
    
    # Build regime using BTC daily
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    
    # Compute signals
    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi
    m_h3combined = m_h3a | m_h3b  # H3-Combined = A OR B
    
    strategies = [
        ("H3-A", m_h3a),
        ("H3-B", m_h3b),
        ("H3-Combined", m_h3combined),
    ]
    
    all_strategy_results = []
    for name, mask in strategies:
        result = run_sweep(name, mask, ts, o, h, l, c, v, regime)
        if result:
            all_strategy_results.append(result)
    
    # Save results to data/research/exits/
    out_dir = DATA_DIR / "research" / "exits"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_file = out_dir / f"SOL_4h_exit_sweep_{timestamp}.json"
    
    with open(out_file, "w") as f:
        json.dump(all_strategy_results, f, indent=2, default=str)
    
    print(f"\nResults saved to {out_file}")
    
    # Summary table
    print("\n" + "="*70)
    print("SUMMARY — Optimal Exit Configurations")
    print("="*70)
    print(f"{'Strategy':<15} {'Exit Method':<20} {'OOS PF':>7} {'WR':>7} {'n':>5} {'p-value':>7} {'Parameters'}")
    print(f"{'-'*15} {'-'*20} {'-'*7} {'-'*7} {'-'*5} {'-'*7} {'-'*20}")
    for res in all_strategy_results:
        opt = res["optimal"]
        params = opt.get("extra_args", {})
        params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "-"
        print(f"{res['strategy']:<15} {opt['label']:<20} {opt['test']['pf']:>7.3f} {opt['test']['wr']:>7.3f} {opt['test']['n']:>5} {opt['test']['p']:>7.3f} {params_str}")

if __name__ == "__main__":
    main()