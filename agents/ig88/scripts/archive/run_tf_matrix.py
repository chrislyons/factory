import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class TimeframeMatrixTester:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.data = self._load_all_data()

    def _load_all_data(self) -> Dict[str, Dict[str, pd.DataFrame]]:
        # Structure: { asset: { timeframe_min: df } }
        all_data = {}
        timeframes = [60, 120, 240, 1440]
        for asset in self.asset_list:
            asset_data = {}
            symbol = asset.replace('/', '_')
            for tf in timeframes:
                path = self.data_dir / f"binance_{symbol}_{tf}m.parquet"
                if path.exists():
                    asset_data[tf] = pd.read_parquet(path)
            all_data[asset] = asset_data
        return all_data

    def run_test(self, df: pd.DataFrame, params: Dict[str, int], friction: float = 0.01):
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        # Unified Indicator Call
        ichi = ichimoku(h, l, c, 
                        tenkan_period=params['tenkan'], 
                        kijun_period=params['kijun'], 
                        senkou_b_period=params['senkou_b'])
        
        T = ichi.tenkan_sen
        K = ichi.kijun_sen
        SA = ichi.senkou_span_a
        SB = ichi.senkou_span_b
        
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(max(params['senkou_b'], 50), len(c)-1):
            # Signal: TK Cross + Above Cloud + RSI > 55
            tk_cross = (T[i] > K[i]) and (T[i-1] <= K[i-1])
            above_cloud = c[i] > max(SA[i], SB[i])
            rsi_ok = rsi_v[i] > 55
            
            if tk_cross and above_cloud and rsi_ok:
                entry_price = c[i]
                total_trades += 1
                
                stop = entry_price - 2.0 * atr_v[i]
                target = entry_price + 5.0 * atr_v[i]
                
                # Simple exit loop
                exit_price = c[-1]
                for j in range(i+1, len(c)):
                    if c[j] <= stop:
                        exit_price = stop
                        break
                    if c[j] >= target:
                        exit_price = target
                        break
                
                pnl = (exit_price - entry_price) / entry_price - friction
                if pnl > 0:
                    gross_wins += pnl
                    total_wins += 1
                else:
                    gross_losses += abs(pnl)
        
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "pf": pf, "win_rate": (total_wins/total_trades*100 if total_trades>0 else 0)}

    def execute_matrix(self):
        # Calendar-Time Constants (Hours)
        # Standard Daily: 9/26/52
        # We scale these based on the bar interval
        results = {}
        
        for asset in self.asset_list:
            asset_res = {}
            for tf, df in self.data[asset].items():
                bar_hours = tf / 60.0
                
                # 1. Standard Parameters (9/26/52)
                std_params = {"tenkan": 9, "kijun": 26, "senkou_b": 52}
                std_res = self.run_test(df, std_params)
                
                # 2. Calendar-Scaled Parameters
                # Ratio relative to 4h (where 9/26/52 is current baseline)
                # If 4h is the "standard" for our current edge:
                ratio = 4.0 / bar_hours
                scaled_params = {
                    "tenkan": int(9 * ratio),
                    "kijun": int(26 * ratio),
                    "senkou_b": int(52 * ratio)
                }
                scaled_res = self.run_test(df, scaled_params)
                
                asset_res[f"{tf}m"] = {
                    "standard": std_res,
                    "scaled": scaled_res,
                    "params_scaled": scaled_params
                }
            results[asset] = asset_res
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = TimeframeMatrixTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    matrix = tester.execute_matrix()
    print(json.dumps(matrix, indent=2))
