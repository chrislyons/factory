import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr

class WalkForwardValidator:
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

    def run_test(self, df: pd.DataFrame, stop_mult: float, target_mult: float, friction: float = 0.002) -> Dict[str, Any]:
        p = self.compute_primitives(df)
        signal = p["signal"]
        c = p['close']
        atr_v = p['atr']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        signal_indices = np.where(signal)[0]
        for i in signal_indices:
            if i >= len(c) - 1: continue
            entry_price = c[i]
            stop = entry_price - stop_mult * atr_v[i]
            target = entry_price + target_mult * atr_v[i]
            
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
        return {"trades": total_trades, "win_rate": win_rate, "pf": pf, "net_pnl_pct": (gross_wins - gross_losses)*100}

    def validate_assets(self, asset_params: Dict[str, Dict]):
        overall_results = {}
        
        for asset in self.asset_list:
            if asset not in self.data: continue
            df = self.data[asset]
            
            # Split: 80% Train, 20% Validation (most recent)
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx]
            val_df = df.iloc[split_idx:]
            
            params = asset_params.get(asset, {"stop": 2.0, "target": 5.0})
            
            train_res = self.run_test(train_df, params["stop"], params["target"])
            val_res = self.run_test(val_df, params["stop"], params["target"])
            
            overall_results[asset] = {
                "train": train_res,
                "val": val_res,
                "decay": val_res["pf"] / train_res["pf"] if train_res["pf"] > 0 else 0
            }
        return overall_results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    # Optimized params from the Grid Search
    asset_params = {
        "SOL/USDT": {"stop": 1.5, "target": 6.0},
        "BTC/USDT": {"stop": 1.5, "target": 6.0},
        "ETH/USDT": {"stop": 1.5, "target": 6.0},
        "LINK/USDT": {"stop": 1.5, "target": 6.0},
        "AVAX/USDT": {"stop": 2.5, "target": 6.0},
        "NEAR/USDT": {"stop": 2.0, "target": 6.0},
    }
    
    validator = WalkForwardValidator(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    results = validator.validate_assets(asset_params)
    print(json.dumps(results, indent=2))
