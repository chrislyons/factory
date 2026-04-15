import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class FrictionStressTester:
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

    def compute_indicators(self, df: pd.DataFrame):
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        ma20 = sma(c, 20)
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        ichi = ichimoku(h, l, c)
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        
        rolling_std = pd.Series(c).rolling(window=20).std().values
        bb_upper = ma20 + 2 * rolling_std
        bb_lower = ma20 - 2 * rolling_std
        
        diff = bb_upper - bb_lower
        diff[diff == 0] = 1e-9
        b_pct = (c - bb_lower) / diff
        
        return {
            "c": c, "atr": atr_v, "rsi": rsi_v, "cloud_top": cloud_top, 
            "b_pct": b_pct, "ma20": ma20
        }

    def evaluate_strategy(self, asset: str, strategy_type: str, friction: float):
        df = self.data[asset]
        p = self.compute_indicators(df)
        c = p['c']
        atr_v = p['atr']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(50, len(c)-1):
            entry_price = None
            target_mult = 0
            stop_mult = 2.0
            
            if strategy_type == "TREND":
                if (c[i] > p['cloud_top'][i]) and (p['rsi'][i] > 55):
                    entry_price = c[i]
                    target_mult = 5.0
            elif strategy_type == "MEAN_REV":
                if (p['b_pct'][i] < 0.2) and (p['rsi'][i] < 30):
                    entry_price = c[i]
                    target_mult = 3.0
            
            if entry_price is not None:
                total_trades += 1
                stop = entry_price - stop_mult * atr_v[i]
                target = entry_price + target_mult * atr_v[i]
                
                for j in range(i+1, len(c)):
                    if c[j] <= stop:
                        gross_losses += ((entry_price - stop) / entry_price) + friction
                        break
                    if c[j] >= target:
                        gross_wins += ((target - entry_price) / entry_price) - friction
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
                        
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "pf": pf, "net_pnl": (gross_wins - gross_losses)*100}

    def run_stress_test(self):
        frictions = {
            "Optimistic": 0.002, # 20bps
            "Realistic": 0.01,   # 1%
            "Pessimistic": 0.05  # 5%
        }
        strategies = ["TREND", "MEAN_REV"]
        
        final_report = {}
        for asset in self.asset_list:
            asset_report = {}
            for strat in strategies:
                strat_results = {}
                for label, f_val in frictions.items():
                    strat_results[label] = self.evaluate_strategy(asset, strat, f_val)
                asset_report[strat] = strat_results
            final_report[asset] = asset_report
        return final_report

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = FrictionStressTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    results = tester.run_stress_test()
    print(json.dumps(results, indent=2))
