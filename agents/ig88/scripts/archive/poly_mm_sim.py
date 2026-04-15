#!/usr/bin/env python3
"""
Polymarket Market Making Simulation
=====================================
Test if liquidity provision + rewards = profit.
"""
import json
import subprocess
import numpy as np
from pathlib import Path

OUTPUT = Path('/Users/nesbitt/dev/factory/agents/ig88/data')


def api_get(url):
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        return json.loads(result.stdout)
    except:
        return None


def get_clob_orderbook(token_id):
    """Get orderbook depth for a token."""
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    return api_get(url)


def simulate_mm_strategy(markets_with_tokens):
    """
    Simulate market making:
    - Place limit orders on both sides at spread
    - Collect rewards for qualifying positions
    - Track inventory risk
    """
    results = []
    
    for m in markets_with_tokens:
        yes_price = m['yes_price']
        spread = m.get('spread', 0.02)
        
        # Skip if spread too small
        if spread < 0.01:
            continue
        
        # MM parameters
        bid_price = yes_price - (spread / 2) * 0.8  # Slightly inside spread
        ask_price = yes_price + (spread / 2) * 0.8
        
        # Estimate fill rate based on volume
        daily_volume = m['volume'] / 30  # Approximate daily
        est_fills = daily_volume * 0.01  # Assume 1% of volume at our price
        
        # Per-fill PnL
        spread_capture = ask_price - bid_price
        
        # Rewards eligibility
        qualifies = m['volume'] > 5000 and spread < 0.035
        daily_reward_rate = 0.001 if qualifies else 0  # 0.1%/day
        
        # Inventory risk: if market moves against us
        # Assume 5% adverse move probability per day
        adverse_move_prob = 0.05
        adverse_move_loss = yes_price * 0.5  # Worst case 50% loss on position
        
        # Expected daily PnL per $1000 position
        spread_pnl = est_fills * spread_capture / yes_price * 1000
        reward_pnl = 1000 * daily_reward_rate
        expected_risk = adverse_move_prob * adverse_move_loss * 1000
        
        net_expected = spread_pnl + reward_pnl - expected_risk
        
        results.append({
            'question': m['question'][:50],
            'yes_price': yes_price,
            'spread': spread,
            'volume': m['volume'],
            'qualifies_rewards': qualifies,
            'spread_pnl': spread_pnl,
            'reward_pnl': reward_pnl,
            'risk': expected_risk,
            'net_expected': net_expected,
        })
    
    return results


def test_correlation_arb():
    """
    Test: Buy NO on correlated "before GTA VI" markets.
    They all resolve based on GTA VI release timing.
    """
    print("=" * 80)
    print("CORRELATION ARB: BEFORE GTA VI MARKETS")
    print("=" * 80)
    
    # Get all "before GTA VI" markets
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=500"
    events = api_get(url)
    
    gta_markets = []
    for event in events:
        title = event.get('title', '').lower()
        if 'gta' in title or 'before' in title:
            for m in event.get('markets', []):
                prices_str = m.get('outcomePrices', '[]')
                try:
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    prices = [float(p) for p in prices]
                except:
                    continue
                
                if len(prices) >= 2 and 0.01 < prices[0] < 0.99:
                    gta_markets.append({
                        'question': m.get('question', ''),
                        'yes_price': prices[0],
                        'no_price': prices[1],
                    })
    
    print(f"\nFound {len(gta_markets)} 'before GTA VI' markets")
    
    # The key insight: ALL these markets depend on when GTA VI releases
    # If GTA releases late 2026+, all these have until then
    # But markets price them as if they're independent
    
    # Strategy: Buy NO on markets where the event is unlikely
    # regardless of GTA timing
    print("\nHIGH PROBABILITY NO BETS:")
    
    strategy_bets = []
    
    for m in gta_markets:
        q = m['question'].lower()
        yes = m['yes_price']
        
        # Events that are clearly unlikely regardless of timeline
        if 'bitcoin' in q and '$1m' in q:
            if yes > 0.30:
                strategy_bets.append(('BTC $1m', m, 0.03, 'Need 12x move, extremely unlikely'))
        
        if 'rihanna' in q and 'album' in q:
            if yes > 0.40:
                strategy_bets.append(('Rihanna', m, 0.15, 'No album since 2016'))
        
        if 'jesus' in q or 'christ' in q:
            if yes > 0.20:
                strategy_bets.append(('Jesus', m, 0.01, '...'))
        
        if 'china' in q and 'taiwan' in q:
            if yes > 0.30:
                strategy_bets.append(('China-Taiwan', m, 0.05, 'Economic costs prohibitive'))
        
        if 'trump' in q and 'out' in q:
            if yes > 0.30:
                strategy_bets.append(('Trump out', m, 0.15, 'Constitutional term'))
    
    for name, m, base_rate, reason in strategy_bets:
        edge = m['yes_price'] - base_rate
        print(f"\n  BUY NO: {name}")
        print(f"    Market YES: {m['yes_price']:.1%}")
        print(f"    Base rate: {base_rate:.1%}")
        print(f"    Edge: {edge:.1%}")
        print(f"    Reason: {reason}")
    
    return strategy_bets


def test_structural_rebates():
    """Test the rewards program edge."""
    print("\n" + "=" * 80)
    print("STRUCTURAL EDGE: REWARDS PROGRAM")
    print("=" * 80)
    
    # Get reward-qualified markets
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=500"
    events = api_get(url)
    
    qualified = []
    
    for event in events:
        for m in event.get('markets', []):
            vol = float(event.get('volume', 0))
            prices_str = m.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                prices = [float(p) for p in prices]
            except:
                continue
            
            if len(prices) >= 2:
                spread = prices[1] - prices[0]
                
                # Rewards qualification: >$20 min size, <3.5% spread
                if vol > 5000 and abs(spread) < 0.035:
                    qualified.append({
                        'question': m.get('question', ''),
                        'yes_price': prices[0],
                        'spread': abs(spread),
                        'volume': vol,
                    })
    
    print(f"\nReward-qualified markets: {len(qualified)}")
    
    if qualified:
        total_vol = sum(m['volume'] for m in qualified)
        print(f"Total volume: ${total_vol:,.0f}")
        
        # If we provide liquidity to 1% of these markets
        # At 0.1% daily rebate, that's significant
        our_share = 0.01  # 1% market share
        est_daily_rebate = total_vol * our_share * 0.001
        
        print(f"\nIf we capture 1% market share:")
        print(f"  Est daily rebate: ${est_daily_rebate:.2f}")
        print(f"  Est monthly: ${est_daily_rebate * 30:.2f}")
        print(f"  Est annual: ${est_daily_rebate * 365:.0f}")
        
        print("\nTop markets to target:")
        for m in sorted(qualified, key=lambda x: -x['volume'])[:10]:
            print(f"  vol=${m['volume']:>10,.0f} | spread={m['spread']:.2%} | {m['question'][:45]}...")
    
    return qualified


def run_simulations():
    """Run all simulations."""
    print("=" * 80)
    print("POLYMARKET EDGE SIMULATIONS")
    print("=" * 80)
    
    # Test 1: Correlation arb
    corr_bets = test_correlation_arb()
    
    # Test 2: Rewards/structural
    reward_markets = test_structural_rebates()
    
    # Summary
    print("\n" + "=" * 80)
    print("SIMULATION RESULTS")
    print("=" * 80)
    
    print(f"""
STRATEGY 1: CORRELATED MARKET ARB (before GTA VI)
  - {len(corr_bets)} identifiable edges
  - Buy NO on unlikely events, they all win if GTA comes first
  - Risk: if GTA delayed further, timeline extends
  
STRATEGY 2: REWARDS PROGRAM MARKET MAKING
  - {len(reward_markets)} reward-qualified markets
  - 0.1%/day rebate on qualifying liquidity
  - Requires inventory management
  - Risk: adverse price movement
  
RECOMMENDATION:
  1. START with Strategy 1 (correlated arb)
     - Clear edges, defined risk
     - $50-100 per position
     
  2. ADD Strategy 2 (rewards MM) once paper trading proves
     - Requires more capital
     - Requires inventory management
     - Pure structural edge
""")


if __name__ == '__main__':
    run_simulations()
