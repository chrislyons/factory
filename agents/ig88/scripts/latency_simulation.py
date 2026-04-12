
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timedelta
import sys

root = Path("/Users/nesbitt/dev/factory/agents/ig88")
data_1min = root / "data/sol_usdt_1min.parquet"
output_path = root / "data/latency_simulation_results.json"

sys.path.insert(0, str(root))
import src.quant.indicators as ind

def run_latency_sim():
    if not data_1min.exists():
        print(f"Error: {data_1min} not found")
        return

    df_1m = pd.read_parquet(data_1min)
    if 'datetime' in df_1m.columns:
        df_1m.index = pd.to_datetime(df_1m['datetime'])
    else:
        df_1m.index = pd.to_datetime(df_1m.index)
    df_1m = df_1m.sort_index()

    df_4h = df_1m['close'].resample('4h').last().to_frame()
    df_4h['high'] = df_1m['high'].resample('4h').max()
    df_4h['low'] = df_1m['low'].resample('4h').min()
    df_4h['open'] = df_1m['open'].resample('4h').first()
    df_4h['volume'] = df_1m['volume'].resample('4h').sum()

    h, l, c = df_4h['high'].values, df_4h['low'].values, df_4h['close'].values
    v = df_4h['volume'].values
    
    ichi = ind.ichimoku(h, l, c)
    rsi = ind.rsi(c, 14)
    vol_ma = ind.sma(v, 20)
    
    tk = ichi.tk_cross_signals()
    cloud_top = np.maximum(ichi.senkou_span_a, ichi.senkou_span_b)
    h3a_mask = (tk == 1) & (c > cloud_top) & (rsi > 55)
    
    price_gain = np.zeros_like(c)
    price_gain[1:] = (c[1:] - c[:-1]) / c[:-1]
    h3b_mask = (v > 1.5 * vol_ma) & (price_gain > 0.005) & (rsi > 50)
    
    combined_mask = h3a_mask | h3b_mask
    signal_indices = np.where(combined_mask)[0]
    
    print(f"Detected {len(signal_indices)} signals.")
    
    results = []
    delays = [60, 120, 300]
    
    for idx in signal_indices:
        close_time = df_4h.index[idx]
        close_price = df_4h['close'].iloc[idx]
        entry_data = {"close_price": close_price, "timestamp": close_time}
        
        for d in delays:
            target_time = close_time + timedelta(seconds=d)
            pos = df_1m.index.searchsorted(target_time)
            if pos < len(df_1m):
                actual_price = df_1m['close'].iloc[pos]
                slippage_bps = abs(actual_price - close_price) / close_price * 10000
                entry_data[f"delay_{d}s"] = {"price": actual_price, "slippage_bps": slippage_bps}
            else:
                entry_data[f"delay_{d}s"] = None
        results.append(entry_data)

    metrics = {}
    for d in delays:
        slips = [r[f"delay_{d}s"]["slippage_bps"] for r in results if r.get(f"delay_{d}s")]
        if slips:
            metrics[f"delay_{d}s"] = {
                "mean_bps": float(np.mean(slips)),
                "median_bps": float(np.median(slips)),
                "max_bps": float(np.max(slips)),
                "std_bps": float(np.std(slips))
            }

    with open(output_path, 'w') as f:
        json.dump({"meta": "H3-Combined Latency Simulation", "aggregate_metrics": metrics, "raw_signals": results}, f, indent=2, default=str)
        
    print(json.dumps(metrics, indent=2))

if __name__ == "__main__":
    run_latency_sim()
