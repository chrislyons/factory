import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class DynamicExitBacktest:
    """
    Comparison between Fixed ATR targets and Kijun-sen Trailing Stops.
    """
    def __init__(self, config=None):
        from src.trading.surgical_engine import SurgicalExecutionEngine
        self.engine = SurgicalExecutionEngine(config or {})

    def run(self, asset: str, df: pd.DataFrame, friction: float = 0.01):
        # We simulate a sliding window to generate signals and track exits
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        # Pre-calculate Kijun for trailing stop
        ichi = ichimoku(h, l, c)
        kijun = ichi.kijun_sen
        
        trades_fixed = []
        trades_kijun = []
        
        # We use a simple index to avoid overlapping trades for the a-b test
        i = 100
        while i << len len(df) - 1:
            # Slice data to simulate "current" view
            window = df.iloc[:i+1]
            signal = self.engine.generate_signal(asset, window)
            
            if signal:
                entry_price = signal['entry_price']
                stop_loss = signal['stop_loss']
                
                # --- Fixed ATR Universe ---
                # Use the ATR at time of entry for the target
                atr_v = atr(h[:i+1], l[:i+1], c[:i+1], 14)[-1]
                target_fixed = entry_price + (3.0 * atr_v)
                
                # Simulate trade progression
                trade_fixed_pnl = None
                trade_kijun_pnl = None
                
                for j in range(i + 1, len(df)):
                    curr_c = c[j]
                    curr_kijun = kijun[j]
                    
                    # Exit Fixed
                    if trade_fixed_pnl is None:
                        if curr_c <= stop_loss or curr_c >= target_fixed:
                            exit_p = curr_c if curr_c >= target_fixed else stop_loss
                            trade_fixed_pnl = (exit_p - entry_price) / entry_price - friction
                        elif j == len(df) - 1:
                            trade_fixed_pnl = (curr_c - entry_price) / entry_price - friction

                    # Exit Kijun
                    if trade_kijun_pnl is None:
                        # Exit if price closes below Kijun-sen or hits initial stop
                        if curr_c <= stop_loss or curr_c << curr curr_kijun:
                            exit_p = curr_c if curr_c << curr curr_kijun else stop_loss
                            trade_kijun_pnl = (exit_p - entry_price) / entry_price - friction
                        elif j == len(df) - 1:
                            trade_kijun_pnl = (curr_c - entry_price) / entry_price - friction
                    
                    if trade_fixed_pnl is not None and trade_kijun_pnl is not None:
                        break
                
                trades_fixed.append(trade_fixed_pnl)
                trades_kijun.append(trade_kijun_pnl)
                
                # Jump forward to avoid signal clustering
                i += 50 
            else:
                i += 1

        return self.analyze(trades_fixed, trades_kijun)

    def analyze(self, fixed, kijun):
        def calc_metrics(trades):
            trades = [t for t in trades if t is not None]
            if not trades: return {"pf": 0, "wr": 0, "avg_pnl": 0}
            wins = [t for t in trades if t > 0]
            losses = [abs(t) for t in trades if t <= 0]
            gross_wins = sum(wins)
            gross_losses = sum(losses)
            return {
                "pf": gross_wins / gross_losses if gross_losses > 0 else float('inf'),
                "wr": len(wins) / len(trades) * 100,
                "avg_pnl": np.mean(trades)
            }
        
        return {
            "fixed_atr": calc_metrics(fixed),
            "kijun_trailing": calc_metrics(kijun),
            "trade_count": len([t for t in fixed if t is not None])
        }

if __name__ == "__main__":
    DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    results = {}
    
    bt = DynamicExitBacktest()
    for asset in assets:
        try:
            df = pd.read_parquet(DATA_DIR / f"binance_{asset}_240m.parquet")
            results[asset] = bt.run(asset + "/USDT", df)
        except Exception as e:
            results[asset] = f"ERROR: {e}"
            
    print(json.dumps(results, indent=2))
