"""
Cross-exchange divergence analysis: Binance vs Kraken 4h candle closes.
Compares price divergence for 5 MR pairs to determine if executing signals
generated from Binance data on Kraken would cost more than 0.3% in divergence.
"""

import json
import os
import time
import urllib.request
import urllib.parse
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# Config
BASE_DIR = "/Users/nesbitt/dev/factory/agents/ig88"
DATA_DIR = os.path.join(BASE_DIR, "data")
EDGE_DIR = os.path.join(DATA_DIR, "edge_discovery")
OUTPUT_FILE = os.path.join(EDGE_DIR, "cross_exchange_divergence.json")

# MR pairs with their Binance parquet files and Kraken API pair names
MR_PAIRS = {
    "SOL": {
        "binance_file": os.path.join(DATA_DIR, "binance_SOL_USDT_240m.parquet"),
        "kraken_pair": "SOLUSD"
    },
    "AVAX": {
        "binance_file": os.path.join(DATA_DIR, "binance_AVAX_USDT_240m.parquet"),
        "kraken_pair": "AVAXUSD"
    },
    "ETH": {
        "binance_file": os.path.join(DATA_DIR, "binance_ETH_USDT_240m.parquet"),
        "kraken_pair": "ETHUSD"
    },
    "LINK": {
        "binance_file": os.path.join(DATA_DIR, "binance_LINK_USDT_240m.parquet"),
        "kraken_pair": "LINKUSD"
    },
    "BTC": {
        "binance_file": os.path.join(DATA_DIR, "binance_BTC_USDT_240m.parquet"),
        "kraken_pair": "XBTUSD"
    }
}

# Kraken uses XBT for BTC
KRAKEN_API_URL = "https://api.kraken.com/0/public/OHLC"

def fetch_kraken_ohlc(pair: str, interval: int = 240) -> pd.DataFrame:
    """
    Fetch OHLCV data from Kraken public API.
    Returns DataFrame indexed by UTC datetime with close prices.
    """
    print(f"  Fetching Kraken OHLC for {pair} (interval={interval}m)...")
    
    params = urllib.parse.urlencode({"pair": pair, "interval": interval})
    url = f"{KRAKEN_API_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    data = json.loads(raw.decode())
    
    if data.get("error") and len(data["error"]) > 0:
        raise ValueError(f"Kraken API error: {data['error']}")
    
    result_key = list(data["result"].keys())[0]
    ohlc_data = data["result"][result_key]
    
    # Each entry: [timestamp, open, high, low, close, vwap, volume, count]
    records = []
    for row in ohlc_data:
        ts = int(row[0])
        records.append({
            "datetime": datetime.fromtimestamp(ts, tz=timezone.utc),
            "close": float(row[4]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "volume": float(row[6])
        })
    
    df = pd.DataFrame(records)
    df.set_index("datetime", inplace=True)
    # Sort by time and remove duplicates
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='last')]
    
    print(f"    Got {len(df)} candles, range: {df.index.min()} to {df.index.max()}")
    return df


def load_binance_ohlc(filepath: str) -> pd.DataFrame:
    """
    Load Binance 4h OHLCV from parquet file.
    Returns DataFrame indexed by UTC datetime with close prices.
    """
    df = pd.read_parquet(filepath)
    # Ensure datetime index is timezone-aware UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    # Sort and deduplicate
    df = df.sort_index()
    df = df[~df.index.duplicated(keep='last')]
    return df


def align_timestamps(binance_df: pd.DataFrame, kraken_df: pd.DataFrame) -> pd.DataFrame:
    """
    Align two OHLC DataFrames on common timestamps.
    Returns a DataFrame with columns: binance_close, kraken_close, divergence_pct
    """
    # Get common timestamps
    common_idx = binance_df.index.intersection(kraken_df.index)
    
    if len(common_idx) == 0:
        return pd.DataFrame()
    
    aligned = pd.DataFrame({
        "binance_close": binance_df.loc[common_idx, "close"],
        "kraken_close": kraken_df.loc[common_idx, "close"]
    })
    
    # Calculate percentage divergence: (kraken - binance) / binance * 100
    aligned["divergence_pct"] = ((aligned["kraken_close"] - aligned["binance_close"]) / aligned["binance_close"]) * 100
    
    return aligned


def calculate_divergence_stats(aligned_df: pd.DataFrame) -> dict:
    """
    Calculate divergence statistics from aligned data.
    Returns dict with mean, std, max, p95, median of absolute divergence.
    """
    abs_div = aligned_df["divergence_pct"].abs()
    
    stats = {
        "mean_divergence_pct": round(float(abs_div.mean()), 4),
        "std_divergence_pct": round(float(abs_div.std()), 4),
        "max_divergence_pct": round(float(abs_div.max()), 4),
        "p95_divergence_pct": round(float(abs_div.quantile(0.95)), 4),
        "median_divergence_pct": round(float(abs_div.median()), 4),
        "num_common_candles": len(aligned_df),
        # Also report signed stats for direction bias
        "mean_signed_divergence_pct": round(float(aligned_df["divergence_pct"].mean()), 4),
    }
    
    return stats


def main():
    os.makedirs(EDGE_DIR, exist_ok=True)
    
    results = {
        "analysis_type": "cross_exchange_divergence",
        "description": "Binance vs Kraken 4h close price divergence for MR pairs",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "threshold_pct": 0.3,
        "pairs": {},
        "summary": {}
    }
    
    divergences_above_threshold = []
    
    for asset, config in MR_PAIRS.items():
        print(f"\n=== Processing {asset} ===")
        
        try:
            # Load Binance data
            print(f"  Loading Binance data from {os.path.basename(config['binance_file'])}...")
            binance_df = load_binance_ohlc(config["binance_file"])
            print(f"    Loaded {len(binance_df)} candles, range: {binance_df.index.min()} to {binance_df.index.max()}")
            
            # Fetch Kraken data
            kraken_df = fetch_kraken_ohlc(config["kraken_pair"], interval=240)
            
            # Align timestamps
            aligned = align_timestamps(binance_df, kraken_df)
            
            if aligned.empty:
                print(f"  WARNING: No common timestamps found for {asset}!")
                results["pairs"][asset] = {"error": "No common timestamps found"}
                continue
            
            # Calculate stats
            stats = calculate_divergence_stats(aligned)
            
            # Check time range overlap
            overlap_start = aligned.index.min().isoformat()
            overlap_end = aligned.index.max().isoformat()
            stats["overlap_start"] = overlap_start
            stats["overlap_end"] = overlap_end
            
            results["pairs"][asset] = stats
            
            # Track if above threshold
            if stats["mean_divergence_pct"] > results["threshold_pct"]:
                divergences_above_threshold.append(asset)
            
            print(f"  Mean divergence: {stats['mean_divergence_pct']:.4f}%")
            print(f"  Median divergence: {stats['median_divergence_pct']:.4f}%")
            print(f"  95th pctl: {stats['p95_divergence_pct']:.4f}%")
            print(f"  Max divergence: {stats['max_divergence_pct']:.4f}%")
            print(f"  Common candles: {stats['num_common_candles']}")
            
            # Rate limit between API calls
            time.sleep(1.5)
            
        except Exception as e:
            print(f"  ERROR processing {asset}: {e}")
            results["pairs"][asset] = {"error": str(e)}
    
    # Summary
    valid_pairs = {k: v for k, v in results["pairs"].items() if "error" not in v}
    
    if valid_pairs:
        mean_divs = [v["mean_divergence_pct"] for v in valid_pairs.values()]
        all_mean = np.mean(mean_divs)
        results["summary"] = {
            "overall_mean_divergence_pct": round(float(all_mean), 4),
            "pairs_above_0.3pct_threshold": divergences_above_threshold,
            "any_pair_above_threshold": len(divergences_above_threshold) > 0,
            "recommendation": "",
            "valid_pairs": list(valid_pairs.keys()),
            "failed_pairs": [k for k in results["pairs"] if k not in valid_pairs]
        }
        
        if len(divergences_above_threshold) > 0:
            results["summary"]["recommendation"] = (
                f"CRITICAL: {len(divergences_above_threshold)} pair(s) have mean divergence > 0.3%: "
                f"{', '.join(divergences_above_threshold)}. "
                "Consider using Kraken data for signal generation to avoid execution slippage."
            )
        else:
            results["summary"]["recommendation"] = (
                "OK: No pairs exceed the 0.3% mean divergence threshold. "
                "Executing Binance-generated signals on Kraken should be acceptable."
            )
        
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"Overall mean divergence: {all_mean:.4f}%")
        print(f"Pairs above 0.3% threshold: {divergences_above_threshold if divergences_above_threshold else 'None'}")
        print(f"Recommendation: {results['summary']['recommendation']}")
    
    # Save results
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to: {OUTPUT_FILE}")
    return results


if __name__ == "__main__":
    main()
