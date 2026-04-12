import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import itertools
import json
from src.quant.indicators import ichimoku, rsi, atr, sma, kama, obv, ema

class AblationTester:
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
        vol_ma = sma(v, 20)
        return {
            "trend_above_cloud": (c > cloud_top).astype(int),
            "mom_rsi_55": (rsi_v > 55).astype(int),
            "mom_rsi_cross": ((rsi_v > 50) & (np.roll(rsi_v, 1) <= 50)).astype(int),
            "vol_ignition": (v > 1.5 * vol_ma).astype(int),
            "close": c,
            "atr": atr(h, l, c, 14)
        }

    def evaluate_composition(self, primitive_keys: List[str], 
                             friction: float = 0.002, 
                             stop_mult: float = 2.0, 
                             target_mult: float = 5.0,
                             asset: str = None) -> Dict[str, Any]:
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        target_assets = [asset] if asset else self.asset_list
        
        for a in target_assets:
            if a not in self.data: continue
            df = self.data[a]
            p = self.compute_primitives(df)
            signal = np.ones(len(df), dtype=int)
            for k in primitive_keys:
                signal &= p[k]
            
            c = p['close']
            atr_v = p['atr']
            
            for i in range(20, len(c)-1):
                if signal[i] == 1:
                    total_trades += 1
                    entry_price = c[i]
                    stop = entry_price - stop_mult * atr_v[i]
                    target = entry_price + target_mult * atr_v[i]
                    
                    for j in range(i+1, len(c)):
                        if c[j] <= stop:
                            loss = (entry_price - stop) / entry_price
                            gross_losses += (loss + friction)
                            break
                        if c[j] >= target:
                            win = (target - entry_price) / entry_price
                            gross_wins += (win - friction)
                            total_wins += 1
                            break
                        if j == len(c)-1:
                            pnl = (c[j] - entry_price) / entry_price
                            if pnl > 0:
                                gross_wins += (pnl - friction)
                                total_wins += 1
                            else:
                                gross_losses += (abs(pnl) + friction)
                            break
        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        net_pnl = gross_wins - gross_losses
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        return {
            "trades": total_trades,
            "win_rate": win_rate,
            "net_pnl_pct": net_pnl * 100,
            "profit_factor": profit_factor
        }

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = AblationTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    best_combo = ["trend_above_cloud", "mom_rsi_55"]

    # ABL-1: Slippage Stress Test
    frictions = [0.002, 0.005] # 20bps, 50bps
    slip_results = {f: tester.evaluate_composition(best_combo, friction=f) for f in frictions}

    # ABL-2: Exit Sensitivity Analysis
    stops = [1.5, 2.0, 2.5]
    exit_results = {s: tester.evaluate_composition(best_combo, stop_mult=s) for s in stops}

    # ABL-3: Portfolio Contribution Audit
    asset_results = {a: tester.evaluate_composition(best_combo, asset=a) for a in assets}

    print("--- ABL-1: SLIPPAGE ---")
    print(json.dumps(slip_results, indent=2))
    print("\\n--- ABL-2: EXIT SENSITIVITY ---")
    print(json.dumps(exit_results, indent=2))
    print("\\n--- ABL-3: ASSET AUDIT ---")
    print(json.dumps(asset_results, indent=2))
