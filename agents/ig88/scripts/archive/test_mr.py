import sys
sys.path.insert(0, '.')
from scripts.optimize_mr import MeanReversionOptimizer
from pathlib import Path

assets = ["BTC/USDT"]
data_dir = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
optimizer = MeanReversionOptimizer(assets, data_dir)
print(f"Loaded data for assets: {list(optimizer.data.keys())}")

# Test compute_indicators
df = optimizer.data["BTC/USDT"]
print(f"DataFrame shape: {df.shape}")
ind = optimizer.compute_indicators(df, bb_std=1.0)
print("Indicators computed")

# Test run_backtest with one combo
metrics = optimizer.run_backtest(df, rsi_threshold=35, bb_std=1.0, volume_threshold=1.2, entry_timing=0)
print("Backtest results:", metrics)

# Quick grid search with small grid
rsi_thresholds = [30, 35]
bb_stds = [1.0]
volume_thresholds = [1.2]
entry_timings = [0]
results = optimizer.grid_search(rsi_thresholds, bb_stds, volume_thresholds, entry_timings)
print("Grid search done")
print("Best per pair:", results['best_per_pair'])