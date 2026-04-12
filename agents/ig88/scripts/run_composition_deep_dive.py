import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import itertools
import json
from src.quant.indicators import ichimoku, rsi, atr, sma, kama, obv, ema

class CompositionTester:
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

    def evaluate_composition(self, primitive_keys: List[str], asset: str = None) -> Dict[str, Any]:
        total_trades = 0
        total_wins = 0
        net_pnl = 0.0
        
        # If asset is specified, only test that one, otherwise test all
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
                    stop = entry_price - 2 * atr_v[i]
                    target = entry_price + 5 * atr_v[i]
                    
                    for j in range(i+1, len(c)):
                        if c[j] <= stop:
                            net_pnl -= (entry_price - stop) / entry_price
                            break
                        if c[j] >= target:
                            net_pnl += (target - entry_price) / entry_price
                            total_wins += 1
                            break
                        if j == len(c)-1:
                            net_pnl += (c[j] - entry_price) / entry_price
                            if c[j] > entry_price: total_wins += 1
                            break
        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        return {
            "composition": " + ".join(primitive_keys),
            "trades": total_trades,
            "win_rate": win_rate,
            "net_pnl_pct": net_pnl * 100
        }

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = CompositionTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    
    primitives = ["trend_above_cloud", "mom_rsi_55", "mom_rsi_cross", "vol_ignition"]
    
    # 1. Test Single Indicators (Baselines)
    single_results = []
    for p in primitives:
        res = tester.evaluate_composition([p])
        single_results.append(res)
    
    # 2. Test Combinations (2 or 3)
    combo_results = []
    for r in range(2, 4):
        for combo in itertools.combinations(primitives, r):
            res = tester.evaluate_composition(list(combo))
            combo_results.append(res)
    
    # 3. Per-Asset Breakdown for Top Combo
    top_combo = ["trend_above_cloud", "mom_rsi_55"]
    asset_breakdown = {}
    for a in assets:
        asset_breakdown[a] = tester.evaluate_composition(top_combo, asset=a)
        
    print("--- SINGLE INDICATORS ---")
    print(json.dumps(single_results, indent=2))
    print("\\n--- TOP COMBOS ---")
    combo_results.sort(key=lambda x: x['net_pnl_pct'], reverse=True)
    print(json.dumps(combo_results[:5], indent=2))
    print("\\n--- ASSET BREAKDOWN (Top Combo) ---")
    print(json.dumps(asset_breakdown, indent=2))
