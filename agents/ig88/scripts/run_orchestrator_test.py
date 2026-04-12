import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class StrategyOrchestrator:
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

    def compute_regime_and_signals(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        # 1. Base Indicators
        ma20 = sma(c, 20)
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        ichi = ichimoku(h, l, c)
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        
        # 2. Volatility Squeeze
        rolling_std = pd.Series(c).rolling(window=20).std().values
        bb_upper = ma20 + 2 * rolling_std
        bb_lower = ma20 - 2 * rolling_std
        kc_upper = ma20 + 1.5 * atr_v
        kc_lower = ma20 - 1.5 * atr_v
        squeeze = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(int)
        release = (np.roll(squeeze, 1) == 1) & (squeeze == 0)
        
        # 3. Bollinger %B
        diff = bb_upper - bb_lower
        diff[diff == 0] = 1e-9
        b_pct = (c - bb_lower) / diff
        
        # --- MODULE SIGNALS ---
        sig_trend = (c > cloud_top) & (rsi_v > 55)
        sig_mean_rev = (b_pct < 0.2) & (rsi_v < 30)
        sig_breakout = (release) & (c > ma20)
        
        return {
            "close": c,
            "atr": atr_v,
            "regime_squeeze": squeeze,
            "sig_trend": sig_trend,
            "sig_mean_rev": sig_mean_rev,
            "sig_breakout": sig_breakout
        }

    def run_orchestrated_test(self, df: pd.DataFrame, friction: float = 0.002) -> Dict[str, Any]:
        p = self.compute_regime_and_signals(df)
        c = p['close']
        atr_v = p['atr']
        squeeze = p['regime_squeeze']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(20, len(c)-1):
            entry_price = None
            target_mult = 0
            stop_mult = 2.0
            
            if squeeze[i] == 1:
                if p['sig_mean_rev'][i]:
                    entry_price = c[i]
                    target_mult = 3.0
            else:
                if p['sig_breakout'][i]:
                    entry_price = c[i]
                    target_mult = 4.0
                elif p['sig_trend'][i]:
                    entry_price = c[i]
                    target_mult = 5.0
            
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
        return {"trades": total_trades, "win_rate": win_rate, "pf": pf, "net_pnl_pct": (gross_wins - gross_losses)*100}

    def validate_portfolio(self):
        results = {}
        for asset in self.asset_list:
            if asset not in self.data: continue
            df = self.data[asset]
            split_idx = int(len(df) * 0.8)
            train_df = df.iloc[:split_idx]
            val_df = df.iloc[split_idx:]
            
            train_res = self.run_orchestrated_test(train_df)
            val_res = self.run_orchestrated_test(val_df)
            
            results[asset] = {
                "train_pf": train_res["pf"],
                "val_pf": val_res["pf"],
                "val_pnl": val_res["net_pnl_pct"],
                "val_trades": val_res["trades"]
            }
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    orchestrator = StrategyOrchestrator(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    res = orchestrator.validate_portfolio()
    print(json.dumps(res, indent=2))
