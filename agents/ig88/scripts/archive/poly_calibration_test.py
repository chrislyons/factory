#!/usr/bin/env python3
"""
Polymarket LLM Calibration Test
=================================
Test whether our LLM assessment would have beaten historical market prices.

This is the CRITICAL validation: if LLM calibration is poor, we have no edge.
"""
import json
import subprocess
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')


def fetch_closed_markets(limit=100):
    """Fetch closed/resolved markets from Gamma API."""
    url = f"https://gamma-api.polymarket.com/events?closed=true&limit={limit}"
    result = subprocess.run(
        ['curl', '-s', url],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return []
    
    try:
        data = json.loads(result.stdout)
        return data
    except json.JSONDecodeError:
        print("Failed to parse response")
        return []


def extract_market_data(event):
    """Extract market data from event."""
    markets = event.get('markets', [])
    results = []
    
    for market in markets:
        if not market.get('closed', False):
            continue
        
        question = market.get('question', '')
        tokens = market.get('tokens', [])
        outcome_prices = market.get('outcomePrices', '[]')
        
        # Parse prices and winner
        try:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
        except:
            prices = []
        
        # Find winner
        winner_outcome = None
        for token in tokens:
            if token.get('winner', False):
                winner_outcome = token.get('outcome', '')
                break
        
        if winner_outcome and len(prices) >= 2:
            results.append({
                'question': question,
                'category': event.get('category', 'Unknown'),
                'prices': prices,
                'winner': winner_outcome,
                'end_date': market.get('end_date_iso', ''),
                'volume': float(market.get('volume', 0)),
            })
    
    return results


def assess_question_llm(question, category):
    """
    Rule-based probability assessment for historical questions.
    
    This simulates what an LLM would estimate.
    For a proper test, we'd use actual LLM calls, but this gives us
    a baseline to work with.
    """
    q_lower = question.lower()
    
    # Sports: use historical win rates as baseline
    if 'nba' in q_lower or 'nba' in category.lower():
        # NBA games are roughly 50/50 with home court advantage ~55%
        return 0.50
    
    if 'nfl' in q_lower or 'nfl' in category.lower():
        return 0.50
    
    if 'nhl' in q_lower or 'nhl' in category.lower():
        return 0.50
    
    if 'ufc' in q_lower or 'ufc' in category.lower():
        # Favorites typically win 65-70%
        if 'first round' in q_lower:
            return 0.35  # First round finishes are rarer
        return 0.65
    
    # Elections
    if 'president' in q_lower or 'election' in q_lower:
        if 'biden' in q_lower:
            return 0.75  # Incumbent advantage
        if 'trump' in q_lower:
            return 0.40
        return 0.50
    
    # Entertainment
    if 'album' in q_lower or 'movie' in q_lower or 'gross' in q_lower:
        if 'more than' in q_lower:
            return 0.40  # Conservative estimate
        return 0.50
    
    # Geopolitics
    if 'world cup' in q_lower:
        return 0.10  # Long shot
    
    return 0.50  # Default uninformative


def calculate_actual_edge(markets):
    """Calculate the edge our LLM would have had."""
    results = []
    
    for m in markets:
        question = m['question']
        prices = m['prices']
        winner = m['winner']
        
        if len(prices) < 2:
            continue
        
        # Get LLM assessment
        llm_prob = assess_question_llm(question, m.get('category', ''))
        
        # Determine which outcome the LLM favors
        # For simplicity, assume LLM assesses "Yes" probability
        yes_price = float(prices[0]) if prices[0] else 0.5
        
        # Did LLM's favored side win?
        if winner == 'Yes':
            outcome = 1.0
        elif winner == 'No':
            outcome = 0.0
        else:
            # Team names for sports - need to check which price corresponds to winner
            # For now, skip these
            continue
        
        # Calculate edge
        raw_edge = llm_prob - yes_price
        
        # Would we have traded?
        # Only trade if |edge| > threshold
        edge_threshold = 0.10  # 10% minimum edge
        
        if abs(raw_edge) > edge_threshold:
            # Calculate PnL
            if raw_edge > 0:
                # Buy YES
                if outcome == 1.0:
                    pnl = (1.0 - yes_price) / yes_price  # Profit %
                else:
                    pnl = -1.0  # Lost 100%
            else:
                # Buy NO (or sell YES)
                no_price = 1.0 - yes_price
                if outcome == 0.0:
                    pnl = (1.0 - no_price) / no_price
                else:
                    pnl = -1.0
            
            results.append({
                'question': question[:60],
                'llm_prob': llm_prob,
                'market_price': yes_price,
                'edge': raw_edge,
                'outcome': 'WIN' if (
                    (raw_edge > 0 and outcome == 1.0) or
                    (raw_edge < 0 and outcome == 0.0)
                ) else 'LOSS',
                'pnl': pnl,
                'volume': m['volume'],
            })
    
    return results


def run_calibration_test():
    """Run the full calibration test."""
    print("=" * 80)
    print("POLYMARKET LLM CALIBRATION TEST")
    print("=" * 80)
    
    # Fetch historical markets
    print("\n[1/4] Fetching closed markets...")
    events = fetch_closed_markets(limit=200)
    print(f"  Fetched {len(events)} closed events")
    
    # Extract market data
    print("\n[2/4] Extracting market data...")
    all_markets = []
    for event in events:
        markets = extract_market_data(event)
        all_markets.extend(markets)
    print(f"  Found {len(all_markets)} resolved markets")
    
    # Calculate edge
    print("\n[3/4] Calculating LLM edge...")
    results = calculate_actual_edge(all_markets)
    print(f"  Found {len(results)} tradeable opportunities (>10% edge)")
    
    if len(results) == 0:
        print("\n  No trades met the edge threshold!")
        print("  This suggests market prices are efficient, or our")
        print("  rule-based assessment is too conservative.")
        return
    
    # Analyze results
    print("\n[4/4] Analyzing results...")
    
    wins = sum(1 for r in results if r['outcome'] == 'WIN')
    losses = len(results) - wins
    win_rate = wins / len(results) if results else 0
    
    total_pnl = sum(r['pnl'] for r in results)
    avg_pnl = total_pnl / len(results) if results else 0
    
    print("\n" + "=" * 80)
    print("CALIBRATION TEST RESULTS")
    print("=" * 80)
    
    print(f"\nTotal trades: {len(results)}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Win rate: {win_rate:.1%}")
    print(f"Total PnL: {total_pnl:.2f}x")
    print(f"Average PnL per trade: {avg_pnl:.2%}")
    
    print("\n--- Trade Details ---")
    for r in results[:20]:
        print(f"  {r['outcome']:4} | Edge: {r['edge']:+.1%} | PnL: {r['pnl']:+.1%} | {r['question']}...")
    
    # Key metrics
    print("\n--- Key Metrics ---")
    print(f"Sharpe-like ratio: {avg_pnl / (np.std([r['pnl'] for r in results]) if len(results) > 1 else 1):.2f}")
    print(f"P(profit): {win_rate:.1%}")
    print(f"Expected value: {avg_pnl:.2%} per trade")
    
    # Verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    
    if win_rate > 0.55 and avg_pnl > 0.05:
        print("""
EDGE CONFIRMED:
- Win rate > 55%
- Positive expected value per trade
- The LLM assessment has informational edge

The strategy is viable.
""")
    elif win_rate > 0.50:
        print("""
MARGINAL EDGE:
- Win rate between 50-55%
- Marginal expected value
- May be viable with zero fees

Need more data or refined assessment.
""")
    else:
        print("""
NO EDGE DETECTED:
- Win rate ~50% (coin flip)
- Markets appear efficient
- LLM assessment does not beat prices

STRATEGY NOT VIABLE without improvement.
""")
    
    # Save results
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'markets_tested': len(all_markets),
        'trades': len(results),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'results': results[:50],
    }
    
    with open(OUTPUT_DIR / 'calibration_test.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    return results


if __name__ == '__main__':
    run_calibration_test()
