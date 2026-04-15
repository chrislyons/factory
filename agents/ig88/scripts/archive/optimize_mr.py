import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
import json
import itertools
from src.quant.indicators import rsi, sma, atr

class MeanReversionOptimizer:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.data = self._load_all_data()
        
    def _load_all_data(self) -> Dict[str, pd.DataFrame]:
        data = {}
        for asset in self.asset_list:
            symbol = asset.replace('/', '_')
            # try both underscore and no underscore variants
            path = self.data_dir / f"binance_{symbol}_240m.parquet"
            if not path.exists():
                # try USDT vs USD? ignore for now
                continue
            df = pd.read_parquet(path)
            # ensure datetime index
            if 'datetime' in df.columns:
                df = df.set_index('datetime')
            data[asset] = df
        return data
    
    def compute_indicators(self, df: pd.DataFrame, bb_std: float, vol_period: int = 20) -> Dict[str, np.ndarray]:
        """Compute all indicators needed for mean reversion."""
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        v = df['volume'].values
        
        ma = sma(c, 20)
        rolling_std = pd.Series(c).rolling(window=20).std().values
        
        upper = ma + bb_std * rolling_std
        lower = ma - bb_std * rolling_std
        
        # Percent B: (Price - Lower) / (Upper - Lower)
        diff = upper - lower
        diff[diff == 0] = 1e-9
        b_pct = (c - lower) / diff
        
        rsi_v = rsi(c, 14)
        atr_v = atr(h, l, c, 14)
        
        # Rolling average volume
        vol_sma = pd.Series(v).rolling(window=vol_period).mean().values
        
        return {
            'close': c,
            'high': h,
            'low': l,
            'volume': v,
            'ma': ma,
            'upper': upper,
            'lower': lower,
            'b_pct': b_pct,
            'rsi': rsi_v,
            'atr': atr_v,
            'vol_sma': vol_sma
        }
    
    def run_backtest(self, df: pd.DataFrame, 
                     rsi_threshold: float,
                     bb_std: float,
                     volume_threshold: float,
                     entry_timing: int,  # 0,1,2
                     friction: float = 0.0025,
                     b_threshold: float = 0.2) -> Dict[str, Any]:
        """Run backtest with given parameters."""
        ind = self.compute_indicators(df, bb_std)
        c = ind['close']
        b_pct = ind['b_pct']
        rsi_v = ind['rsi']
        atr_v = ind['atr']
        vol = ind['volume']
        vol_sma = ind['vol_sma']
        
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        
        # start from 20 to have indicators ready
        for i in range(20, len(c) - 1):
            # Check if entry conditions met at candle i
            # Volume condition
            if vol_sma[i] == 0 or np.isnan(vol_sma[i]):
                continue
            vol_ratio = vol[i] / vol_sma[i]
            if vol_ratio < volume_threshold:
                continue
            # RSI and BB condition
            if b_pct[i] < b_threshold and rsi_v[i] < rsi_threshold:
                # Determine entry candle based on timing
                entry_idx = i + entry_timing
                if entry_idx >= len(c):
                    continue
                entry_price = c[entry_idx]
                # Use ATR at signal candle i (or entry candle?)
                atr_entry = atr_v[i] if not np.isnan(atr_v[i]) else atr_v[entry_idx]
                if np.isnan(atr_entry):
                    continue
                stop = entry_price - 2 * atr_entry
                target = entry_price + 3 * atr_entry
                
                total_trades += 1
                # Look forward from entry_idx+1
                for j in range(entry_idx + 1, len(c)):
                    if c[j] <= stop:
                        gross_losses += ((entry_price - stop) / entry_price) + friction
                        break
                    if c[j] >= target:
                        gross_wins += ((target - entry_price) / entry_price) - friction
                        total_wins += 1
                        break
                    if j == len(c) - 1:
                        pnl = (c[j] - entry_price) / entry_price
                        if pnl > 0:
                            gross_wins += (pnl - friction)
                            total_wins += 1
                        else:
                            gross_losses += (abs(pnl) + friction)
                        break
        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        net_pnl_pct = (gross_wins - gross_losses) * 100
        
        return {
            'trades': total_trades,
            'win_rate': win_rate,
            'pf': pf,
            'net_pnl_pct': net_pnl_pct,
            'gross_wins': gross_wins,
            'gross_losses': gross_losses
        }
    
    def grid_search(self, 
                    rsi_thresholds: List[float],
                    bb_stds: List[float],
                    volume_thresholds: List[float],
                    entry_timings: List[int]) -> Dict[str, Any]:
        """Perform grid search across all parameter combinations."""
        param_combos = list(itertools.product(rsi_thresholds, bb_stds, volume_thresholds, entry_timings))
        print(f"Total parameter combinations: {len(param_combos)}")
        
        all_results = {}
        best_per_pair = {}
        
        for asset in self.asset_list:
            if asset not in self.data:
                print(f"Missing data for {asset}, skipping")
                continue
            df = self.data[asset]
            pair_results = []
            
            for combo in param_combos:
                rsi_thresh, bb_std, vol_thresh, entry_timing = combo
                metrics = self.run_backtest(df, rsi_thresh, bb_std, vol_thresh, entry_timing)
                metrics['params'] = {
                    'rsi_threshold': rsi_thresh,
                    'bb_std': bb_std,
                    'volume_threshold': vol_thresh,
                    'entry_timing': entry_timing
                }
                pair_results.append(metrics)
            
            # Find best combination based on net PnL (or profit factor)
            # We'll sort by net_pnl descending
            pair_results.sort(key=lambda x: x['net_pnl_pct'], reverse=True)
            best = pair_results[0] if pair_results else None
            best_per_pair[asset] = best
            all_results[asset] = pair_results
            print(f"Asset {asset}: best params {best['params']} with net PnL {best['net_pnl_pct']:.2f}%, PF {best['pf']:.3f}")
        
        # Aggregate metrics across pairs for their best combos
        aggregate = {
            'total_trades': sum([b['trades'] for b in best_per_pair.values()]),
            'avg_win_rate': np.mean([b['win_rate'] for b in best_per_pair.values()]),
            'avg_pf': np.mean([b['pf'] for b in best_per_pair.values() if b['pf'] != float('inf')]),
            'total_net_pnl_pct': sum([b['net_pnl_pct'] for b in best_per_pair.values()]),
            'best_per_pair': {k: {'params': v['params'], 'metrics': {key: val for key, val in v.items() if key != 'params'}} for k, v in best_per_pair.items()}
        }
        
        return {
            'detailed_results': all_results,
            'best_per_pair': best_per_pair,
            'aggregate': aggregate
        }

def main():
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    data_dir = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    optimizer = MeanReversionOptimizer(assets, data_dir)
    
    # Define parameter grid
    rsi_thresholds = [30, 32, 35, 38, 40]
    bb_stds = [0.5, 1.0, 1.5, 2.0]
    volume_thresholds = [1.1, 1.2, 1.3, 1.5]
    entry_timings = [0, 1, 2]  # T0, T1, T2
    
    results = optimizer.grid_search(rsi_thresholds, bb_stds, volume_thresholds, entry_timings)
    
    # Save results
    output_path = data_dir / "mr_optimization_results.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {output_path}")
    
    # Print summary
    print("\n=== BEST PARAMETER COMBOS PER PAIR ===")
    for asset, best in results['best_per_pair'].items():
        print(f"{asset}: {best['params']} -> Net PnL {best['net_pnl_pct']:.2f}%, PF {best['pf']:.3f}, WR {best['win_rate']:.1f}%, Trades {best['trades']}")
    
    print(f"\nAggregate: {results['aggregate']['total_trades']} trades, Avg WR {results['aggregate']['avg_win_rate']:.1f}%, Avg PF {results['aggregate']['avg_pf']:.3f}, Total Net PnL {results['aggregate']['total_net_pnl_pct']:.2f}%")

if __name__ == "__main__":
    main()