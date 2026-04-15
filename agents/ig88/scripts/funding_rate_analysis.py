#!/usr/bin/env python3
"""Funding Rate Arbitrage Analysis - Binance ETH Perps (proxy for Jupiter)"""

import urllib.request
import json
import statistics
from datetime import datetime, timezone

def fetch_funding_rates():
    """Fetch historical funding rates from Binance"""
    url = 'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&limit=1000'
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    return data

def analyze_rates(rates):
    """Analyze funding rate patterns"""
    funding_rates = [float(r['fundingRate']) for r in rates]
    timestamps = [int(r['fundingTime']) for r in rates]
    
    # Basic stats
    avg_rate = statistics.mean(funding_rates)
    median_rate = statistics.median(funding_rates)
    stdev = statistics.stdev(funding_rates) if len(funding_rates) > 1 else 0
    
    # Frequency analysis
    above_5bps = sum(1 for r in funding_rates if r > 0.0005)
    above_10bps = sum(1 for r in funding_rates if r > 0.0010)
    above_20bps = sum(1 for r in funding_rates if r > 0.0020)
    below_neg3bps = sum(1 for r in funding_rates if r < -0.0003)
    below_neg5bps = sum(1 for r in funding_rates if r < -0.0005)
    
    total = len(funding_rates)
    
    # Distribution percentiles
    sorted_rates = sorted(funding_rates)
    p25 = sorted_rates[int(total * 0.25)]
    p50 = sorted_rates[int(total * 0.50)]
    p75 = sorted_rates[int(total * 0.75)]
    p90 = sorted_rates[int(total * 0.90)]
    p95 = sorted_rates[int(total * 0.95)]
    p99 = sorted_rates[int(total * 0.99)]
    max_rate = max(funding_rates)
    min_rate = min(funding_rates)
    
    # Check for clustering (predictable spikes)
    consecutive_high = 0
    max_consecutive_high = 0
    for r in funding_rates:
        if r > 0.0005:
            consecutive_high += 1
            max_consecutive_high = max(max_consecutive_high, consecutive_high)
        else:
            consecutive_high = 0
    
    # Funding rate momentum (does current predict next?)
    positive_then_positive = 0
    positive_count = 0
    negative_then_negative = 0
    negative_count = 0
    for i in range(len(funding_rates) - 1):
        if funding_rates[i] > 0:
            positive_count += 1
            if funding_rates[i+1] > 0:
                positive_then_positive += 1
        if funding_rates[i] < 0:
            negative_count += 1
            if funding_rates[i+1] < 0:
                negative_then_negative += 1
    
    pos_persistence = positive_then_positive / positive_count if positive_count > 0 else 0
    neg_persistence = negative_then_negative / negative_count if negative_count > 0 else 0
    
    # Price direction correlation with funding
    # Simple: when funding is very positive, is price about to drop?
    # We can't get price data easily here, but we can note the persistence
    
    # Strategy backtest
    strategy_results = backtest_strategy(rates, funding_rates)
    
    # Time span
    start_date = datetime.fromtimestamp(timestamps[0] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(timestamps[-1] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    days_span = (timestamps[-1] - timestamps[0]) / (1000 * 86400)
    
    return {
        "data_period": {
            "start": start_date,
            "end": end_date,
            "total_periods": total,
            "days_span": round(days_span, 1),
            "periods_per_day": round(total / days_span, 2) if days_span > 0 else 0
        },
        "basic_stats": {
            "average_rate_8h_pct": round(avg_rate * 100, 4),
            "median_rate_8h_pct": round(median_rate * 100, 4),
            "stdev_pct": round(stdev * 100, 4),
            "annualized_avg_pct": round(avg_rate * 3 * 365 * 100, 2),  # 3 periods per day
            "max_rate_pct": round(max_rate * 100, 4),
            "min_rate_pct": round(min_rate * 100, 4)
        },
        "distribution": {
            "p25_pct": round(p25 * 100, 4),
            "p50_pct": round(p50 * 100, 4),
            "p75_pct": round(p75 * 100, 4),
            "p90_pct": round(p90 * 100, 4),
            "p95_pct": round(p95 * 100, 4),
            "p99_pct": round(p99 * 100, 4)
        },
        "frequency_analysis": {
            "above_5bps": {"count": above_5bps, "pct": round(100 * above_5bps / total, 2)},
            "above_10bps": {"count": above_10bps, "pct": round(100 * above_10bps / total, 2)},
            "above_20bps": {"count": above_20bps, "pct": round(100 * above_20bps / total, 2)},
            "below_neg3bps": {"count": below_neg3bps, "pct": round(100 * below_neg3bps / total, 2)},
            "below_neg5bps": {"count": below_neg5bps, "pct": round(100 * below_neg5bps / total, 2)},
            "max_consecutive_high_periods": max_consecutive_high
        },
        "persistence": {
            "positive_persistence_pct": round(pos_persistence * 100, 2),
            "negative_persistence_pct": round(neg_persistence * 100, 2),
            "interpretation": "High persistence means funding trends continue - good for holding positions"
        },
        "strategy_backtest": strategy_results
    }

def backtest_strategy(rates, funding_rates):
    """Backtest the funding capture strategy"""
    # Strategy: SHORT when funding > 0.05%, LONG when funding < -0.03%, close when |funding| < 0.01%
    
    position = None  # None, 'short', 'long'
    entry_idx = None
    total_pnl = 0
    trades = []
    periods_in_position = 0
    periods_short = 0
    periods_long = 0
    
    for i, rate in enumerate(funding_rates):
        if position is None:
            if rate > 0.0005:  # > 5bps
                position = 'short'
                entry_idx = i
            elif rate < -0.0003:  # < -3bps
                position = 'long'
                entry_idx = i
        elif position == 'short':
            periods_short += 1
            periods_in_position += 1
            total_pnl += rate  # Short collects positive funding
            if abs(rate) < 0.0001:  # Close when normalized
                trades.append({'type': 'short', 'entry': entry_idx, 'exit': i, 'periods': i - entry_idx, 'pnl_pct': round(total_pnl * 100, 4)})
                position = None
                entry_idx = None
        elif position == 'long':
            periods_long += 1
            periods_in_position += 1
            total_pnl += abs(rate)  # Long collects when funding is negative (longs get paid)
            if abs(rate) < 0.0001:  # Close when normalized
                trades.append({'type': 'long', 'entry': entry_idx, 'exit': i, 'periods': i - entry_idx, 'pnl_pct': round(total_pnl * 100, 4)})
                position = None
                entry_idx = None
    
    # Calculate various threshold scenarios
    scenarios = {}
    for threshold_name, long_threshold, short_threshold in [
        ("conservative_3bps", 0.0003, 0.0003),
        ("moderate_5bps", 0.0005, 0.0005),
        ("aggressive_10bps", 0.0010, 0.0010),
    ]:
        s_pnl = 0
        s_periods = 0
        for rate in funding_rates:
            if rate > short_threshold:
                s_pnl += rate
                s_periods += 1
            elif rate < -long_threshold:
                s_pnl += abs(rate)
                s_periods += 1
        
        total_possible = len(funding_rates)
        days = total_possible / 3
        annual_return = (s_pnl / days) * 365 * 100 if days > 0 else 0
        
        scenarios[threshold_name] = {
            "total_return_pct": round(s_pnl * 100, 4),
            "active_periods": s_periods,
            "active_pct": round(100 * s_periods / total_possible, 2),
            "annualized_return_pct": round(annual_return, 2)
        }
    
    # Simple always-collect strategy (just short when positive, long when negative)
    always_collect_pnl = sum(r if r > 0 else abs(r) for r in funding_rates if abs(r) > 0.0001)
    days = len(funding_rates) / 3
    always_annual = (always_collect_pnl / days) * 365 * 100 if days > 0 else 0
    
    return {
        "strategy_rules": {
            "short_entry": "funding > 0.05% (5 bps)",
            "long_entry": "funding < -0.03% (-3 bps)",
            "exit": "abs(funding) < 0.01% (1 bp)"
        },
        "trades_executed": len(trades),
        "last_trades_summary": trades[-5:] if trades else [],
        "threshold_scenarios": scenarios,
        "always_collect_1bp": {
            "total_return_pct": round(always_collect_pnl * 100, 4),
            "annualized_return_pct": round(always_annual, 2)
        },
        "position_utilization": {
            "periods_in_position": periods_in_position,
            "periods_short": periods_short,
            "periods_long": periods_long,
            "utilization_pct": round(100 * periods_in_position / len(funding_rates), 2)
        }
    }

def main():
    print("Fetching Binance ETH funding rates...")
    rates = fetch_funding_rates()
    print(f"Fetched {len(rates)} funding rate periods")
    
    print("Analyzing patterns...")
    analysis = analyze_rates(rates)
    
    # Print summary
    print("\n=== FUNDING RATE ANALYSIS SUMMARY ===")
    print(f"Period: {analysis['data_period']['start']} to {analysis['data_period']['end']} ({analysis['data_period']['days_span']} days)")
    print(f"Average funding: {analysis['basic_stats']['average_rate_8h_pct']}% per 8h = {analysis['basic_stats']['annualized_avg_pct']}% annualized")
    print(f"Median funding: {analysis['basic_stats']['median_rate_8h_pct']}% per 8h")
    print(f"Max: {analysis['basic_stats']['max_rate_pct']}%, Min: {analysis['basic_stats']['min_rate_pct']}%")
    print(f"\nDistribution:")
    for k, v in analysis['distribution'].items():
        print(f"  {k}: {v}%")
    print(f"\nFrequency:")
    for k, v in analysis['frequency_analysis'].items():
        print(f"  {k}: {v}")
    print(f"\nThreshold Scenarios:")
    for name, s in analysis['strategy_backtest']['threshold_scenarios'].items():
        print(f"  {name}: {s['annualized_return_pct']}% annual, active {s['active_pct']}% of time")
    print(f"\nAlways collect >1bp: {analysis['strategy_backtest']['always_collect_1bp']['annualized_return_pct']}% annual")
    
    # Save results
    output_path = '/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/funding_rate_arb.json'
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)
    print(f"\nResults saved to {output_path}")

if __name__ == '__main__':
    main()
