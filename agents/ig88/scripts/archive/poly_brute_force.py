#!/usr/bin/env python3
"""
Polymarket Bruteforce Edge Finder
===================================
Find what makes money. Period.
"""
import json
import subprocess
import numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

OUTPUT = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
OUTPUT.mkdir(exist_ok=True)


def api_get(url, timeout=30):
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except:
        return None


def get_all_active():
    """Get every active market with prices."""
    markets = []
    cursor = None
    
    for _ in range(10):  # Max 10 pages
        if cursor:
            url = f"https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100&cursor={cursor}"
        else:
            url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"
        
        data = api_get(url)
        if not data:
            break
        
        for event in data:
            for m in event.get('markets', []):
                prices_str = m.get('outcomePrices', '[]')
                try:
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    prices = [float(p) for p in prices]
                except:
                    continue
                
                if len(prices) >= 2 and 0.01 < prices[0] < 0.99:
                    markets.append({
                        'slug': m.get('slug', ''),
                        'question': m.get('question', ''),
                        'yes_price': prices[0],
                        'no_price': prices[1],
                        'category': event.get('category', ''),
                        'volume': float(event.get('volume', 0)),
                        'liquidity': float(event.get('liquidity', 0)),
                        'end_date': m.get('endDate', ''),
                    })
        
        # Check for next page
        if data and len(data) == 100:
            cursor = api_get("https://gamma-api.polymarket.com/events?active=true&closed=false&limit=1&offset=99")
        else:
            break
    
    return markets


def test_market_making(markets):
    """Test: can we profit by providing liquidity at spread?"""
    print("\n=== MARKET MAKING EDGE ===")
    
    # Simulate: place bids at (yes_price - 0.01) and asks at (yes_price + 0.01)
    # Collect spread if filled
    
    profits = []
    for m in markets:
        spread = m['no_price'] - m['yes_price']
        if spread > 0.02:  # Minimum spread to capture
            # If we provide liquidity at mid-market
            mid = (m['yes_price'] + m['no_price']) / 2
            edge = spread / 2  # We capture half the spread
            
            # Volume-weighted estimate
            if m['volume'] > 1000:
                est_daily_profit = m['volume'] * 0.001 * edge  # 0.1% of volume at our price
                profits.append(est_daily_profit)
    
    avg_profit = np.mean(profits) if profits else 0
    total_est = sum(profits)
    print(f"Markets with spread > 2%: {len(profits)}")
    print(f"Est daily profit from MM: ${total_est:.2f}")
    return profits


def test_correlation_arb(markets):
    """Find correlated markets with mispricing."""
    print("\n=== CORRELATION ARB ===")
    
    # Group by keywords
    groups = defaultdict(list)
    keywords = ['gta', 'trump', 'bitcoin', 'ethereum', 'ceasefire', 'election', '2026', '2027']
    
    for m in markets:
        q = m['question'].lower()
        for kw in keywords:
            if kw in q:
                groups[kw].append(m)
    
    arb_opps = []
    
    for kw, group in groups.items():
        if len(group) < 2:
            continue
        
        # Find markets that should be correlated but have price divergence
        for i, m1 in enumerate(group):
            for m2 in group[i+1:]:
                # If both mention YES outcomes of related events
                price_diff = abs(m1['yes_price'] - m2['yes_price'])
                
                # Check if prices should be closer
                if price_diff > 0.15:  # 15% divergence
                    arb_opps.append({
                        'pair': [m1['question'][:40], m2['question'][:40]],
                        'prices': [m1['yes_price'], m2['yes_price']],
                        'diff': price_diff,
                        'keyword': kw,
                    })
    
    print(f"Potential correlation arbs found: {len(arb_opps)}")
    for opp in arb_opps[:10]:
        print(f"  [{opp['keyword']}] {opp['prices'][0]:.2f} vs {opp['prices'][1]:.2f} (diff: {opp['diff']:.2f})")
        print(f"    {opp['pair'][0]}")
        print(f"    {opp['pair'][1]}")
    
    return arb_opps


def test_momentum(markets):
    """Test price momentum signals."""
    print("\n=== MOMENTUM EDGE ===")
    
    # Fetch recent price history for high-volume markets
    high_vol = sorted(markets, key=lambda x: x['volume'], reverse=True)[:20]
    
    momentum_opps = []
    
    for m in high_vol:
        # Get price history from CLOB
        # For now, use spread as proxy for momentum
        spread = m['no_price'] - m['yes_price']
        
        # Extreme prices may revert
        if m['yes_price'] > 0.85 or m['yes_price'] < 0.15:
            momentum_opps.append({
                'question': m['question'][:50],
                'yes_price': m['yes_price'],
                'signal': 'REVERT_SHORT' if m['yes_price'] > 0.85 else 'REVERT_LONG',
                'volume': m['volume'],
            })
    
    print(f"Extreme price markets (potential reversals): {len(momentum_opps)}")
    for opp in momentum_opps[:10]:
        print(f"  {opp['signal']:12} | {opp['yes_price']:.2f} | vol=${opp['volume']:,.0f} | {opp['question']}...")
    
    return momentum_opps


def test_structural_edge(markets):
    """Find structural edges: fees, rebates, minimums."""
    print("\n=== STRUCTURAL EDGE ===")
    
    # Reward program: need $20 min size, <3.5% spread
    reward_qualified = [m for m in markets if m['volume'] > 5000 and (m['no_price'] - m['yes_price']) < 0.035]
    
    print(f"Markets qualified for rewards (vol>$5k, spread<3.5%): {len(reward_qualified)}")
    
    # Calculate potential rebate income
    # Assuming 0.1% daily rebate on qualifying positions
    total_liquidity = sum(m['liquidity'] for m in reward_qualified)
    est_daily_rebate = total_liquidity * 0.001  # 0.1% daily
    
    print(f"Total qualifying liquidity: ${total_liquidity:,.0f}")
    print(f"Est daily rebate income (if we provide all): ${est_daily_rebate:.2f}")
    
    # Find highest volume markets for focused MM
    top_vol = sorted(reward_qualified, key=lambda x: x['volume'], reverse=True)[:10]
    print("\nTop volume markets for focused MM:")
    for m in top_vol:
        print(f"  vol=${m['volume']:>10,.0f} | spread={m['no_price']-m['yes_price']:.2%} | {m['question'][:45]}...")
    
    return reward_qualified


def test_extreme_edges(markets):
    """Find markets with obvious mispricing."""
    print("\n=== EXTREME EDGE SCAN ===")
    
    extreme = []
    
    for m in markets:
        q = m['question'].lower()
        yes = m['yes_price']
        
        # Pattern: "Will X happen before Y?" where Y is known to be far away
        if 'before gta' in q:
            # GTA VI not coming until late 2026+
            # So "before GTA" means essentially "ever"
            if 'bitcoin' in q and '$1m' in q:
                if yes > 0.30:  # Market says >30% chance BTC hits $1m before GTA
                    extreme.append(('BUY_NO', m, 0.03, 'BTC $1m extremely unlikely in any timeframe'))
            
            if 'rihanna' in q and 'album' in q:
                if yes > 0.40:  # Market says >40% Rihanna drops album
                    extreme.append(('BUY_NO', m, 0.15, 'Rihanna album unlikely after 10yr gap'))
        
        # Pattern: Impeachment/removal - historically very rare
        if 'impeach' in q and 'trump' in q:
            if yes > 0.10:
                extreme.append(('BUY_NO', m, 0.05, 'Impeachment historically rare'))
        
        # Pattern: Long-shot科技突破
        if any(w in q for w in ['agi', 'artificial general intelligence']):
            if yes > 0.20:
                extreme.append(('BUY_NO', m, 0.05, 'AGI timeline aggressive'))
        
        # Pattern: Sports long-shots
        if 'championship' in q or 'win the' in q:
            if yes > 0.50:  # Favorite priced >50%
                extreme.append(('BUY_NO', m, 0.3, 'Championships have many contenders'))
    
    print(f"Extreme edge opportunities: {len(extreme)}")
    for direction, m, base, reason in extreme:
        edge = abs(m['yes_price'] - base)
        print(f"  {direction:8} | Edge: {edge:.1%} | Price: {m['yes_price']:.2%}")
        print(f"           | {m['question'][:55]}...")
        print(f"           | Reason: {reason}")
    
    return extreme


def run_all_tests():
    """Run all edge tests."""
    print("=" * 80)
    print("POLYMARKET BRUTE FORCE EDGE FINDER")
    print("=" * 80)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    
    print("\nFetching all active markets...")
    markets = get_all_active()
    print(f"Found {len(markets)} active markets")
    
    # Run all tests
    mm_results = test_market_making(markets)
    corr_results = test_correlation_arb(markets)
    momentum_results = test_momentum(markets)
    struct_results = test_structural_edge(markets)
    extreme_results = test_extreme_edges(markets)
    
    # Summary
    print("\n" + "=" * 80)
    print("EDGE SUMMARY")
    print("=" * 80)
    
    print(f"""
1. MARKET MAKING: {len(mm_results)} markets with spread > 2%
2. CORRELATION ARB: {len(corr_results)} mispriced pairs
3. MOMENTUM REVERSION: {len(momentum_results)} extreme price markets
4. STRUCTURAL (REWARDS): {len(struct_results)} reward-qualified markets
5. EXTREME MISPRICING: {len(extreme_results)} obvious edges
""")
    
    if extreme_results:
        print("TOP EXTREME EDGES:")
        for direction, m, base, reason in sorted(extreme_results, key=lambda x: abs(x[1]['yes_price'] - x[2]), reverse=True)[:5]:
            edge = abs(m['yes_price'] - base)
            print(f"  {direction} @ {m['yes_price']:.1%} -> {base:.0%} (edge: {edge:.1%})")
            print(f"    {m['question'][:60]}")
    
    # Save results
    results = {
        'time': datetime.now(timezone.utc).isoformat(),
        'markets_scanned': len(markets),
        'extreme_edges': [(d, m['question'], m['yes_price'], b) for d, m, b, r in extreme_results],
        'correlation_arbs': len(corr_results),
        'reward_markets': len(struct_results),
    }
    
    with open(OUTPUT / 'brute_force_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return extreme_results


if __name__ == '__main__':
    run_all_tests()
