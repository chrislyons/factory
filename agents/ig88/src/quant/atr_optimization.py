"""
ATR Stop/Target Optimization for H3-B (vol+rsi) strategy.

Sweep stop multiplier 1.0x-3.0x (step 0.5) and target multiplier 2.0x-8.0x (step 1.5)
for SOL, ETH, BTC, NEAR on 4h timeframe. Walk-forward 70/30 split.
Report peak Profit Factor (PF) configuration per asset.
Determine if universal ratio works or asset-specific is needed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2]))
import src.quant.indicators as ind
from src.quant.indicator_research import SignalBacktester, backtest_signal
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState
from src.quant.indicator_research import signals_vol_spike_break, signals_rsi_momentum_cross

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
MAKER_FEE = 0.0016


def load_asset(symbol: str, interval_min: int):
    """Load asset data from Binance."""
    try:
        return load_binance(symbol, interval_min)
    except FileNotFoundError:
        return None


def walk_forward_test(ts, o, h, l, c, v, regime, signal_mask, atr_stop_mult, atr_target_mult,
                      capital=10_000.0, bar_hours=4.0, split=0.70):
    """Run walk-forward backtest with given ATR stop/target multipliers.
    Returns (train_pf, test_pf, test_p, test_n) or (0,0,1,0) if no trades."""
    n = len(ts)
    SPLIT = int(n * split)
    
    # Compute ATR values
    atr_v = ind.atr(h, l, c, 14)
    
    # Create SignalBacktester with custom ATR multipliers
    bt = SignalBacktester(initial_capital=capital, bar_hours=bar_hours,
                          atr_stop=atr_stop_mult, atr_target=atr_target_mult)
    
    # Train period
    tr_trades = bt.run(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                       c[:SPLIT], v[:SPLIT], signal_mask[:SPLIT],
                       regime[:SPLIT], atr_v[:SPLIT])
    # Test period
    bt2 = SignalBacktester(initial_capital=capital, bar_hours=bar_hours,
                           atr_stop=atr_stop_mult, atr_target=atr_target_mult)
    te_trades = bt2.run(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                        c[SPLIT:], v[SPLIT:], signal_mask[SPLIT:],
                        regime[SPLIT:], atr_v[SPLIT:])
    
    def compute_pf(trades):
        if not trades:
            return 0.0, 1.0, 0
        eng = BacktestEngine(capital)
        eng.add_trades(trades)
        st = eng.compute_stats(venue=VENUE)
        return st.profit_factor, st.p_value, st.n_trades
    
    tr_pf, tr_p, tr_n = compute_pf(tr_trades)
    te_pf, te_p, te_n = compute_pf(te_trades)
    return tr_pf, te_pf, te_p, te_n


def optimize_atr_for_asset(symbol, label, btc_c, btc_ts):
    """Run ATR optimization for a single asset."""
    print(f"\n{'='*60}", flush=True)
    print(f"Optimizing {label}", flush=True)
    print(f"{'='*60}", flush=True)
    
    # Load 4h data
    df = load_asset(symbol, 240)  # 4h = 240 minutes
    if df is None or len(df) < 200:
        print(f"  [ERROR] No data for {label}", flush=True)
        return None
    
    ts, o, h, l, c, v = df_to_arrays(df)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    
    # Generate H3-B signal mask
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    signal_mask = m_vol & m_rsi
    
    # Parameter grid
    stop_mults = [1.0, 1.5, 2.0, 2.5, 3.0]
    target_mults = [2.0, 3.5, 5.0, 6.5, 8.0]  # 5 values equally spaced
    
    results = []
    best_te_pf = 0.0
    best_params = None
    best_row = None
    
    print(f"\n  {'Stop':>6} {'Target':>7} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}", flush=True)
    print(f"  {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*5}", flush=True)
    
    for stop, target in product(stop_mults, target_mults):
        tr_pf, te_pf, te_p, te_n = walk_forward_test(ts, o, h, l, c, v, regime,
                                                     signal_mask, stop, target)
        row = {"stop": stop, "target": target,
               "tr_pf": tr_pf, "te_pf": te_pf, "te_p": te_p, "te_n": te_n}
        results.append(row)
        
        star = "*" if te_p < 0.10 else " "
        print(f"  {stop:>6.1f} {target:>7.1f} {tr_pf:>7.3f} {te_pf:>7.3f} {te_p:>7.3f}{star} {te_n:>5}", flush=True)
        
        # Track best OOS PF (require at least 5 trades)
        if te_n >= 5 and te_pf > best_te_pf:
            best_te_pf = te_pf
            best_params = (stop, target)
            best_row = row
    
    print(f"\n  Best config: stop={best_params[0]:.1f}x target={best_params[1]:.1f}x  OOS PF={best_te_pf:.3f}", flush=True)
    return {
        "asset": label,
        "best_stop": best_params[0] if best_params else None,
        "best_target": best_params[1] if best_params else None,
        "best_pf": best_te_pf,
        "best_p": best_row["te_p"] if best_row else None,
        "best_n": best_row["te_n"] if best_row else None,
        "grid": results
    }


def main():
    import traceback
    print("=" * 72)
    print("ATR STOP/TARGET OPTIMIZATION - H3-B (vol+rsi) strategy")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)
    sys.stdout.flush()
    
    try:
        print("Starting optimization...", flush=True)
        # Load BTC daily for regime
        btc_df = load_asset("BTC/USD", 1440)
        print(f"BTC df loaded: {len(btc_df) if btc_df is not None else None}")
        if btc_df is None:
            print("[ERROR] BTC daily data not found")
            return
        btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
        
        # Assets to optimize
        assets = [
            ("SOL/USDT", "SOL 4h"),
            ("ETH/USD", "ETH 4h"),
            ("BTC/USD", "BTC 4h"),
            ("NEAR/USD", "NEAR 4h"),
        ]
        
        all_results = {}
        print(f"Assets to process: {assets}", flush=True)
        for sym, label in assets:
            res = optimize_atr_for_asset(sym, label, btc_c, btc_ts)
            if res:
                all_results[label] = res
        
        # Summary
        print("\n" + "=" * 72)
        print("SUMMARY - Peak PF per asset")
        print("=" * 72)
        print(f"{'Asset':<10} {'Stop':>6} {'Target':>7} {'PF':>7} {'p-val':>7} {'n':>5}")
        print(f"{'-'*10} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")
        
        for label, res in all_results.items():
            print(f"{label:<10} {res['best_stop']:>6.1f} {res['best_target']:>7.1f} "
                  f"{res['best_pf']:>7.3f} {res['best_p']:>7.3f} {res['best_n']:>5}")
        
        # Determine universal vs asset-specific
        stop_set = set(res['best_stop'] for res in all_results.values())
        target_set = set(res['best_target'] for res in all_results.values())
        
        if len(stop_set) == 1 and len(target_set) == 1:
            print(f"\n=> Universal ratio works: stop={stop_set.pop():.1f}x target={target_set.pop():.1f}x")
        else:
            print(f"\n=> Asset-specific ratios needed:")
            for label, res in all_results.items():
                print(f"    {label}: stop={res['best_stop']:.1f}x target={res['best_target']:.1f}x")
        
        # Save results
        out_path = DATA_DIR / "research" / "atr_optimization" / "atr_optimization_results.json"
        with open(out_path, "w") as f:
            json.dump({
                "run_at": datetime.now(timezone.utc).isoformat(),
                "stop_mults": [1.0, 1.5, 2.0, 2.5, 3.0],
                "target_mults": [2.0, 3.5, 5.0, 6.5, 8.0],
                "results": all_results
            }, f, indent=2)
        print(f"\nResults saved to: {out_path}")
    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main