import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.quant.indicators import ichimoku, rsi, atr

class MeanReversionMTF:
    """
    Experiment: Mean Reversion for 'Range-Bound' Assets (e.g., LINK, AVAX).
    Hypothesis: In a neutral or slightly bearish 4h regime, 
    extreme 1h/2h oversold conditions lead to a mean-reversion 
    bounce toward the 4h Kijun-sen.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.slow_params = {"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52}
        self.fast_params = {"rsi_period": 14, "rsi_oversold": 30}

    def run_test(self, df_slow: pd.DataFrame, df_fast: pd.DataFrame, friction: float = 0.01):
        # 1. Macro Context (Slow TF)
        c_slow = df_slow['close'].values
        h_slow = df_slow['high'].values
        l_slow = df_slow['low'].values
        ichi_slow = ichimoku(h_slow, l_slow, c_slow, **self.slow_params)
        kijun_slow = ichi_slow.kijun_sen
        
        # 2. Trigger (Fast TF)
        c_fast = df_fast['close'].values
        h_fast = df_fast['high'].values
        l_fast = df_fast['low'].values
        rsi_fast = rsi(c_fast, self.fast_params['rsi_period'])
        atr_fast = atr(h_fast, l_fast, c_fast, 14)
        
        # Alignment
        ratio = 4 # 240m / 60m = 4
        aligned_kijun = np.repeat(kijun_slow, ratio)[:len(c_fast)]
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        # Cap the loop to the smallest available array to avoid index errors
        max_idx = min(len(c_fast), len(aligned_kijun))
        
        for i in range(50, max_idx - 1):
            # Trigger: RSI deeply oversold AND price is significantly below the 4h Kijun
            if not np.isnan(rsi_fast[i]) and not np.isnan(aligned_kijun[i]):
                if rsi_fast[i] < self.fast_params['rsi_oversold'] and c_fast[i] < aligned_kijun[i] * 0.95:
                    entry_price = c_fast[i]
                    total_trades += 1
                    
                    # Target: Mean Reversion to the 4h Kijun
                    target = aligned_kijun[i]
                    # Stop: 2x ATR of the fast timeframe
                    stop = entry_price - 2.0 * atr_fast[i] if not np.isnan(atr_fast[i]) else entry_price * 0.9
                    
                    # Look forward for exit
                    exit_price = c_fast[-1]
                    for j in range(i+1, len(c_fast)):
                        if c_fast[j] <= stop:
                            exit_price = stop
                            break
                        if c_fast[j] >= target:
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

if __name__ == "__main__":
    DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    assets = ["LINKUSDT", "AVAXUSDT", "NEARUSDT"]
    results = {}
    
    engine = MeanReversionMTF({})
    for asset in assets:
        try:
            df_slow = pd.read_parquet(DATA_DIR / f"binance_{asset}_240m.parquet")
            df_fast = pd.read_parquet(DATA_DIR / f"binance_{asset}_60m.parquet")
            results[asset] = engine.run_test(df_slow, df_fast)
        except Exception as e:
            results[asset] = f"ERROR: {e}"
            
    print(json.dumps(results, indent=2))
