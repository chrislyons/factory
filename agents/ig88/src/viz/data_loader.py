"""
IG-88 Visualization Data Loader
================================
Unified interface for loading real data into Manim scenes.
All scenes call these functions instead of using hardcoded values.

Data sources:
- state/paper_trading/portfolio.json (paper trading state)
- data/binance_*_240m.parquet (OHLCV data)
- data/*.json (backtest results)
- data/current_regime.json (regime state)
"""
import json
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
STATE_DIR = PROJECT_ROOT / "state"
DATA_DIR = PROJECT_ROOT / "data"


def load_json(path, default=None):
    """Load JSON file, return default if not found."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_paper_trading_state():
    """Load paper trading portfolio state."""
    return load_json(STATE_DIR / "paper_trading" / "portfolio.json", {
        "positions": {},
        "completed_trades": [],
        "scan_count": 0,
        "stats": {
            "scan_count": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "profit_factor": 0
        },
        "last_update": "No data"
    })


def load_regime_state():
    """Load current market regime."""
    return load_json(DATA_DIR / "current_regime.json", {
        "state": "UNKNOWN",
        "severity": "LOW",
        "message": "No data",
        "pair_data": {}
    })


def load_ohlcv(pair="SOL", timeframe="240m", exchange="binance"):
    """
    Load OHLCV data from parquet file.
    Returns dict with keys: times, open, high, low, close, volume
    or None if file not found.
    """
    # Convert pair format: SOL -> SOLUSDT
    if "-" in pair:
        symbol = pair.replace("-", "")
    elif not pair.endswith("USDT"):
        symbol = f"{pair}USDT"
    else:
        symbol = pair
    
    # Try multiple path formats
    paths_to_try = [
        DATA_DIR / f"{exchange}_{symbol}_{timeframe}.parquet",
        DATA_DIR / f"{exchange}_{pair.replace('-', '_')}_{timeframe}.parquet",
        DATA_DIR / f"{exchange}_{pair}_{timeframe}.parquet",
    ]
    
    for path in paths_to_try:
        if path.exists():
            try:
                try:
                    import pandas as pd
                except ImportError:
                    return None  # pandas not available, use fallback
                df = pd.read_parquet(path)
                # Normalize column names
                col_map = {
                    'timestamp': 'times', 'time': 'times', 'date': 'times',
                    'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close',
                    'volume': 'volume', 'vol': 'volume',
                }
                df.columns = [col_map.get(c.lower(), c.lower()) for c in df.columns]
                
                required = ['times', 'open', 'high', 'low', 'close', 'volume']
                if all(c in df.columns for c in required):
                    return {
                        'times': df['times'].values,
                        'open': df['open'].values.astype(float),
                        'high': df['high'].values.astype(float),
                        'low': df['low'].values.astype(float),
                        'close': df['close'].values.astype(float),
                        'volume': df['volume'].values.astype(float),
                    }
            except Exception as e:
                print(f"Error loading {path}: {e}")
                continue
    
    return None


def load_backtest_results(name="mr"):
    """
    Load backtest results from JSON.
    Returns dict with equity curve, trades, stats.
    """
    path_map = {
        "mr": DATA_DIR / "mr_results.json",
        "h3": DATA_DIR / "h3_results.json",
        "convergence": DATA_DIR / "convergence_results.json",
        "combo": DATA_DIR / "combo_research_results.json",
    }
    
    path = path_map.get(name, DATA_DIR / f"{name}_results.json")
    return load_json(path)


def load_equity_curve_from_trades(trades, initial_capital=10000):
    """
    Compute equity curve from list of trades.
    Each trade needs: pnl_pct or pnl
    """
    if not trades:
        return None, None
    
    equity = [initial_capital]
    for trade in trades:
        pnl_pct = trade.get("pnl_pct", trade.get("pnl", 0))
        if isinstance(pnl_pct, float) and abs(pnl_pct) > 1:
            # Already in percentage
            new_val = equity[-1] * (1 + pnl_pct / 100)
        else:
            # Assume fractional
            new_val = equity[-1] * (1 + pnl_pct)
        equity.append(new_val)
    
    return equity, trades


def compute_stats(equity_curve, trades, initial_capital=10000):
    """Compute performance statistics from equity curve and trades."""
    if not equity_curve or len(equity_curve) < 2:
        return {
            "total_return": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "final_value": initial_capital,
            "n_trades": 0,
        }
    
    final_value = equity_curve[-1]
    total_return = (final_value - initial_capital) / initial_capital * 100
    
    wins = sum(1 for t in trades if t.get("type") == "win" or t.get("pnl", 0) > 0)
    n_trades = len(trades)
    win_rate = wins / n_trades * 100 if n_trades > 0 else 0
    
    gross_wins = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
    gross_losses = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")
    
    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    return {
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": -max_dd,
        "final_value": final_value,
        "n_trades": n_trades,
    }


def generate_synthetic_equity(n_trades=50, wr=0.58, rr_ratio=1.8, initial=10000, seed=42):
    """Fallback: generate synthetic equity curve when no real data."""
    rng = np.random.default_rng(seed)
    wallet = initial
    equity = [wallet]
    trades = []
    for i in range(n_trades):
        is_winner = rng.random() < wr
        pnl = wallet * 0.02 * rr_ratio if is_winner else -wallet * 0.02
        wallet += pnl
        equity.append(wallet)
        trades.append({
            "pnl": pnl,
            "pnl_pct": pnl / equity[-2] * 100,
            "type": "win" if is_winner else "loss"
        })
    return equity, trades


def generate_synthetic_prices(n_bars=80, trend_strength=0.3, start_price=100.0, seed=42):
    """Fallback: generate synthetic price data for Ichimoku demo."""
    rng = np.random.default_rng(seed)
    close = start_price
    prices = [close]
    for _ in range(n_bars - 1):
        close = close + trend_strength * 0.1 + rng.standard_normal() * 2.0
        close = max(close, start_price * 0.8)
        prices.append(close)
    return np.array(prices)
