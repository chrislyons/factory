#!/usr/bin/env python3
"""
Session Analysis: Time-of-Day and Day-of-Week Edges
Analyzes crypto session patterns (Asia/Europe/US) across all available symbols.
"""

import json
import os
import glob
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
OUTPUT_FILE = "/Users/nesbitt/dev/factory/agents/ig88/data/session_analysis.json"

# Session definitions (UTC hours)
SESSIONS = {
    "Asia":   (0, 8),    # 00:00-08:00 UTC
    "Europe": (8, 16),   # 08:00-16:00 UTC
    "US":     (16, 24),  # 16:00-24:00 UTC
}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def load_all_symbols(data_dir):
    """Load all parquet files and normalize symbol names."""
    files = glob.glob(os.path.join(data_dir, "*.parquet"))
    symbols = {}
    
    # Priority: _1h > _60m > others; skip daily (1440m) and 120m data
    def file_priority(f):
        bn = os.path.basename(f)
        score = 0
        if "_1h" in bn: score += 100
        elif "_60m" in bn: score += 50
        elif "1440m" in bn: score -= 1000  # daily data, skip entirely
        elif "120m" in bn: score -= 50   # 2h data, less preferred
        return score
    
    for f in sorted(files, key=file_priority, reverse=True):
        # Skip daily and 2h files entirely
        bn = os.path.basename(f)
        if "1440m" in bn or "120m" in bn:
            continue
            
        basename = bn.replace(".parquet", "")
        parts = basename.split("_")
        # Extract symbol: e.g., binance_BTCUSDT_1h -> BTCUSDT, binance_BTC_USDT_60m -> BTC
        if len(parts) >= 3:
            symbol = parts[1]
        else:
            symbol = basename
        
        if symbol in symbols:
            continue
        symbols[symbol] = f
    return symbols


def compute_session_stats(df):
    """Compute per-session stats for a single symbol."""
    df = df.copy()
    df["hour"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek  # 0=Monday
    df["day_name"] = df.index.day_name()
    df["session"] = df["hour"].apply(classify_session)
    df["return"] = df["close"].pct_change()
    df["range_pct"] = (df["high"] - df["low"]) / df["open"]
    
    # Handle optional columns
    has_quote_vol = "quote_volume" in df.columns
    has_trades = "trades" in df.columns
    
    # Session analysis
    session_results = {}
    for sess_name, (start, end) in SESSIONS.items():
        mask = df["session"] == sess_name
        sess_data = df[mask]
        if len(sess_data) < 10:
            continue
        session_results[sess_name] = {
            "avg_return": float(sess_data["return"].mean()),
            "median_return": float(sess_data["return"].median()),
            "std_return": float(sess_data["return"].std()),
            "avg_range_pct": float(sess_data["range_pct"].mean()),
            "avg_volume": float(sess_data["volume"].mean()),
            "avg_quote_volume": float(sess_data["quote_volume"].mean()) if has_quote_vol else 0.0,
            "avg_trades": float(sess_data["trades"].mean()) if has_trades else 0.0,
            "count": int(len(sess_data)),
            "pct_positive": float((sess_data["return"] > 0).mean()),
        }
    
    # Day-of-week analysis
    dow_results = {}
    for dow in range(7):
        mask = df["day_of_week"] == dow
        day_data = df[mask]
        if len(day_data) < 5:
            continue
        dow_results[DAYS[dow]] = {
            "avg_return": float(day_data["return"].mean()),
            "median_return": float(day_data["return"].median()),
            "std_return": float(day_data["return"].std()),
            "avg_range_pct": float(day_data["range_pct"].mean()),
            "avg_volume": float(day_data["volume"].mean()),
            "count": int(len(day_data)),
            "pct_positive": float((day_data["return"] > 0).mean()),
        }
    
    # Combined session + day patterns
    combined_results = {}
    for sess_name in SESSIONS:
        for dow in range(7):
            mask = (df["session"] == sess_name) & (df["day_of_week"] == dow)
            cd = df[mask]
            if len(cd) < 3:
                continue
            key = f"{DAYS[dow]}_{sess_name}"
            combined_results[key] = {
                "avg_return": float(cd["return"].mean()),
                "std_return": float(cd["return"].std()),
                "avg_volume": float(cd["volume"].mean()),
                "count": int(len(cd)),
                "pct_positive": float((cd["return"] > 0).mean()),
            }
    
    return session_results, dow_results, combined_results


def classify_session(hour):
    """Classify an hour into a session."""
    if 0 <= hour < 8:
        return "Asia"
    elif 8 <= hour < 16:
        return "Europe"
    else:
        return "US"


def backtest_session_strategy(df, buy_session="Asia", sell_session="US"):
    """
    Backtest: Buy at end of buy_session, sell at end of sell_session.
    Uses walk-forward 60/40 split.
    """
    df = df.copy()
    df["session"] = df.index.hour.map(lambda h: classify_session(h))
    
    # Get session close prices
    # For each day, find the last hour of each session
    df["date"] = df.index.date
    
    trades = []
    for date, group in df.groupby("date"):
        buy_rows = group[group["session"] == buy_session]
        sell_rows = group[group["session"] == sell_session]
        if buy_rows.empty or sell_rows.empty:
            continue
        buy_price = buy_rows.iloc[-1]["close"]
        sell_price = sell_rows.iloc[-1]["close"]
        ret = (sell_price - buy_price) / buy_price
        trades.append({"date": str(date), "buy_price": buy_price, "sell_price": sell_price, "return": ret})
    
    if len(trades) < 20:
        return None
    
    trades_df = pd.DataFrame(trades)
    
    # Walk-forward: 60% train, 40% test
    split_idx = int(len(trades_df) * 0.6)
    train = trades_df.iloc[:split_idx]
    test = trades_df.iloc[split_idx:]
    
    def compute_metrics(tdf):
        if len(tdf) == 0:
            return {}
        returns = tdf["return"].values
        win_rate = (returns > 0).mean()
        avg_ret = returns.mean()
        cum_ret = (1 + returns).prod() - 1
        sharpe = avg_ret / (returns.std() + 1e-9) * np.sqrt(252) if returns.std() > 0 else 0
        max_dd = compute_max_drawdown(returns)
        return {
            "trades": len(returns),
            "win_rate": float(win_rate),
            "avg_return": float(avg_ret),
            "cumulative_return": float(cum_ret),
            "sharpe": float(sharpe),
            "max_drawdown": float(max_dd),
            "best_trade": float(returns.max()),
            "worst_trade": float(returns.min()),
        }
    
    return {
        "train": compute_metrics(train),
        "test": compute_metrics(test),
    }


def compute_max_drawdown(returns):
    """Compute max drawdown from a series of returns."""
    cum = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    return dd.min()


def aggregate_across_symbols(all_results):
    """Aggregate session/dow stats across all symbols."""
    session_agg = {s: [] for s in SESSIONS}
    dow_agg = {d: [] for d in DAYS}
    combined_agg = {}
    
    for sym, data in all_results.items():
        for sess, stats in data.get("session_analysis", {}).items():
            session_agg[sess].append(stats)
        for dow, stats in data.get("day_of_week_analysis", {}).items():
            dow_agg[dow].append(stats)
        for key, stats in data.get("combined_analysis", {}).items():
            if key not in combined_agg:
                combined_agg[key] = []
            combined_agg[key].append(stats)
    
    # Compute averages
    def avg_stats(list_of_stats):
        if not list_of_stats:
            return {}
        keys = list_of_stats[0].keys()
        return {k: float(np.mean([s[k] for s in list_of_stats if k in s])) for k in keys}
    
    return {
        "session_avg": {s: avg_stats(v) for s, v in session_agg.items() if v},
        "day_of_week_avg": {d: avg_stats(v) for d, v in dow_agg.items() if v},
        "combined_avg": {k: avg_stats(v) for k, v in combined_agg.items() if v},
    }


def find_patterns(aggregated):
    """Identify key patterns from aggregated data."""
    patterns = {}
    
    # Session patterns
    session_avg = aggregated.get("session_avg", {})
    if session_avg:
        # Which session has highest avg return?
        best_sess = max(session_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        worst_sess = min(session_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        patterns["best_session_by_return"] = {"session": best_sess[0], "avg_return": best_sess[1].get("avg_return", 0)}
        patterns["worst_session_by_return"] = {"session": worst_sess[0], "avg_return": worst_sess[1].get("avg_return", 0)}
        
        # Which session has most volatility?
        most_vol = max(session_avg.items(), key=lambda x: x[1].get("avg_range_pct", 0))
        patterns["most_volatile_session"] = {"session": most_vol[0], "avg_range_pct": most_vol[1].get("avg_range_pct", 0)}
        
        # Which session has most volume?
        most_vol_session = max(session_avg.items(), key=lambda x: x[1].get("avg_volume", 0))
        patterns["highest_volume_session"] = {"session": most_vol_session[0], "avg_volume": most_vol_session[1].get("avg_volume", 0)}
    
    # Day of week patterns
    dow_avg = aggregated.get("day_of_week_avg", {})
    if dow_avg:
        best_day = max(dow_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        worst_day = min(dow_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        patterns["best_day"] = {"day": best_day[0], "avg_return": best_day[1].get("avg_return", 0)}
        patterns["worst_day"] = {"day": worst_day[0], "avg_return": worst_day[1].get("avg_return", 0)}
    
    # Combined patterns
    combined_avg = aggregated.get("combined_avg", {})
    if combined_avg:
        best_combo = max(combined_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        worst_combo = min(combined_avg.items(), key=lambda x: x[1].get("avg_return", 0))
        patterns["best_session_day_combo"] = {"combo": best_combo[0], "avg_return": best_combo[1].get("avg_return", 0)}
        patterns["worst_session_day_combo"] = {"combo": worst_combo[0], "avg_return": worst_combo[1].get("avg_return", 0)}
    
    # Buy Asia, Sell US pattern
    if "Asia" in session_avg and "US" in session_avg:
        asia_ret = session_avg["Asia"].get("avg_return", 0)
        us_ret = session_avg["US"].get("avg_return", 0)
        patterns["buy_asia_sell_us_edge"] = {
            "asia_avg_return": asia_ret,
            "us_avg_return": us_ret,
            "edge": us_ret - asia_ret,
            "interpretation": "Buy at Asia close, sell at US close" if us_ret > asia_ret else "No clear edge"
        }
    
    # Wednesday dip
    if "Wednesday" in dow_avg:
        wed_ret = dow_avg["Wednesday"].get("avg_return", 0)
        overall_avg = np.mean([v.get("avg_return", 0) for v in dow_avg.values()])
        patterns["wednesday_dip"] = {
            "wednesday_avg_return": wed_ret,
            "overall_avg_return": float(overall_avg),
            "is_dip": wed_ret < overall_avg,
        }
    
    return patterns


def main():
    print("=" * 60)
    print("SESSION ANALYSIS: Time-of-Day & Day-of-Week Edges")
    print("=" * 60)
    
    # Load all symbols
    symbol_files = load_all_symbols(DATA_DIR)
    print(f"\nFound {len(symbol_files)} unique symbols")
    
    all_results = {}
    all_strategies = {}
    
    for sym, fpath in sorted(symbol_files.items()):
        try:
            df = pd.read_parquet(fpath)
            if len(df) < 100:
                print(f"  {sym}: skipped (only {len(df)} rows)")
                continue
            
            # Make sure index is datetime and in UTC
            if not isinstance(df.index, pd.DatetimeIndex):
                continue
            
            sess_stats, dow_stats, combined_stats = compute_session_stats(df)
            
            if not sess_stats:
                print(f"  {sym}: skipped (insufficient session data)")
                continue
            
            all_results[sym] = {
                "session_analysis": sess_stats,
                "day_of_week_analysis": dow_stats,
                "combined_analysis": combined_stats,
            }
            
            # Test multiple strategies
            strategies_to_test = [
                ("buy_asia_sell_us", "Asia", "US"),
                ("buy_europe_sell_us", "Europe", "US"),
                ("buy_asia_sell_europe", "Asia", "Europe"),
            ]
            
            sym_strategies = {}
            for strat_name, buy_s, sell_s in strategies_to_test:
                result = backtest_session_strategy(df, buy_s, sell_s)
                if result:
                    sym_strategies[strat_name] = result
            
            all_strategies[sym] = sym_strategies
            
            # Quick summary
            asia = sess_stats.get("Asia", {})
            us = sess_stats.get("US", {})
            print(f"  {sym}: Asia ret={asia.get('avg_return', 0):.5f}, US ret={us.get('avg_return', 0):.5f}, "
                  f"Asia vol={asia.get('avg_volume', 0):.0f}, US vol={us.get('avg_volume', 0):.0f}")
            
        except Exception as e:
            print(f"  {sym}: ERROR - {e}")
    
    print(f"\nAnalyzed {len(all_results)} symbols successfully")
    
    # Aggregate across symbols
    print("\nAggregating results across all symbols...")
    aggregated = aggregate_across_symbols(all_results)
    
    # Find patterns
    print("Identifying patterns...")
    patterns = find_patterns(aggregated)
    
    # Aggregate strategy results
    strategy_summary = {}
    for strat_name in ["buy_asia_sell_us", "buy_europe_sell_us", "buy_asia_sell_europe"]:
        train_metrics = []
        test_metrics = []
        for sym, strats in all_strategies.items():
            if strat_name in strats:
                s = strats[strat_name]
                if s.get("train") and s["train"].get("trades", 0) > 0:
                    train_metrics.append(s["train"])
                if s.get("test") and s["test"].get("trades", 0) > 0:
                    test_metrics.append(s["test"])
        
        if train_metrics and test_metrics:
            strategy_summary[strat_name] = {
                "train_avg": {
                    "win_rate": float(np.mean([m["win_rate"] for m in train_metrics])),
                    "avg_return": float(np.mean([m["avg_return"] for m in train_metrics])),
                    "sharpe": float(np.mean([m["sharpe"] for m in train_metrics])),
                    "symbols_tested": len(train_metrics),
                },
                "test_avg": {
                    "win_rate": float(np.mean([m["win_rate"] for m in test_metrics])),
                    "avg_return": float(np.mean([m["avg_return"] for m in test_metrics])),
                    "sharpe": float(np.mean([m["sharpe"] for m in test_metrics])),
                    "symbols_tested": len(test_metrics),
                },
            }
    
    # Build final output
    output = {
        "metadata": {
            "symbols_analyzed": len(all_results),
            "sessions": {k: f"{v[0]:02d}:00-{v[1]:02d}:00 UTC" for k, v in SESSIONS.items()},
            "data_source": DATA_DIR,
        },
        "per_symbol": {},
        "aggregated": {
            "session_averages": aggregated["session_avg"],
            "day_of_week_averages": aggregated["day_of_week_avg"],
            "combined_averages": aggregated["combined_avg"],
        },
        "patterns": patterns,
        "strategy_backtest": strategy_summary,
        "per_symbol_strategies": all_strategies,
    }
    
    # Add per-symbol session/dow data
    for sym, data in all_results.items():
        output["per_symbol"][sym] = {
            "session_analysis": data["session_analysis"],
            "day_of_week_analysis": data["day_of_week_analysis"],
        }
    
    # Write results
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults written to {OUTPUT_FILE}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("KEY FINDINGS")
    print("=" * 60)
    
    print("\n--- Session Analysis (Average across all symbols) ---")
    for sess, stats in aggregated["session_avg"].items():
        print(f"  {sess:8s}: avg_return={stats.get('avg_return', 0):.6f}, "
              f"volatility={stats.get('avg_range_pct', 0):.5f}, "
              f"volume={stats.get('avg_volume', 0):.0f}, "
              f"pct_positive={stats.get('pct_positive', 0):.3f}")
    
    print("\n--- Day of Week Analysis ---")
    for day, stats in aggregated["day_of_week_avg"].items():
        print(f"  {day:10s}: avg_return={stats.get('avg_return', 0):.6f}, "
              f"pct_positive={stats.get('pct_positive', 0):.3f}")
    
    print("\n--- Patterns ---")
    for name, pat in patterns.items():
        print(f"  {name}: {pat}")
    
    print("\n--- Strategy Backtest Summary (Walk-Forward 60/40) ---")
    for strat, summary in strategy_summary.items():
        train = summary.get("train_avg", {})
        test = summary.get("test_avg", {})
        print(f"  {strat}:")
        print(f"    Train: win_rate={train.get('win_rate', 0):.3f}, avg_ret={train.get('avg_return', 0):.6f}, sharpe={train.get('sharpe', 0):.3f}")
        print(f"    Test:  win_rate={test.get('win_rate', 0):.3f}, avg_ret={test.get('avg_return', 0):.6f}, sharpe={test.get('sharpe', 0):.3f}")
    
    print("\nDone!")


if __name__ == "__main__":
    main()
