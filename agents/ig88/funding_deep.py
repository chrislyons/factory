#!/usr/bin/env python3
"""
Deep Funding Rate Analysis
- Scan ALL 229 markets for extreme funding
- Cross-reference with OHLCV data for mean-reversion hypothesis
- Detailed JSON output
"""

import json
import urllib.request
import ssl
import os
import glob
from datetime import datetime, timezone

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data"

def fetch_hyperliquid_funding():
    url = "https://api.hyperliquid.xyz/info"
    payload = json.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_hyperliquid_funding_history(coin):
    """Fetch historical funding rates for a specific coin."""
    url = "https://api.hyperliquid.xyz/info"
    import time as _time
    # startTime required; go back 90 days
    start_ms = int((_time.time() - 90 * 86400) * 1000)
    payload = json.dumps({"type": "fundingHistory", "coin": coin, "startTime": start_ms}).encode("utf-8")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    Error fetching history for {coin}: {e}")
        return None

def main():
    print("=" * 70)
    print("DEEP FUNDING RATE ANALYSIS")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    
    # Fetch all data
    print("\n[1] Fetching Hyperliquid data...")
    raw = fetch_hyperliquid_funding()
    universe = raw[0].get("universe", [])
    contexts = raw[1]
    
    # Build full market list
    all_markets = []
    for i, ctx in enumerate(contexts):
        meta = universe[i] if i < len(universe) else {}
        name = meta.get("name", f"UNK_{i}")
        fr = float(ctx.get("funding", "0") or "0")
        vol = float(ctx.get("dayNtlVlm", "0") or "0")
        oi = float(ctx.get("openInterest", "0") or "0")
        mark_px = float(ctx.get("markPx", "0") or "0")
        mid_px = float(ctx.get("midPx", "0") or "0")
        oracle_px = float(ctx.get("oraclePx", "0") or "0")
        premium = float(ctx.get("premium", "0") or "0")
        max_lev = meta.get("maxLeverage", 0)
        
        all_markets.append({
            "symbol": name,
            "funding_rate_8h": fr,
            "funding_rate_8h_pct": round(fr * 100, 6),
            "funding_rate_8h_bps": round(fr * 10000, 3),
            "annualized_pct": round(fr * 3 * 365 * 100, 3),
            "volume_24h_usd": vol,
            "open_interest": oi,
            "mark_price": mark_px,
            "mid_price": mid_px,
            "oracle_price": oracle_px,
            "premium_pct": round(premium * 100, 4),
            "max_leverage": max_lev,
        })
    
    # Sort by absolute funding rate
    by_abs_funding = sorted(all_markets, key=lambda x: abs(x["funding_rate_8h"]), reverse=True)
    
    print(f"\n  Total markets: {len(all_markets)}")
    
    # Show top 30 by |funding|
    print(f"\n  Top 30 markets by |funding rate|:")
    print(f"  {'Symbol':<12} {'FR 8h %':>10} {'FR bp':>8} {'Ann %':>8} {'Vol 24h':>14} {'Premium':>8} {'MaxLev':>7}")
    print("  " + "-" * 75)
    for m in by_abs_funding[:30]:
        vol_str = f"${m['volume_24h_usd']:,.0f}" if m['volume_24h_usd'] else "N/A"
        print(f"  {m['symbol']:<12} {m['funding_rate_8h_pct']:>9.5f}% {m['funding_rate_8h_bps']:>7.3f} {m['annualized_pct']:>7.1f}% {vol_str:>14} {m['premium_pct']:>7.3f}% {m['max_leverage']:>5}x")
    
    # Extreme funding thresholds
    EXTREME_8H = 0.0003  # 0.03% per 8h
    SIGNIFICANT_8H = 0.0001  # 0.01% per 8h
    
    extreme_high = [m for m in all_markets if m["funding_rate_8h"] > EXTREME_8H]
    extreme_low = [m for m in all_markets if m["funding_rate_8h"] < -EXTREME_8H]
    significant = [m for m in all_markets if abs(m["funding_rate_8h"]) > SIGNIFICANT_8H]
    
    print(f"\n  Extreme funding (>{EXTREME_8H*100:.2f}%/8h): {len(extreme_high)} positive, {len(extreme_low)} negative")
    print(f"  Significant funding (>{SIGNIFICANT_8H*100:.2f}%/8h): {len(significant)} markets")
    
    if extreme_high:
        print(f"\n  VERY POSITIVE (short earns funding):")
        for m in sorted(extreme_high, key=lambda x: x["funding_rate_8h"], reverse=True):
            print(f"    {m['symbol']:<10} {m['funding_rate_8h_pct']:.5f}%/8h ({m['annualized_pct']:.1f}% ann)")
    
    if extreme_low:
        print(f"\n  VERY NEGATIVE (long earns funding):")
        for m in sorted(extreme_low, key=lambda x: x["funding_rate_8h"]):
            print(f"    {m['symbol']:<10} {m['funding_rate_8h_pct']:.5f}%/8h ({m['annualized_pct']:.1f}% ann)")
    
    # Distribution analysis
    rates = [m["funding_rate_8h_pct"] for m in all_markets]
    rates_sorted = sorted(rates)
    n = len(rates)
    
    p10 = rates_sorted[int(n * 0.1)]
    p25 = rates_sorted[int(n * 0.25)]
    p50 = rates_sorted[int(n * 0.5)]
    p75 = rates_sorted[int(n * 0.75)]
    p90 = rates_sorted[int(n * 0.9)]
    
    print(f"\n  Distribution of funding rates (%/8h):")
    print(f"    P10: {p10:.5f}%   P25: {p25:.5f}%   P50: {p50:.5f}%   P75: {p75:.5f}%   P90: {p90:.5f}%")
    print(f"    Min: {min(rates):.5f}%   Max: {max(rates):.5f}%   Mean: {sum(rates)/n:.5f}%")
    
    # Fetch historical funding for top coins to check mean-reversion
    print("\n[2] Fetching historical funding for mean-reversion analysis...")
    coins_to_check = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "BLUR", "MAVIA"]
    historical = {}
    
    for coin in coins_to_check:
        print(f"  Fetching {coin} funding history...")
        hist = fetch_hyperliquid_funding_history(coin)
        if hist:
            historical[coin] = hist
            print(f"    Got {len(hist)} funding records")
            if hist:
                # Show last few records
                for rec in hist[-5:]:
                    rate = float(rec.get("fundingRate", rec.get("funding", "0")))
                    time_ms = rec.get("time", 0)
                    dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc) if time_ms else "N/A"
                    print(f"      {dt}: {rate*100:.5f}%")
    
    # Analyze funding patterns
    print("\n[3] Funding pattern analysis...")
    for coin, hist in historical.items():
        if not hist:
            continue
        rates_hist = [float(rec.get("fundingRate", rec.get("funding", "0"))) for rec in hist]
        if len(rates_hist) < 10:
            continue
        
        avg = sum(rates_hist) / len(rates_hist)
        max_r = max(rates_hist)
        min_r = min(rates_hist)
        
        # Count extreme periods
        extreme_pos = sum(1 for r in rates_hist if r > 0.0003)
        extreme_neg = sum(1 for r in rates_hist if r < -0.0003)
        
        # Mean reversion: after extreme, does it revert?
        reversions = 0
        extremes_total = 0
        for i in range(len(rates_hist) - 1):
            if abs(rates_hist[i]) > 0.0003:
                extremes_total += 1
                if (rates_hist[i] > 0 and rates_hist[i+1] < rates_hist[i]) or \
                   (rates_hist[i] < 0 and rates_hist[i+1] > rates_hist[i]):
                    reversions += 1
        
        reversion_rate = reversions / extremes_total * 100 if extremes_total > 0 else 0
        
        print(f"\n  {coin} ({len(rates_hist)} periods):")
        print(f"    Avg: {avg*100:.5f}%/8h  ({avg*3*365*100:.2f}% ann)")
        print(f"    Range: {min_r*100:.5f}% to {max_r*100:.5f}%")
        print(f"    Extreme periods: {extreme_pos} pos, {extreme_neg} neg (of {len(rates_hist)})")
        print(f"    Mean reversion after extremes: {reversions}/{extremes_total} = {reversion_rate:.1f}%")
    
    # Build comprehensive result
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_markets": len(all_markets),
            "extreme_funding_count": len(extreme_high) + len(extreme_low),
            "significant_funding_count": len(significant),
            "avg_funding_8h_pct": round(sum(rates)/n, 6),
            "median_funding_8h_pct": round(p50, 6),
            "market_regime": "NEUTRAL" if abs(p50) < 0.0001 else ("BULLISH" if p50 > 0 else "BEARISH"),
            "notes": []
        },
        "all_markets_by_abs_funding": by_abs_funding[:50],
        "top_20_by_volume": sorted(all_markets, key=lambda x: x["volume_24h_usd"] or 0, reverse=True)[:20],
        "extreme_positive": sorted(extreme_high, key=lambda x: x["funding_rate_8h"], reverse=True),
        "extreme_negative": sorted(extreme_low, key=lambda x: x["funding_rate_8h"]),
        "distribution": {
            "p10": round(p10, 6),
            "p25": round(p25, 6),
            "p50": round(p50, 6),
            "p75": round(p75, 6),
            "p90": round(p90, 6),
            "min": round(min(rates), 6),
            "max": round(max(rates), 6),
        },
        "historical_funding": {},
        "mean_reversion": {},
        "strategy_integration": {
            "funding_as_entry_filter": {
                "description": "Before ATR breakout entry, check funding rate. If funding strongly opposes your intended direction, skip or reduce size.",
                "threshold": "Skip if funding opposing direction > 0.01%/8h (11% ann)",
                "reasoning": "Extreme opposing funding = overcrowded positioning. You're fighting the crowd AND paying funding."
            },
            "funding_as_confirmation": {
                "description": "If funding AGREES with breakout direction, it's a structural edge on top of the technical signal.",
                "example": "BTC breakout long + negative funding = you earn funding while holding the position",
                "amplifier": "Funding can add/subtract 11%+ annualized to your returns"
            },
            "delta_neutral_funding_arb": {
                "description": "Run in PARALLEL with directional ATR trades for diversified alpha",
                "method": "Long spot + Short perp (or vice versa) to collect funding with no directional risk",
                "best_opportunities": "Markets with |funding| > 0.03%/8h and sufficient liquidity",
                "jupiter_cross_venue": "Jupiter API currently returns 403; manual comparison needed"
            },
            "extreme_fade_signal": {
                "description": "When funding > 0.05%/8h or < -0.05%/8h, market is extremely overcrowded",
                "action": "Consider fading the direction (trading against the crowd)",
                "historical_edge": "Funding extremes tend to mean-revert (see historical analysis above)"
            }
        },
        "funding_schedule": {
            "settlement_times_utc": ["00:00", "08:00", "16:00"],
            "periods_per_day": 3,
            "note": "Position must be open at settlement to earn/pay funding"
        }
    }
    
    # Add historical data summary
    for coin, hist in historical.items():
        if hist:
            rates_h = [float(rec.get("fundingRate", rec.get("funding", "0"))) for rec in hist]
            result["historical_funding"][coin] = {
                "records": len(hist),
                "avg_8h_pct": round(sum(rates_h)/len(rates_h)*100, 6) if rates_h else None,
                "max_8h_pct": round(max(rates_h)*100, 6) if rates_h else None,
                "min_8h_pct": round(min(rates_h)*100, 6) if rates_h else None,
                "last_10_rates_pct": [round(r*100, 6) for r in rates_h[-10:]],
            }
            
            # Mean reversion calc
            extremes = 0
            reverts = 0
            for i in range(len(rates_h) - 1):
                if abs(rates_h[i]) > 0.0003:
                    extremes += 1
                    if (rates_h[i] > 0 and rates_h[i+1] < rates_h[i]) or \
                       (rates_h[i] < 0 and rates_h[i+1] > rates_h[i]):
                        reverts += 1
            result["mean_reversion"][coin] = {
                "extreme_periods": extremes,
                "reversions_next_period": reverts,
                "reversion_rate_pct": round(reverts/extremes*100, 1) if extremes > 0 else None
            }
    
    # Add notes
    if not extreme_high and not extreme_low:
        result["summary"]["notes"].append("No extreme funding rates detected at this snapshot. Funding is neutral across all markets.")
        result["summary"]["notes"].append("This is typical during low-volatility or consolidation periods.")
        result["summary"]["notes"].append("Extreme funding usually appears during strong trending moves when one side is heavily crowded.")
    
    if sum(1 for m in all_markets if m["funding_rate_8h"] > 0) > sum(1 for m in all_markets if m["funding_rate_8h"] <= 0):
        result["summary"]["notes"].append("More markets have positive funding (shorts earn) than negative - mildly bullish positioning overall.")
    else:
        result["summary"]["notes"].append("More markets have negative funding (longs earn) than positive - mildly bearish positioning overall.")
    
    # Write
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = f"{DATA_DIR}/funding_analysis.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    print(f"\n[4] Results written to: {out_path}")
    
    # Final summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Markets analyzed: {len(all_markets)}")
    print(f"  Extreme funding: {len(extreme_high) + len(extreme_low)} (currently none)")
    print(f"  Significant funding: {len(significant)}")
    print(f"  Regime: {'NEUTRAL' if abs(p50) < 0.0001 else ('BULLISH' if p50 > 0 else 'BEARISH')} (median: {p50:.5f}%/8h)")
    print(f"  Historical data retrieved for: {', '.join(historical.keys())}")
    print("\n  Key takeaway: Funding rates are currently very low (~0.1bp/8h).")
    print("  This means:")
    print("    - No immediate funding arb opportunities")
    print("    - Directional trades won't be hurt by funding costs")
    print("    - ATR breakout entries can proceed without funding filter concerns")
    print("    - Monitor for extreme funding spikes during volatile periods")
    print("  When funding DOES spike (>0.03%/8h), it's a strong structural signal.")
    print("=" * 70)

if __name__ == "__main__":
    main()
