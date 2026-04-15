import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class AdversarialSurgicalAudit:
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

    def simulate_strategy(self, c, atr_v, cloud_top, rsi_v, atr_baseline, friction=0.01, slippage_exit=0.0):
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(50, len(c)-1):
            if (atr_v[i] > atr_baseline[i] * 1.2) and (c[i] > cloud_top[i]) and (rsi_v[i] > 55):
                entry_price = c[i]
                total_trades += 1
                
                highest_price = entry_price
                exit_price = c[-1]
                for j in range(i+1, len(c)):
                    highest_price = max(highest_price, c[j])
                    if c[j] <= highest_price - 2.0 * atr_v[j]:
                        exit_price = c[j]
                        break
                
                # Apply exit slippage: we get a slightly worse price than the signal
                # For a long exit, slippage means a lower price.
                actual_exit = exit_price * (1 - slippage_exit)
                pnl = (actual_exit - entry_price) / entry_price - friction
                
                if pnl > 0:
                    gross_wins += pnl
                    total_wins += 1
                else:
                    gross_losses += abs(pnl)
        
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "pf": pf, "win_rate": (total_wins/total_trades*100 if total_trades>0 else 0)}

    def run_adversarial_suite(self):
        results = {}
        for asset in self.asset_list:
            df = self.data[asset]
            # a) Standard Run (Baseline)
            p = self.compute_indicators(df)
            baseline = self.simulate_strategy(p['c'], p['atr'], p['cloud_top'], p['rsi'], p['atr_baseline'])
            
            # b) Shuffle Test (Randomized time series)
            # We shuffle the CLOSE prices to break time-series correlation
            shuffled_c = np.random.permutation(p['c'])
            # We keep indicators the same to see if the "entry timing" is just luck
            shuffle_res = self.simulate_strategy(shuffled_c, p['atr'], p['cloud_top'], p['rsi'], p['atr_baseline'])
            
            # c) Slippage Stress (Add 0.5% slippage to every exit)
            slip_res = self.simulate_strategy(p['c'], p['atr'], p['cloud_top'], p['rsi'], p['atr_baseline'], slippage_exit=0.005)
            
            results[asset] = {
                "baseline": baseline,
                "shuffle": shuffle_res,
                "slippage_0_5pct": slip_res
            }
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    auditor = AdversarialSurgicalAudit(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    final_results = auditor.run_adversarial_suite()
    print(json.dumps(final_results, indent=2))
