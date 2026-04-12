import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

# Configure logging for autonomous execution
logging.basicConfig(level=logging.INFO, format='%(asctime)s - IG88-EXEC - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from src.quant.indicators import ichimoku, rsi, atr, sma

class SurgicalExecutionEngine:
    """
    The final validated execution engine implementing the High-Magnitude 
    Surgical logic: Volatility Gating, Trailing Stops, and Asset-Specific Params.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Asset-specific parameters found during Project Fingerprint & Stress Tests
        self.asset_params = {
            "SOL/USDT": {"strat": "VOL_GATED_TREND", "stop_mult": 1.5, "vol_gate": 1.2},
            "ETH/USDT": {"strat": "VOL_GATED_TREND", "stop_mult": 1.5, "vol_gate": 1.2},
            "BTC/USDT": {"strat": "VOL_GATED_TREND", "stop_mult": 1.5, "vol_gate": 1.2},
            "LINK/USDT": {"strat": "EXTREME_REV", "stop_mult": 2.5, "target_mult": 3.0},
            "AVAX/USDT": {"strat": "VOL_GATED_TREND", "stop_mult": 1.5, "vol_gate": 1.2},
            "NEAR/USDT": {"strat": "VOL_GATED_TREND", "stop_mult": 1.5, "vol_gate": 1.2},
        }

    def generate_signal(self, asset: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Generates a trade signal based on the validated Surgical logic.
        """
        if asset not in self.asset_params:
            return None
            
        params = self.asset_params[asset]
        
        # Pre-compute indicators
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        ma20 = sma(c, 20)
        atr_v = atr(h, l, c, 14)
        rsi_v = rsi(c, 14)
        ichi = ichimoku(h, l, c)
        cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
        
        # Volatility baseline for gating
        atr_baseline = pd.Series(atr_v).rolling(window=30).mean().values
        
        # Current State
        curr_c = c[-1]
        curr_atr = atr_v[-1]
        curr_rsi = rsi_v[-1]
        curr_cloud = cloud_top[-1]
        curr_baseline = atr_baseline[-1]
        
        # 1. VOL_GATED_TREND Logic
        if params['strat'] == "VOL_GATED_TREND":
            vol_condition = curr_atr > (curr_baseline * params['vol_gate'])
            trend_condition = (curr_c > curr_cloud) and (curr_rsi > 55)
            
            if vol_condition and trend_condition:
                return {
                    "action": "BUY",
                    "entry_price": curr_c,
                    "stop_loss": curr_c - (params['stop_mult'] * curr_atr),
                    "exit_type": "TRAILING_STOP",
                    "trailing_dist": params['stop_mult'] * curr_atr,
                    "conviction": 0.8,
                    "reason": f"VolGate({curr_atr:.2f} > {curr_baseline*params['vol_gate']:.2f}) + Trend"
                }

        # 2. EXTREME_REV Logic (Specialist for LINK)
        elif params['strat'] == "EXTREME_REV":
            # Calculate B% for the last candle
            rolling_std = pd.Series(c).rolling(window=20).std().values
            bb_lower = ma20[-1] - 2 * rolling_std[-1]
            bb_upper = ma20[-1] + 2 * rolling_std[-1]
            b_pct = (curr_c - bb_lower) / (bb_upper - bb_lower + 1e-9)
            
            if (b_pct <<  0.05) and (curr_rsi <<  25):
                return {
                    "action": "BUY",
                    "entry_price": curr_c,
                    "stop_loss": curr_c - (params['stop_mult'] * curr_atr),
                    "exit_type": "FIXED_TARGET",
                    "target_price": curr_c + (params['target_mult'] * curr_atr),
                    "conviction": 0.7,
                    "reason": f"ExtremeExhaustion(B%:{b_pct:.2f}, RSI:{curr_rsi:.2f})"
                }
        
        return None

if __name__ == "__main__":
    # This allows the script to be used as a module or tested standalone
    print("SurgicalExecutionEngine initialized.")
