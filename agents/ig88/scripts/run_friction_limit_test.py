import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class FrictionLimitTester:
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
        atr_baseline = pd.Series(atr_v).rolling(window=30).mean().values
        return {
            "c": c, "atr": atr_v, "rsi": rsi_v, 
            "cloud_top": cloud_top, "atr_baseline": atr_baseline
        }

    def run_test(self, asset: str, friction: float):
        df = self.data[asset]
        p = self.compute_indicators(df)
        c = p['c']
        atr_v = p['atr']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(50, len(c)-1):
            # Using the winning VOL_GATED_TREND logic
            if (atr_v[i] > p['atr_baseline'][i] * 1.2) and (c[i] > p['cloud_top'][i]) and (p['rsi'][i] > 55):
                entry_price = c[i]
                total_trades += 1
                
                # Trailing Stop logic
                highest_price = entry_price
                exit_price = c[-1]
                for j in range(i+1, len(c)):
                    highest_price = max(highest_price, c[j])
                    if c[j] <= highest_price - 2.0 * atr_v[j]:
                        exit_price = c[j]
                        break
                
                pnl = (exit_price - entry_price) / entry_price - friction
                if pnl > 0:
                    gross_wins += pnl
                    total_wins += 1
                else:
                    gross_losses += abs(pnl)
        
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "win_rate": (total_wins/total_trades*100 if total_trades>0 else 0), "pf": pf}

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = FrictionLimitTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    
    # Testing a range of frictions to find the breaking point
    friction_levels = [0.002, 0.01, 0.02, 0.03, 0.04, 0.05]
    final_results = {}
    
    for f in friction_levels:
        level_res = {}
        for asset in assets:
            level_res[asset] = tester.run_test(asset, f)
        final_results[f"{f*100:.1f}%"] = level_res
        
    print(json.dumps(final_results, indent=2))
