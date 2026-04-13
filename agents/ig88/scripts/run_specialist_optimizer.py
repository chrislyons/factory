import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class AssetSpecialistOptimizer:
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
        v = df['volume'].values
        
        # Base
        ma20 = sma(c, 20)
        ma50 = sma(c, 50)
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        ichi = ichimoku(h, l, c)
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        
        # Volatility/Bands
        rolling_std = pd.Series(c).rolling(window=20).std().values
        bb_upper = ma20 + 2 * rolling_std
        bb_lower = ma20 - 2 * rolling_std
        
        # Squeeze
        kc_upper = ma20 + 1.5 * atr_v
        kc_lower = ma20 - 1.5 * atr_v
        squeeze = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(int)
        release = (np.roll(squeeze, 1) == 1) & (squeeze == 0)
        
        # B%
        diff = bb_upper - bb_lower
        diff[diff == 0] = 1e-9
        b_pct = (c - bb_lower) / diff
        
        return {
            "c": c, "h": h, "l": l, "v": v, "ma20": ma20, "ma50": ma50, 
            "atr": atr_v, "rsi": rsi_v, "cloud_top": cloud_top,
            "bb_upper": bb_upper, "bb_lower": bb_lower, "b_pct": b_pct,
            "squeeze": squeeze, "release": release
        }

    def test_strategy(self, asset: str, strategy_name: str, stop_mult: float, target_mult: float, friction: float = 0.002):
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
            
            # --- STRATEGY ROUTING ---
            if strategy_name == "TREND_H3":
                if (c[i] > p['cloud_top'][i]) and (p['rsi'][i] > 55):
                    entry_price = c[i]
            
            elif strategy_name == "MEAN_REV":
                if (p['b_pct'][i] < 0.2) and (p['rsi'][i] < 30):
                    entry_price = c[i]
            
            elif strategy_name == "SQUEEZE_BREAK":
                if p['release'][i] and (c[i] > p['ma20'][i]):
                    entry_price = c[i]
            
            elif strategy_name == "MOM_SUSTAIN":
                if (c[i] > p['ma20'][i]) and (c[i] > c[i-1]) and (p['rsi'][i] > 65):
                    entry_price = c[i]
            
            elif strategy_name == "VOL_SLING":
                if atr_v[i] > atr_v[i-1] and atr_v[i] > np.mean(atr_v[max(0, i-20):i]):
                    if c[i] > p['ma20'][i]:
                        entry_price = c[i]
            
            elif strategy_name == "SCALP_MEAN":
                if (p['b_pct'][i] < 0.15):
                    entry_price = c[i]
            
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
                        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        return {"trades": total_trades, "win_rate": win_rate, "pf": pf, "net_pnl": (gross_wins - gross_losses)*100}

    def find_best_for_all(self):
        strategies = ["TREND_H3", "MEAN_REV", "SQUEEZE_BREAK", "MOM_SUSTAIN", "VOL_SLING", "SCALP_MEAN"]
        stop_range = [1.5, 2.0, 2.5]
        target_range = [3.0, 4.0, 5.0, 6.0]
        
        final_map = {}
        for asset in self.asset_list:
            best_overall_pf = -1
            best_config = {}
            
            for strat in strategies:
                for s in stop_range:
                    for t in target_range:
                        res = self.test_strategy(asset, strat, s, t)
                        if res["pf"] > best_overall_pf:
                            best_overall_pf = res["pf"]
                            best_config = {"strategy": strat, "stop": s, "target": t, **res}
            
            final_map[asset] = best_config
        return final_map

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    optimizer = AssetSpecialistOptimizer(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    results = optimizer.find_best_for_all()
    print(json.dumps(results, indent=2))
