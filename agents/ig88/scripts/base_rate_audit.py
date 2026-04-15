#!/usr/bin/env python3
"""
BASE RATE AUDIT Strategy for Polymarket
Compare current market prices to historical base rates for similar event types.
If the market price significantly diverges from the base rate, trade on the base rate.
"""

import urllib.request
import json
import math
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import os

# ============================================================
# STEP 1: FETCH ACTIVE POLYMARKET MARKETS
# ============================================================

def fetch_active_markets() -> List[Dict]:
    """Fetch all active Polymarket markets via Gamma API."""
    url = 'https://gamma-api.polymarket.com/events?limit=200&active=true&closed=false'
    
    print("[1/7] Fetching active Polymarket markets...")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            print(f"      Fetched {len(data)} events from Gamma API")
            return data
    except Exception as e:
        print(f"      Error fetching markets: {e}")
        return []

def parse_json_field(field) -> list:
    """Parse a JSON string field safely."""
    if field is None:
        return []
    if isinstance(field, list):
        return field
    if isinstance(field, str):
        try:
            return json.loads(field)
        except:
            return []
    return []

# ============================================================
# STEP 2: CATEGORIZE MARKETS BY TYPE
# ============================================================

def categorize_market(title: str, description: str, debug: bool = False) -> str:
    """Categorize market by type based on title/description."""
    text = f"{title} {description}".lower()
    
    if debug:
        print(f"DEBUG categorize: '{title[:60]}' -> checking categories...")
    
    # Price targets (crypto/stock reaching X price) - use word boundaries
    import re
    price_patterns = [r'\bprice\b', r'\breach\b', r'\babove\b', r'\bbelow\b', 
                      r'\bath\b', r'\ball-time high\b', r'\bstrike\b', r'\btarget price\b']
    matched_pat = None
    for pat in price_patterns:
        if re.search(pat, text):
            matched_pat = pat
            break
    if matched_pat:
        if debug:
            print(f"DEBUG: matched price_pattern '{matched_pat}' in '{text[:60]}', returning price_target")
        return 'price_target'
    
    # Check for specific crypto/stock tickers with price mentions (word boundary check)
    import re
    ticker_patterns = [r'\bbtc\b', r'\bbitcoin\b', r'\beth\b', r'\bethereum\b', 
                       r'\bsol\b', r'\bsolana\b', r'\bxrp\b', r'\bdoge\b']
    if any(re.search(p, text) for p in ticker_patterns):
        if any(p in text for p in ['$', 'price', 'k', '000']):
            if debug:
                print(f"DEBUG: matched ticker+price, returning price_target")
            return 'price_target'
    
    # Date ranges (when will X happen) - use word boundaries
    date_patterns = [r'\bwhen\b', r'\bdate\b', r'\bby when\b', r'\bbefore\b', 
                     r'\bquarter\b', r'\bmonth\b', r'\bq1\b', r'\bq2\b', r'\bq3\b', r'\bq4\b']
    for pat in date_patterns:
        if re.search(pat, text) and ('?' in title):
            if debug:
                print(f"DEBUG: matched date_pattern '{pat}', returning date_range")
            return 'date_range'
    
    # Numerical ranges (what will X be)
    numerical_keywords = ['how many', 'how much', 'number of', 'count', 'total',
                          'percent', 'rate', 'level', 'amount', 'gdp', 'inflation']
    if any(kw in text for kw in numerical_keywords):
        return 'numerical_range'
    
    # Default to yes/no (most common)
    if debug:
        print(f"DEBUG categorize result: yes_no (text was: '{text[:50]}')")
    return 'yes_no'

def extract_market_data_from_event(event: Dict) -> List[Dict]:
    """Extract all market data from an event (handles multi-market events)."""
    markets_list = event.get('markets', [])
    extracted = []
    
    for market in markets_list:
        if not market.get('active') or market.get('closed'):
            continue
            
        outcomes = parse_json_field(market.get('outcomes'))
        outcome_prices_str = market.get('outcomePrices')
        outcome_prices = parse_json_field(outcome_prices_str)
        
        if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
            prices = {}
            for i, outcome in enumerate(outcomes):
                try:
                    prices[outcome] = float(outcome_prices[i])
                except (ValueError, IndexError):
                    pass
            
            if prices:
                extracted.append({
                    'question': market.get('question', ''),
                    'outcomes': outcomes,
                    'prices': prices,
                    'volume': float(market.get('volumeNum', 0) or market.get('volume', 0) or 0),
                    'end_date': market.get('endDateIso') or market.get('endDate'),
                    'description': market.get('description', ''),
                })
    
    return extracted

# ============================================================
# STEP 3: ASSIGN HISTORICAL BASE RATES
# ============================================================

def estimate_price_target_base_rate(title: str, days: Optional[int]) -> float:
    """Estimate base rate for price target markets."""
    title_lower = title.lower()
    
    # Extract target price from title
    price_matches = re.findall(r'\$?([\d,]+(?:\.\d+)?)\s*[kK]?', title)
    
    if days is None:
        days = 180
    
    # BTC price targets
    if any(c in title_lower for c in ['btc', 'bitcoin']):
        target_pct = None
        for match in price_matches:
            try:
                val = float(match.replace(',', ''))
                if 'k' in title_lower[title_lower.find(match):title_lower.find(match)+len(match)+3]:
                    val *= 1000
                if val > 50000:  # Likely a BTC price target
                    current_btc = 103000  # Approximate current BTC
                    target_pct = (val - current_btc) / current_btc
            except:
                pass
        
        if target_pct is not None:
            if target_pct > 0.5:
                return 0.10 if days < 90 else (0.20 if days < 180 else (0.35 if days < 365 else 0.50))
            elif target_pct > 0.2:
                return 0.25 if days < 90 else (0.40 if days < 180 else 0.55)
            elif target_pct > 0:
                return 0.45 if days < 90 else (0.55 if days < 180 else 0.60)
            else:
                return 0.35  # Downside target
    
    # ETH price targets
    if any(c in title_lower for c in ['eth', 'ethereum']):
        target_pct = None
        for match in price_matches:
            try:
                val = float(match.replace(',', ''))
                if val > 1000:
                    current_eth = 3500
                    target_pct = (val - current_eth) / current_eth
            except:
                pass
        if target_pct is not None:
            if target_pct > 0.5:
                return 0.15 if days < 180 else 0.35
            elif target_pct > 0.2:
                return 0.25 if days < 180 else 0.45
            else:
                return 0.40 if days < 180 else 0.55
    
    # Default
    return 0.35

def estimate_yes_no_base_rate(title: str, description: str, days: Optional[int], market_price: float = 0.5) -> float:
    """Estimate base rate for yes/no event markets."""
    title_lower = title.lower()
    desc_lower = description.lower()
    text = f"{title_lower} {desc_lower}"
    
    # Debug for specific markets
    if 'arsenal' in text and 'top 4' in text:
        print(f"DEBUG Arsenal: text='{text[:80]}', market_price={market_price}")
        print(f"  'top 4' in text: {'top 4' in text}")
        print(f"  'arsenal' in text: {'arsenal' in text}")
    
    # Presidential/political elections
    if any(kw in text for kw in ['president', 'election', 'win', 'elected', 'nominee']):
        if 'trump' in text and ('2028' in text or 'republican' in text):
            return 0.65
        if 'democrat' in text and '2028' in text:
            return 0.45
        return 0.50
    
    # Bankruptcy of established companies
    if any(kw in text for kw in ['bankrupt', 'default', 'delist']):
        major_companies = ['apple', 'google', 'amazon', 'microsoft', 'tesla', 'meta', 
                          'netflix', 'nvidia', 'coinbase', 'binance', 'jp morgan', 'goldman']
        if any(co in text for co in major_companies):
            return 0.02
        return 0.05
    
    # ETF approvals
    if 'etf' in text and ('approv' in text or 'launch' in text or 'list' in text):
        if 'solana' in text or 'sol ' in text:
            return 0.75
        if 'ethereum' in text or 'eth ' in text:
            return 0.85
        if 'bitcoin' in text or 'btc' in text:
            return 0.90
        if 'xrp' in text or 'ripple' in text:
            return 0.60
        return 0.50
    
    # Fed rate decisions
    if 'fed' in text and ('rate' in text or 'cut' in text or 'hike' in text):
        if 'cut' in text:
            return 0.65
        if 'hike' in text:
            return 0.25
        return 0.50
    
    # Recession/economic
    if any(kw in text for kw in ['recession', 'gdp negative']):
        return 0.30
    
    # War/conflict
    if any(kw in text for kw in ['war', 'conflict', 'attack', 'invasion', 'peace', 'ceasefire']):
        if 'ceasefire' in text or 'peace' in text:
            return 0.35
        return 0.25
    
    # Regulatory/legal
    if any(kw in text for kw in ['ban', 'regulation', 'sec', 'fine', 'lawsuit', 'indict']):
        return 0.35
    
    # Technology/AI milestones
    if any(kw in text for kw in ['agi', 'ai', 'model', 'gpt', 'claude', 'gemini']):
        if 'agi' in text:
            return 0.15
        return 0.45
    
    # Sports: Top 4/Champions League qualification
    if 'top 4' in text or 'top four' in text or 'champions league' in text:
        # Elite teams historically finish top 4 ~70-85% of the time
        elite_teams = ['arsenal', 'manchester city', 'liverpool', 'real madrid', 'barcelona',
                      'bayern', 'psg', 'juventus', 'inter', 'ac milan', 'napoli', 'atletico']
        good_teams = ['tottenham', 'chelsea', 'manchester united', 'newcastle', 'aston villa',
                     'dortmund', 'rb leipzig', 'roma', 'lazio', 'atletico', 'real sociedad']
        for team in elite_teams:
            if team in text:
                # print(f"DEBUG: Found elite team '{team}' in: {text[:50]}")
                return 0.80  # Elite teams: 80% base rate
        for team in good_teams:
            if team in text:
                return 0.50  # Good teams: 50%
        return 0.25  # Others: 25%
    
    # Sports: Relegation
    if 'relegat' in text:
        # Bottom teams historically get relegated ~30-50% depending on position
        weak_teams = ['wolves', 'burnley', 'sheffield', 'luton', 'norwich', 'watford',
                     'southampton', 'nottingham forest', 'everton', 'bournemouth', 'fulham',
                     'ipswich', 'leicester']
        if any(team in text for team in weak_teams):
            return 0.35  # Weak teams: 35% relegation risk
        return 0.15  # Others: 15%
    
    # Sports: Championship winner (single team in multi-team market)
    if any(kw in text for kw in ['champion', 'win the', 'super bowl', 'world series', 
                                  'stanley cup', 'premier league winner', 'la liga winner',
                                  'serie a winner', 'bundesliga winner']):
        # Top favorites historically win ~15-25%
        top_favorites = ['manchester city', 'liverpool', 'arsenal', 'real madrid', 'barcelona',
                        'bayern', 'psg', 'juventus', 'kansas city chiefs', 'golden state']
        if any(team in text for team in top_favorites):
            return 0.25
        return 0.08  # Others: 8%
    
    # Sports: NFL Draft
    if 'draft' in text and ('first pick' in text or '#1' in text or 'first overall' in text):
        # QB favorites historically go #1 ~60% of the time
        return 0.60
    
    # Sports: Make playoffs
    if 'playoff' in text or 'postseason' in text:
        return 0.40
    
    # Default - use market price as weak prior if no specific knowledge
    # This prevents huge divergences on markets we don't understand
    return market_price

def estimate_date_range_base_rate(title: str, description: str) -> float:
    """Estimate base rate for date range markets."""
    # Date range markets are typically multi-outcome with different date bins
    # Each bin should have a probability summing to ~1.0
    # Default: equal probability
    return 0.50

# ============================================================
# MAIN ANALYSIS
# ============================================================

def assign_base_rate_for_outcome(title: str, description: str, outcome: str, 
                                  market_price: float, days: Optional[int],
                                  category: str, num_outcomes: int) -> Tuple[float, str]:
    """Assign historical base rate to a specific outcome."""
    
    # For multi-outcome markets, each outcome should have proportional probability
    if num_outcomes > 2:
        # Equal probability baseline for multi-outcome
        equal_prob = 1.0 / num_outcomes
        
        # Adjust based on outcome characteristics
        if category == 'yes_no':
            if outcome.lower() in ['yes', 'true']:
                base_rate = estimate_yes_no_base_rate(title, description, days, market_price)
            else:
                base_rate = 1.0 - estimate_yes_no_base_rate(title, description, days, 1 - market_price)
        else:
            base_rate = equal_prob
        
        reasoning = f"Multi-outcome ({num_outcomes}), category-specific adjustment"
        return base_rate, reasoning
    
    # Binary (2 outcome) markets
    if category == 'price_target':
        if outcome.lower() in ['yes', 'true', 'above', 'over']:
            base_rate = estimate_price_target_base_rate(title, days)
        else:
            base_rate = 1.0 - estimate_price_target_base_rate(title, days)
        reasoning = f"Price target, historical volatility-adjusted, {days or '?'} days"
    elif category == 'yes_no':
        if outcome.lower() in ['yes', 'true']:
            base_rate = estimate_yes_no_base_rate(title, description, days, market_price)
        else:
            base_rate = 1.0 - estimate_yes_no_base_rate(title, description, days, 1 - market_price)
        reasoning = "Yes/No event, category-specific historical base rate"
    elif category == 'date_range':
        base_rate = estimate_date_range_base_rate(title, description)
        reasoning = "Date range market"
    else:
        base_rate = 0.50
        reasoning = "Default 50%"
    
    return base_rate, reasoning

def identify_mispricings_for_market(event_title: str, event_slug: str, category: str,
                                     liquidity: float, market_data: Dict) -> List[Dict]:
    """Identify mispricings for all outcomes in a market."""
    mispricings = []
    
    title = market_data.get('question', event_title)
    description = market_data.get('description', '')
    
    # Recategorize based on market question, not event title
    debug = 'arsenal' in title.lower() or 'wolves' in title.lower()
    market_category = categorize_market(title, description, debug=debug)
    
    if debug:
        print(f"DEBUG market_category for '{title[:50]}': {market_category}")
    
    prices = market_data.get('prices', {})
    days = None
    
    end_date = market_data.get('end_date')
    if end_date:
        try:
            if 'T' in str(end_date):
                end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                end = datetime.strptime(end_date, '%Y-%m-%d')
            now = datetime.now(end.tzinfo) if end.tzinfo else datetime.now()
            days = max(0, (end - now).days)
        except:
            pass
    
    num_outcomes = len(prices)
    
    for outcome, price in prices.items():
        # Skip resolved markets (price = 0 or 1 exactly)
        if price <= 0.001 or price >= 0.999:
            continue
        
        base_rate, reasoning = assign_base_rate_for_outcome(
            title, description, outcome, price, days, market_category, num_outcomes
        )
        
        divergence = abs(price - base_rate)
        threshold = 0.10  # 10% minimum edge
        
        if divergence > threshold:
            if base_rate > price:
                direction = 'BUY'
                edge = base_rate - price
            else:
                direction = 'SELL'
                edge = price - base_rate
            
            # Calculate EV
            if direction == 'BUY':
                potential_profit = 1 - price
                cost = price
                ev = (base_rate * potential_profit) - ((1 - base_rate) * cost)
                roi = ev / price if price > 0 else 0
                b = (1 / price) - 1 if price > 0 else 0
                kelly = max(0, (base_rate * b - (1 - base_rate)) / b) if b > 0 else 0
            else:
                potential_profit = price
                cost = 1 - price
                ev = ((1 - base_rate) * potential_profit) - (base_rate * cost)
                roi = ev / (1 - price) if price < 1 else 0
                b = price / (1 - price) if price < 1 else 0
                kelly = max(0, ((1 - base_rate) * b - base_rate) / b) if b > 0 else 0
            
            mispricings.append({
                'event_title': event_title,
                'title': title,
                'slug': event_slug,
                'category': market_category,
                'outcome': outcome,
                'direction': direction,
                'market_price': round(price, 4),
                'base_rate': round(base_rate, 4),
                'divergence': round(divergence, 4),
                'edge': round(edge, 4),
                'expected_value': round(ev, 4),
                'roi_percent': round(roi * 100, 2),
                'kelly_fraction': round(kelly, 4),
                'half_kelly_fraction': round(kelly / 2, 4),
                'volume': market_data.get('volume', 0),
                'liquidity': liquidity,
                'days_until_end': days,
                'reasoning': reasoning,
            })
    
    return mispricings

def run_base_rate_audit():
    """Run complete base rate audit analysis."""
    print("=" * 70)
    print("BASE RATE AUDIT - Polymarket Strategy")
    print("=" * 70)
    print()
    
    # Step 1: Fetch markets
    events = fetch_active_markets()
    if not events:
        print("ERROR: No markets fetched. Exiting.")
        return
    
    print()
    
    # Step 2 & 3: Process events and find mispricings
    print("[2/7] Processing events and identifying mispricings...")
    
    all_mispricings = []
    markets_analyzed = 0
    markets_with_prices = 0
    
    for event in events:
        event_title = event.get('title', 'Unknown')
        event_slug = event.get('slug', '')
        event_desc = event.get('description', '')
        liquidity = float(event.get('liquidity', 0) or 0)
        category = categorize_market(event_title, event_desc)
        
        market_data_list = extract_market_data_from_event(event)
        
        for market_data in market_data_list:
            markets_analyzed += 1
            
            if market_data['prices']:
                markets_with_prices += 1
                mispricings = identify_mispricings_for_market(
                    event_title, event_slug, category, liquidity, market_data
                )
                all_mispricings.extend(mispricings)
    
    print(f"      Processed {markets_analyzed} markets from {len(events)} events")
    print(f"      Markets with valid prices: {markets_with_prices}")
    print(f"      Mispricings found: {len(all_mispricings)}")
    print()
    
    # Step 7: Sort by EV and report top 10
    print("[3/7] Sorting by expected value...")
    all_mispricings.sort(key=lambda x: x['expected_value'], reverse=True)
    
    print()
    print("[4/7] TOP 10 TRADE OPPORTUNITIES BY EXPECTED VALUE")
    print("=" * 70)
    
    top_trades = all_mispricings[:10]
    
    for i, trade in enumerate(top_trades, 1):
        print(f"\n#{i}: {trade['title'][:65]}")
        print(f"    Outcome: {trade['outcome']} | Direction: {trade['direction']}")
        print(f"    Market: {trade['market_price']:.3f} | Base Rate: {trade['base_rate']:.3f}")
        print(f"    Edge: {trade['edge']:.3f} ({trade['divergence']*100:.1f}% divergence)")
        print(f"    EV: ${trade['expected_value']:.4f} | ROI: {trade['roi_percent']:.1f}%")
        print(f"    Kelly: {trade['kelly_fraction']*100:.1f}% | Half-Kelly: {trade['half_kelly_fraction']*100:.1f}%")
        print(f"    Liquidity: ${trade['liquidity']:,.0f}")
        if trade['days_until_end'] is not None:
            print(f"    Days Until End: {trade['days_until_end']}")
    
    print()
    print("=" * 70)
    
    # Summary statistics
    if all_mispricings:
        buy_trades = [t for t in all_mispricings if t['direction'] == 'BUY']
        sell_trades = [t for t in all_mispricings if t['direction'] == 'SELL']
        
        print("\nSUMMARY STATISTICS")
        print("-" * 40)
        print(f"Total opportunities: {len(all_mispricings)}")
        print(f"  BUY opportunities: {len(buy_trades)}")
        print(f"  SELL opportunities: {len(sell_trades)}")
        if buy_trades:
            print(f"  Avg BUY edge: {sum(t['edge'] for t in buy_trades)/len(buy_trades)*100:.1f}%")
            print(f"  Avg BUY EV: ${sum(t['expected_value'] for t in buy_trades)/len(buy_trades):.4f}")
        if sell_trades:
            print(f"  Avg SELL edge: {sum(t['edge'] for t in sell_trades)/len(sell_trades)*100:.1f}%")
            print(f"  Avg SELL EV: ${sum(t['expected_value'] for t in sell_trades)/len(sell_trades):.4f}")
    
    # Save results
    print()
    print("[5/5] Saving results...")
    
    output = {
        'timestamp': datetime.now().isoformat(),
        'events_fetched': len(events),
        'markets_analyzed': markets_analyzed,
        'markets_with_prices': markets_with_prices,
        'mispricings_found': len(all_mispricings),
        'top_10_trades': top_trades,
        'all_opportunities': all_mispricings[:50],  # Top 50 for the file
        'summary': {
            'total_opportunities': len(all_mispricings),
            'buy_opportunities': len(buy_trades) if all_mispricings else 0,
            'sell_opportunities': len(sell_trades) if all_mispricings else 0,
            'avg_edge': sum(t['edge'] for t in all_mispricings) / len(all_mispricings) if all_mispricings else 0,
            'avg_ev': sum(t['expected_value'] for t in all_mispricings) / len(all_mispricings) if all_mispricings else 0,
        }
    }
    
    output_dir = '/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery'
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, 'base_rate_audit.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"      Saved to: {output_path}")
    print()
    print("BASE RATE AUDIT COMPLETE")
    print("=" * 70)

if __name__ == '__main__':
    run_base_rate_audit()