import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class GridSearchOptimizer:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.data = self._load_all_data()

    def _load_all_data(self) -> Dict[str, pd.DataFrame]:
        data = {}
        for asset in self.asset_list:
            symbol = asset.replace('/', '_')
            path = self.data_dir / f"binance_{symbol}_240m.parquet"
            if path.exists():
                data[asset] = pd.read_parquet(path)
        return data

    def compute_primitives(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        h, l, c, v = df['high'].values, df['low'].values, df['close'].values, df['volume'].values
        ichi = ichimoku(h, l, c)
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        rsi_v = rsi(c, 14)
        return {
            "signal": (c > cloud_top) & (rsi_v > 55),
            "close": c,
            "atr": atr(h, l, c, 14)
        }

    def evaluate(self, asset: str, stop_mult: float, target_mult: float, friction: float = 0.002) -> Dict[str, Any]:
        df = self.data[asset]
        p = self.compute_primitives(df)
        signal = p["signal"]
        c = p['close']
        atr_v = p['atr']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        # Vectorized search is hard for this loop, but we can optimize the loop
        # We only iterate over indices where signal == 1
        signal_indices = np.where(signal)[0]
        
        for i in signal_indices:
            if i >= len(c) - 1: continue
            entry_price = c[i]
            stop = entry_price - stop_mult * atr_v[i]
            target = entry_price + target_mult * atr_v[i]
            
            # Vectorized check for the exit
            remaining = c[i+1:]
            exit_idx = np.where((remaining <= stop) | (remaining >= target))[0]
            
            if len(exit_idx) > 0:
                idx = exit_idx[0]
                exit_price = remaining[idx]
                if exit_price >= target:
                    gross_wins += ((target - entry_price) / entry_price) - friction
                    total_wins += 1
                else:
                    gross_losses += ((entry_price - stop) / entry_price) + friction
            else:
                # End of data exit
                last_price = c[-1]
                pnl = (last_price - entry_price) / entry_price
                if pnl > 0:
                    gross_wins += (pnl - friction)
                    total_wins += 1
                else:
                    gross_losses += (abs(pnl) + friction)
            total_trades += 1
                        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"stop": stop_mult, "target": target_mult, "pf": pf, "wr": win_rate, "trades": total_trades}

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    optimizer = GridSearchOptimizer(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    
    # Narrower search for speed
    stop_range = [1.5, 2.0, 2.5]
    target_range = [4.0, 5.0, 6.0]
    
    final_results = {}
    for asset in assets:
        best_pf = -1
        best_params = {}
        for s in stop_range:
            for t in target_range:
                res = optimizer.evaluate(asset, s, t)
                if res["pf"] > best_pf:
                    best_pf = res["pf"]
                    best_params = res
        final_results[asset] = best_params
        
    print(json.dumps(final_results, indent=2))
