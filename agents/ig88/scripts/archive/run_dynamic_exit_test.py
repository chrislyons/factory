import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr

class DynamicExitTester:
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
        # Kijun-sen is the baseline for dynamic exits
        kijun = ichi.kijun_sen
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        rsi_v = rsi(c, 14)
        return {
            "signal": (c > cloud_top) & (rsi_v > 55),
            "close": c,
            "atr": atr(h, l, c, 14),
            "kijun": kijun
        }

    def run_test(self, df: pd.DataFrame, exit_mode: str, stop_mult: float = 2.0, friction: float = 0.002) -> Dict[str, Any]:
        p = self.compute_primitives(df)
        signal = p["signal"]
        c = p['close']
        atr_v = p['atr']
        kijun = p['kijun']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        signal_indices = np.where(signal)[0]
        for i in signal_indices:
            if i >= len(c) - 1: continue
            entry_price = c[i]
            
            # Initial Stop is always ATR based to prevent immediate blowup
            initial_stop = entry_price - stop_mult * atr_v[i]
            current_stop = initial_stop
            
            for j in range(i+1, len(c)):
                # Update Trailing Stop if using trailing mode
                if exit_mode == "trailing":
                    # Trail using 2x ATR from the highest high since entry
                    highest_high = np.max(c[i:j+1])
                    current_stop = max(current_stop, highest_high - stop_mult * atr_v[j])
                elif exit_mode == "kijun":
                    # Exit when price closes below Kijun-sen (or initial stop)
                    current_stop = max(initial_stop, kijun[j])
                
                if c[j] <= current_stop:
                    loss = (entry_price - current_stop) / entry_price
                    gross_losses += (abs(loss) + friction)
                    break
                
                if j == len(c)-1:
                    pnl = (c[j] - entry_price) / entry_price
                    if pnl > 0:
                        gross_wins += (pnl - friction)
                        total_wins += 1
                    else:
                        gross_losses += (abs(pnl) + friction)
                    break
            total_trades += 1
                        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "win_rate": win_rate, "pf": pf, "net_pnl_pct": (gross_wins - gross_losses)*100}

    def validate_all(self, exit_modes: List[str]):
        results = {}
        for mode in exit_modes:
            mode_results = {}
            for asset in self.asset_list:
                df = self.data[asset]
                # 80/20 Split
                split_idx = int(len(df) * 0.8)
                train_df = df.iloc[:split_idx]
                val_df = df.iloc[split_idx:]
                
                train_res = self.run_test(train_df, mode)
                val_res = self.run_test(val_df, mode)
                
                mode_results[asset] = {
                    "train_pf": train_res["pf"],
                    "val_pf": val_res["pf"],
                    "decay": val_res["pf"] / train_res["pf"] if train_res["pf"] > 0 else 0,
                    "val_pnl": val_res["net_pnl_pct"]
                }
            results[mode] = mode_results
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = DynamicExitTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    
    # Compare Fixed ATR (baseline) vs Trailing ATR vs Kijun-Sen
    # Note: For Fixed ATR, we have to modify run_test slightly or just use a very high target.
    # Let's compare Trailing vs Kijun.
    modes = ["trailing", "kijun"]
    res = tester.validate_all(modes)
    print(json.dumps(res, indent=2))
