import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class MeanReversionTester:
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

    def compute_mean_rev_primitives(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        c = df['close'].values
        ma = sma(c, 20)
        rolling_std = pd.Series(c).rolling(window=20).std().values
        
        upper = ma + 2 * rolling_std
        lower = ma - 2 * rolling_std
        
        # Percent B: (Price - Lower) / (Upper - Lower)
        # Avoid division by zero
        diff = upper - lower
        diff[diff == 0] = 1e-9
        b_pct = (c - lower) / diff
        
        rsi_v = rsi(c, 14)
        
        return {
            "b_pct": b_pct,
            "rsi": rsi_v,
            "close": c,
            "atr": atr(df['high'].values, df['low'].values, c, 14)
        }

    def run_test(self, df: pd.DataFrame, b_threshold: float = 0.2, rsi_threshold: float = 30.0) -> Dict[str, Any]:
        p = self.compute_mean_rev_primitives(df)
        b_pct = p["b_pct"]
        rsi_v = p["rsi"]
        c = p['close']
        atr_v = p['atr']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        friction = 0.002
        
        for i in range(20, len(c)-1):
            # ENTRY: Price is extremely oversold (Low B% and Low RSI)
            if b_pct[i] < b_threshold and rsi_v[i] < rsi_threshold:
                total_trades += 1
                entry_price = c[i]
                stop = entry_price - 2 * atr_v[i]
                target = entry_price + 3 * atr_v[i]
                
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
                        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "win_rate": win_rate, "pf": pf, "net_pnl_pct": (gross_wins - gross_losses)*100}

    def validate_all(self):
        results = {}
        for asset in self.asset_list:
            if asset not in self.data: continue
            df = self.data[asset]
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx]
            val_df = df.iloc[split_idx:]
            
            train_res = self.run_test(train_df)
            val_res = self.run_test(val_df)
            
            results[asset] = {
                "train_pf": train_res["pf"],
                "val_pf": val_res["pf"],
                "val_pnl": val_res["net_pnl_pct"]
            }
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = MeanReversionTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    res = tester.validate_all()
    print(json.dumps(res, indent=2))
