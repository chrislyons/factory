#!/usr/bin/env python3
"""Extended Funding Rate Analysis - fetch multiple batches to get longer history"""

import urllib.request
import json
import statistics
from datetime import datetime, timezone

def fetch_funding_rates_batch(startTime=None, limit=1000):
    """Fetch funding rates with optional start time"""
    url = f'https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&limit={limit}'
    if startTime:
        url += f'&startTime={startTime}'
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())

def fetch_all_funding_rates():
    """Fetch as much history as possible"""
    all_rates = []
    startTime = None
    
    for _ in range(10):  # Up to 10 batches
        batch = fetch_funding_rates_batch(startTime)
        if not batch:
            break
        all_rates.extend(batch)
        if len(batch) < 1000:
            break
        # Next batch starts after the last timestamp
        startTime = int(batch[-1]['fundingTime']) + 1
        print(f"  Fetched {len(all_rates)} total rates so far...")
    
    return all_rates

def analyze_comprehensive(rates):
    """Comprehensive analysis"""
    funding_rates = [float(r['fundingRate']) for r in rates]
    timestamps = [int(r['fundingTime']) for r in rates]
    
    total = len(funding_rates)
    days_span = (timestamps[-1] - timestamps[0]) / (1000 * 86400)
    start_date = datetime.fromtimestamp(timestamps[0] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    end_date = datetime.fromtimestamp(timestamps[-1] / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
    
    # Basic stats
    avg_rate = statistics.mean(funding_rates)
    median_rate = statistics.median(funding_rates)
    stdev = statistics.stdev(funding_rates)
    
    # Distribution
    sorted_rates = sorted(funding_rates)
    percentiles = {}
    for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        percentiles[f'p{p}'] = round(sorted_rates[int(total * p / 100)] * 100, 4)
    
    # Threshold frequency
    thresholds = [0.0001, 0.0003, 0.0005, 0.0010, 0.0015, 0.0020, 0.0050, 0.0100]
    threshold_counts = {}
    for t in thresholds:
        above = sum(1 for r in funding_rates if r > t)
        below_neg = sum(1 for r in funding_rates if r < -t)
        threshold_counts[f'above_{int(t*10000)}bps'] = {'count': above, 'pct': round(100 * above / total, 2)}
        threshold_counts[f'below_neg_{int(t*10000)}bps'] = {'count': below_neg, 'pct': round(100 * below_neg / total, 2)}
    
    # Monthly breakdown
    monthly = {}
    for i, ts in enumerate(timestamps):
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        key = dt.strftime('%Y-%m')
        if key not in monthly:
            monthly[key] = []
        monthly[key].append(funding_rates[i])
    
    monthly_stats = {}
    for month, rts in sorted(monthly.items()):
        m_avg = statistics.mean(rts)
        m_above5 = sum(1 for r in rts if r > 0.0005)
        m_below_neg3 = sum(1 for r in rts if r < -0.0003)
        monthly_stats[month] = {
            'avg_rate_8h_pct': round(m_avg * 100, 4),
            'annualized_pct': round(m_avg * 3 * 365 * 100, 2),
            'count': len(rts),
            'above_5bps': m_above5,
            'below_neg_3bps': m_below_neg3
        }
    
    # Strategy scenarios with different thresholds
    strategies = {}
    for name, min_short, min_long in [
        ("ultra_conservative", 0.0001, 0.0001),
        ("conservative", 0.0003, 0.0002),
        ("moderate", 0.0005, 0.0003),
        ("aggressive", 0.0010, 0.0005),
        ("ultra_aggressive", 0.0015, 0.0010),
    ]:
        total_collect = 0
        short_periods = 0
        long_periods = 0
        for r in funding_rates:
            if r > min_short:
                total_collect += r
                short_periods += 1
            elif r < -min_long:
                total_collect += abs(r)
                long_periods += 1
        
        active_periods = short_periods + long_periods
        annual = (total_collect / days_span) * 365 * 100 if days_span > 0 else 0
        
        strategies[name] = {
            'short_threshold_bps': round(min_short * 10000, 1),
            'long_threshold_bps': round(min_long * 10000, 1),
            'total_return_pct': round(total_collect * 100, 4),
            'annualized_return_pct': round(annual, 2),
            'short_periods': short_periods,
            'long_periods': long_periods,
            'active_pct': round(100 * active_periods / total, 2),
            'short_pct': round(100 * short_periods / total, 2),
            'long_pct': round(100 * long_periods / total, 2)
        }
    
    # Persistence analysis
    pos_then_pos = 0
    pos_count = 0
    neg_then_neg = 0
    neg_count = 0
    for i in range(len(funding_rates) - 1):
        if funding_rates[i] > 0:
            pos_count += 1
            if funding_rates[i+1] > 0:
                pos_then_pos += 1
        else:
            neg_count += 1
            if funding_rates[i+1] < 0:
                neg_then_neg += 1
    
    # Clustering
    max_consec_pos_5bps = 0
    cur_consec = 0
    for r in funding_rates:
        if r > 0.0005:
            cur_consec += 1
            max_consec_pos_5bps = max(max_consec_pos_5bps, cur_consec)
        else:
            cur_consec = 0
    
    return {
        "metadata": {
            "start": start_date,
            "end": end_date,
            "total_periods": total,
            "days_span": round(days_span, 1),
            "source": "Binance ETHUSDT Perpetual"
        },
        "summary": {
            "avg_rate_8h_pct": round(avg_rate * 100, 4),
            "median_rate_8h_pct": round(median_rate * 100, 4),
            "stdev_pct": round(stdev * 100, 4),
            "annualized_avg_pct": round(avg_rate * 3 * 365 * 100, 2),
            "max_rate_pct": round(max(funding_rates) * 100, 4),
            "min_rate_pct": round(min(funding_rates) * 100, 4)
        },
        "distribution_percentiles": percentiles,
        "threshold_frequency": threshold_counts,
        "monthly_breakdown": monthly_stats,
        "strategy_scenarios": strategies,
        "persistence": {
            "positive_continuation_pct": round(100 * pos_then_pos / pos_count, 2) if pos_count > 0 else 0,
            "negative_continuation_pct": round(100 * neg_then_neg / neg_count, 2) if neg_count > 0 else 0,
            "max_consecutive_positive_5bps": max_consec_pos_5bps
        },
        "jupiter_comparison_notes": {
            "status": "Jupiter perps funding not directly accessible via public API without on-chain query",
            "expected_divergence": "Jupiter may have slightly higher rates due to less efficient funding mechanism",
            "recommendation": "Monitor Jupiter directly for divergence > 2x Binance rates as additional edge"
        }
    }

def main():
    print("Fetching extended Binance ETH funding rate history...")
    all_rates = fetch_all_funding_rates()
    print(f"Total rates fetched: {len(all_rates)}")
    
    print("Running comprehensive analysis...")
    analysis = analyze_comprehensive(all_rates)
    
    print("\n=== COMPREHENSIVE FUNDING RATE ANALYSIS ===")
    print(f"Period: {analysis['metadata']['start']} to {analysis['metadata']['end']} ({analysis['metadata']['days_span']} days)")
    print(f"Total periods: {analysis['metadata']['total_periods']}")
    print(f"\nAverage: {analysis['summary']['avg_rate_8h_pct']}% / 8h = {analysis['summary']['annualized_avg_pct']}% annualized")
    print(f"Max: {analysis['summary']['max_rate_pct']}%, Min: {analysis['summary']['min_rate_pct']}%")
    
    print(f"\n--- STRATEGY SCENARIOS ---")
    for name, s in analysis['strategy_scenarios'].items():
        print(f"{name}: {s['annualized_return_pct']}% annual | active {s['active_pct']}% | short {s['short_pct']}% long {s['long_pct']}%")
    
    print(f"\n--- MONTHLY BREAKDOWN ---")
    for month, stats in analysis['monthly_breakdown'].items():
        print(f"{month}: avg={stats['avg_rate_8h_pct']}% ann={stats['annualized_pct']}% hi5={stats['above_5bps']} lo_neg3={stats['below_neg_3bps']}")
    
    # Save
    output_path = '/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/funding_rate_arb.json'
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2)
    print(f"\nSaved to {output_path}")

if __name__ == '__main__':
    main()
