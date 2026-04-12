import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class MTFExecutionEngine:
    """
    Multi-Timeframe (MTF) Execution Engine - SURGICAL VERSION.
    Architecture:
    - Macro Filter: 4h Ichimoku Cloud (Bullish Trend)
    - Signal Trigger: 2h/1h "Surgical" Setup (TK Cross + Above Cloud + Vol Gate)
    - Logic: Nested Alpha. We look for a structural setup on the fast TF 
      that aligns with the structural trend of the slow TF.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Macro filter (4h)
        self.macro_params = {"tenkan": 9, "kijun": 26, "senkou_b": 52}
        # Signal trigger (Fast TF) - mirroring the surgical parameters
        self.signal_params = {
            "tenkan": 9, 
            "kijun": 26, 
            "senkou_b": 52,
            "vol_gate": 1.2,
            "rsi_threshold": 55
        }

    def compute_macro_filter(self, df_4h: pd.DataFrame) -> np.ndarray:
        """Returns boolean array: True if price is above the 4h cloud."""
        c = df_4h['close'].values
        h = df_4h['high'].values
        l = df_4h['low'].values
        
        ichi = ichimoku(h, l, c, 
                        tenkan_period=self.macro_params['tenkan'], 
                        kijun_period=self.macro_params['kijun'], 
                        senkou_b_period=self.macro_params['senkou_b'])
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        return c > cloud_top

    def compute_surgical_trigger(self, df_fast: pd.DataFrame) -> np.ndarray:
        """
        Implements the nested Surgical logic on the fast timeframe.
        T-K cross + Above Cloud + RSI + Vol Gate.
        """
        c = df_fast['close'].values
        h = df_fast['high'].values
        l = df_fast['low'].values
        
        # Indicators for fast TF
        ichi = ichimoku(h, l, c, 
                        tenkan_period=self.signal_params['tenkan'], 
                        kijun_period=self.signal_params['kijun'], 
                        senkou_b_period=self.signal_params['senkou_b'])
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        atr_baseline = pd.Series(atr_v).rolling(window=30).mean().values
        
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        
        # Signal Generation
        signals = np.zeros(len(c), dtype=bool)
        for i in range(50, len(c)):
            # 1. TK Cross
            tk_cross = (ichi.tenkan_sen[i] > ichi.kijun_sen[i]) and \
                       (ichi.tenkan_sen[i-1] <= ichi.kijun_sen[i-1])
            # 2. Above Cloud
            above_cloud = c[i] > cloud_top[i]
            # 3. RSI Momentum
            rsi_ok = rsi_v[i] > self.signal_params['rsi_threshold']
            # 4. Volatility Gate
            vol_ok = atr_v[i] > (atr_baseline[i] * self.signal_params['vol_gate'])
            
            if tk_cross and above_cloud and rsi_ok and vol_ok:
                signals[i] = True
                
        return signals

    def backtest_mtf(self, df_slow: pd.DataFrame, df_fast: pd.DataFrame, friction: float = 0.01):
        # 1. Macro Filter (Slow TF)
        macro_filter = self.compute_macro_filter(df_slow)
        
        # 2. Surgical Trigger (Fast TF)
        signal_trigger = self.compute_surgical_trigger(df_fast)
        
        # 3. Align timeframes
        ratio = len(df_fast) // len(df_slow)
        aligned_macro = np.repeat(macro_filter, ratio)
        
        min_len = min(len(aligned_macro), len(signal_trigger))
        aligned_macro = aligned_macro[:min_len]
        signal_trigger = signal_trigger[:min_len]
        
        c_fast = df_fast['close'].values[:min_len]
        h_fast = df_fast['high'].values[:min_len]
        l_fast = df_fast['low'].values[:min_len]
        atr_fast = atr(h_fast, l_fast, c_fast, 14)
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        for i in range(50, min_len - 1):
            # Nested Alpha: Macro Trend AND Micro Setup
            if aligned_macro[i] and signal_trigger[i]:
                entry_price = c_fast[i]
                total_trades += 1
                
                stop = entry_price - 2.0 * atr_fast[i]
                target = entry_price + 5.0 * atr_fast[i]
                
                exit_price = c_fast[-1]
                for j in range(i+1, min_len):
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
    print("MTFExecutionEngine (Surgical) initialized.")
