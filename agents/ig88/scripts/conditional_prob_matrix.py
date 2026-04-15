#!/usr/bin/env python3
"""
Conditional Probability Matrix for Polymarket crypto markets.
Strategy #2: "Claude holds thousands of conditional pairs humans cannot track."

Identifies mispricings where implied conditional probabilities are inconsistent.
"""

import urllib.request
import json
import re
import math
from datetime import datetime
from collections import defaultdict

OUTPUT_PATH = "/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/conditional_prob_matrix.json"

# Price thresholds for nested BTC markets
BTC_THRESHOLDS = [75000, 80000, 85000, 90000, 95000, 100000, 105000, 110000, 
                  120000, 125000, 130000, 140000, 150000, 175000, 200000, 250000, 300000]

ETH_THRESHOLDS = [2000, 2500, 3000, 3500, 4000, 4500, 5000, 6000, 7500, 8000, 10000, 12500, 15000]

SOL_THRESHOLDS = [100, 125, 150, 175, 200, 250, 300, 400, 500, 750, 1000]

def fetch_url(url, timeout=30):
    """Fetch a URL and return parsed JSON."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_polymarket_events():
    """Fetch all active Polymarket events via Gamma API with pagination."""
    all_events = []
    seen_ids = set()
    
    # Paginate through events
    for offset in range(0, 1000, 200):
        url = f'https://gamma-api.polymarket.com/events?limit=200&offset={offset}&active=true&closed=false'
        try:
            data = fetch_url(url)
            if not isinstance(data, list) or len(data) == 0:
                break
            for event in data:
                eid = event.get('id', '')
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    all_events.append(event)
            print(f"  Fetched events offset={offset}: got {len(data)} (total unique: {len(all_events)})")
            if len(data) < 200:
                break
        except Exception as e:
            print(f"  Warning: Failed at offset {offset}: {e}")
            break
    
    # Also fetch markets directly with pagination
    all_markets = []
    seen_mids = set()
    
    for offset in range(0, 2000, 200):
        url = f'https://gamma-api.polymarket.com/markets?limit=200&offset={offset}&active=true&closed=false'
        try:
            data = fetch_url(url)
            if not isinstance(data, list) or len(data) == 0:
                break
            for m in data:
                mid = m.get('id', m.get('conditionId', ''))
                if mid not in seen_mids:
                    seen_mids.add(mid)
                    all_markets.append(m)
            print(f"  Fetched markets offset={offset}: got {len(data)} (total unique: {len(all_markets)})")
            if len(data) < 200:
                break
        except Exception as e:
            print(f"  Warning: Failed at offset {offset}: {e}")
            break
    
    return all_events, all_markets


def extract_market_price(market):
    """Extract the 'Yes' price from a market object."""
    # Try various fields where price might be stored
    if 'outcomePrices' in market:
        try:
            prices = json.loads(market['outcomePrices']) if isinstance(market['outcomePrices'], str) else market['outcomePrices']
            if isinstance(prices, list) and len(prices) >= 1:
                return float(prices[0])
        except:
            pass
    
    if 'bestAsk' in market and market['bestAsk']:
        return float(market['bestAsk'])
    
    if 'lastTradePrice' in market and market['lastTradePrice']:
        return float(market['lastTradePrice'])
    
    if 'outcomePrice' in market:
        try:
            return float(market['outcomePrice'])
        except:
            pass
    
    return None


def extract_markets_from_event(event):
    """Extract individual markets from an event."""
    markets = []
    
    # Markets are often nested in events
    if 'markets' in event and event['markets']:
        for m in event['markets']:
            m['_event_title'] = event.get('title', '')
            m['_event_slug'] = event.get('slug', '')
            markets.append(m)
    
    # Some events have the market data directly
    if 'outcomePrices' in event:
        markets.append(event)
    
    return markets


def parse_price_from_title(title):
    """Extract a numeric price threshold from market title."""
    # Match patterns like "$100K", "$100,000", "$100000", "100k", "$7.5K", "$5,000"
    patterns = [
        # $100K, $7.5K, $1.5M  
        r'\$(\d+(?:\.\d+)?)\s*[kK]',  
        r'\$(\d+(?:\.\d+)?)\s*[mM]',  
        # $100,000 or $100000 or $5,000
        r'\$(\d{1,3}(?:,\d{3})+)',
        r'\$(\d{4,})',
        # 100K, 7.5K
        r'(\d+(?:\.\d+)?)\s*[kK]\b',
        r'(\d+(?:\.\d+)?)\s*[mM]\b',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            val_str = match.group(1).replace(',', '')
            val = float(val_str)
            context = title[max(0, match.start()-1):match.end()+2]
            if 'k' in context.lower():
                val *= 1000
            elif 'm' in context.lower():
                val *= 1000000
            return int(val)
    
    return None


def classify_market(title, description=''):
    """Classify a market into categories for pairing."""
    title_lower = title.lower()
    desc_lower = (description or '').lower()
    combined = title_lower + ' ' + desc_lower
    
    info = {
        'asset': None,
        'threshold': None,
        'direction': None,  # 'above' or 'below'
        'category': None,
    }
    
    # Detect asset (use word boundaries to avoid false matches)
    if re.search(r'\b(bitcoin|btc)\b', combined):
        info['asset'] = 'BTC'
    elif re.search(r'\b(ethereum|ether)\b', combined) or re.search(r'\beth\b', combined):
        info['asset'] = 'ETH'
    elif re.search(r'\bsolana\b', combined):
        info['asset'] = 'SOL'
    
    # Detect price thresholds - but exclude "holdings" markets
    threshold = parse_price_from_title(title)
    if threshold:
        # Exclude markets about holdings/accumulation (not price targets)
        is_holdings_market = any(x in combined for x in [
            'hold', 'holding', 'hodl', 'accumulate', 'treasury', 'announce',
            'microstrategy', 'bitmine', 'saylor', 'company', 'corporate'
        ])
        
        if not is_holdings_market:
            info['threshold'] = threshold
            
            # Check for "dip to" / "fall below" first (more specific)
            if any(x in combined for x in ['dip to', 'dip below', 'fall below', 'drop below', 'fall to', 'crash to']):
                info['direction'] = 'below'
            elif any(x in combined for x in ['below', 'under', 'less than']):
                info['direction'] = 'below'
            elif any(x in combined for x in ['above', 'over', 'reach', 'hit', 'exceed', 'surpass', 'greater', 'pass']):
                info['direction'] = 'above'
            else:
                # Default assumption for price targets
                info['direction'] = 'above'
            
            info['category'] = 'price_target'
    
    # Detect presidential/election markets
    if any(x in combined for x in ['president', 'election', 'win', 'nominee']):
        info['category'] = 'election'
    
    # Detect Fed rate markets
    if any(x in combined for x in ['federal reserve', 'fed ', 'interest rate', 'rate cut', 'rate hike']):
        info['category'] = 'fed_rates'
    
    # Detect crypto general movement
    if any(x in combined for x in ['bull market', 'bear market', 'all-time high', 'ath']):
        info['category'] = 'market_regime'
    
    return info


def kelly_criterion(prob_win, odds):
    """Calculate Kelly-optimal bet sizing.
    prob_win: estimated probability of winning
    odds: decimal odds (e.g., 2.0 means 2x payout)
    """
    if odds <= 1:
        return 0
    q = 1 - prob_win
    b = odds - 1  # net odds received on the bet
    kelly = (prob_win * b - q) / b
    return max(0, kelly)


def analyze_nested_price_markets(markets_by_asset):
    """Analyze nested BTC/ETH/SOL price markets for mispricings."""
    mispricings = []
    
    for asset, markets in markets_by_asset.items():
        # Filter to only markets with thresholds AND real prices (skip illiquid markets)
        markets_with_threshold = [m for m in markets 
                                   if m['info']['threshold'] is not None 
                                   and m['price'] is not None 
                                   and m['price'] > 0.005]  # Skip near-zero prices
        
        # Separate above and below markets
        above_markets = [m for m in markets_with_threshold if m['info']['direction'] == 'above']
        below_markets = [m for m in markets_with_threshold if m['info']['direction'] == 'below']
        
        # ===== ABOVE MARKETS =====
        # "Reach $150K" implies "Reach $100K", so P(reach 150K) <= P(reach 100K)
        # Higher threshold -> lower or equal probability
        above_markets_sorted = sorted(above_markets, key=lambda m: m['info']['threshold'])
        
        for i, m_high in enumerate(above_markets_sorted):
            for j, m_low in enumerate(above_markets_sorted):
                if m_high['info']['threshold'] <= m_low['info']['threshold']:
                    continue
                
                high_thresh = m_high['info']['threshold']
                low_thresh = m_low['info']['threshold']
                high_price = m_high['price']
                low_price = m_low['price']
                
                if high_price > low_price:
                    mispricing_amount = high_price - low_price
                    p_conditional = high_price / low_price if low_price > 0.01 else None
                    
                    mispricings.append({
                        'type': 'nested_above_violation',
                        'severity': 'HIGH',
                        'asset': asset,
                        'market_high': {
                            'title': m_high['title'],
                            'threshold': high_thresh,
                            'price': high_price,
                        },
                        'market_low': {
                            'title': m_low['title'],
                            'threshold': low_thresh,
                            'price': low_price,
                        },
                        'violation': f"P({asset}>={high_thresh}) = {high_price:.4f} > P({asset}>={low_thresh}) = {low_price:.4f}",
                        'mispricing_amount': mispricing_amount,
                        'direction': f"BUY {m_low['title']} / SELL {m_high['title']}",
                        'expected_value': mispricing_amount,
                        'kelly_fraction': min(0.25, mispricing_amount * 2),
                    })
                else:
                    p_conditional = high_price / low_price if low_price > 0.01 else None
                    
                    if p_conditional is not None and p_conditional > 0.95 and high_thresh > low_thresh * 1.5:
                        mispricings.append({
                            'type': 'unreasonable_conditional_above',
                            'severity': 'MEDIUM',
                            'asset': asset,
                            'market_high': {'title': m_high['title'], 'threshold': high_thresh, 'price': high_price},
                            'market_low': {'title': m_low['title'], 'threshold': low_thresh, 'price': low_price},
                            'conditional_prob': p_conditional,
                            'interpretation': f"P({asset}>={high_thresh} | {asset}>={low_thresh}) = {p_conditional:.2%}",
                            'direction': f"SELL {m_high['title']} / BUY {m_low['title']}",
                            'kelly_fraction': min(0.15, (p_conditional - 0.8) * 0.5),
                        })
                    
                    if p_conditional is not None and p_conditional < 0.10 and high_thresh < low_thresh * 1.2:
                        mispricings.append({
                            'type': 'unreasonable_conditional_above',
                            'severity': 'MEDIUM',
                            'asset': asset,
                            'market_high': {'title': m_high['title'], 'threshold': high_thresh, 'price': high_price},
                            'market_low': {'title': m_low['title'], 'threshold': low_thresh, 'price': low_price},
                            'conditional_prob': p_conditional,
                            'interpretation': f"P({asset}>={high_thresh} | {asset}>={low_thresh}) = {p_conditional:.2%} seems too low",
                            'direction': f"BUY {m_high['title']} / SELL {m_low['title']}",
                            'kelly_fraction': min(0.15, (0.3 - p_conditional) * 0.5),
                        })
        
        # ===== BELOW MARKETS =====
        # "Dip to $5K" implies "Dip to $60K", so P(dip to 5K) <= P(dip to 60K)
        # Lower threshold -> lower or equal probability
        below_markets_sorted = sorted(below_markets, key=lambda m: m['info']['threshold'])
        
        for i, m_low in enumerate(below_markets_sorted):
            for j, m_high in enumerate(below_markets_sorted):
                if m_low['info']['threshold'] >= m_high['info']['threshold']:
                    continue
                
                low_thresh = m_low['info']['threshold']
                high_thresh = m_high['info']['threshold']
                low_price = m_low['price']
                high_price = m_high['price']
                
                if low_price > high_price:
                    mispricing_amount = low_price - high_price
                    p_conditional = low_price / high_price if high_price > 0.01 else None
                    
                    mispricings.append({
                        'type': 'nested_below_violation',
                        'severity': 'HIGH',
                        'asset': asset,
                        'market_low_threshold': {
                            'title': m_low['title'],
                            'threshold': low_thresh,
                            'price': low_price,
                        },
                        'market_high_threshold': {
                            'title': m_high['title'],
                            'threshold': high_thresh,
                            'price': high_price,
                        },
                        'violation': f"P({asset} dips to {low_thresh}) = {low_price:.4f} > P({asset} dips to {high_thresh}) = {high_price:.4f}",
                        'mispricing_amount': mispricing_amount,
                        'direction': f"BUY {m_high['title']} / SELL {m_low['title']}",
                        'expected_value': mispricing_amount,
                        'kelly_fraction': min(0.25, mispricing_amount * 2),
                    })
    
    return mispricings


def analyze_election_markets(markets):
    """Analyze election/presidential markets for sum-to-one violations."""
    mispricings = []
    
    # Group by election event
    election_groups = defaultdict(list)
    
    for m in markets:
        if m['info']['category'] != 'election':
            continue
        title = m['title'].lower()
        
        # Try to group by year/office
        year_match = re.search(r'20\d{2}', title)
        year = year_match.group() if year_match else 'unknown'
        
        if 'president' in title:
            election_groups[f'president_{year}'].append(m)
    
    for group_name, group_markets in election_groups.items():
        if len(group_markets) < 2:
            continue
        
        total_prob = sum(m['price'] for m in group_markets if m['price'] is not None)
        
        # Allow ~10% for third parties / uncertainty
        if total_prob > 1.10:
            mispricings.append({
                'type': 'election_sum_exceeds_one',
                'severity': 'MEDIUM',
                'group': group_name,
                'total_probability': total_prob,
                'excess': total_prob - 1.0,
                'markets': [{'title': m['title'], 'price': m['price']} for m in group_markets if m['price']],
                'direction': 'SELL the overpriced candidates (sum > 1.10)',
                'kelly_fraction': min(0.20, (total_prob - 1.05) * 2),
            })
        elif total_prob < 0.90:
            mispricings.append({
                'type': 'election_sum_below_one',
                'severity': 'MEDIUM',
                'group': group_name,
                'total_probability': total_prob,
                'deficit': 1.0 - total_prob,
                'markets': [{'title': m['title'], 'price': m['price']} for m in group_markets if m['price']],
                'direction': 'BUY the underpriced candidates (sum < 0.90)',
                'kelly_fraction': min(0.15, (0.95 - total_prob) * 2),
            })
    
    return mispricings


def analyze_cross_asset_correlations(markets_by_asset):
    """Analyze implied correlations between crypto assets."""
    mispricings = []
    
    # If BTC is very likely to hit $100K (e.g., P=0.85),
    # ETH should also be reasonably likely to hit its moderate targets
    # We can check for consistency in bullishness
    
    btc_markets = markets_by_asset.get('BTC', [])
    eth_markets = markets_by_asset.get('ETH', [])
    
    # Find the "mood" of BTC markets
    btc_above_markets = [m for m in btc_markets if m['info']['direction'] == 'above']
    if btc_above_markets:
        avg_btc_bullishness = sum(m['price'] for m in btc_above_markets) / len(btc_above_markets)
        
        # Check ETH markets for consistency
        eth_above_markets = [m for m in eth_markets if m['info']['direction'] == 'above']
        if eth_above_markets:
            avg_eth_bullishness = sum(m['price'] for m in eth_above_markets) / len(eth_above_markets)
            
            # Historical BTC/ETH correlation is ~0.85
            # If BTC markets are very bullish but ETH markets are very bearish (or vice versa), flag it
            if avg_btc_bullishness > 0.6 and avg_eth_bullishness < 0.3:
                mispricings.append({
                    'type': 'cross_asset_divergence',
                    'severity': 'LOW',
                    'description': 'BTC markets are bullish but ETH markets are bearish',
                    'btc_avg_bullishness': avg_btc_bullishness,
                    'eth_avg_bullishness': avg_eth_bullishness,
                    'direction': 'Consider BUYING ETH targets / SELLING BTC targets',
                    'note': 'Historical BTC/ETH correlation is ~0.85',
                })
    
    return mispricings


def analyze_causal_chains(markets):
    """Analyze causal chain consistency (Fed -> crypto -> price targets)."""
    mispricings = []
    
    fed_markets = [m for m in markets if m['info']['category'] == 'fed_rates']
    crypto_price_markets = []
    for asset in ['BTC', 'ETH', 'SOL']:
        crypto_price_markets.extend([m for m in markets 
                                      if m['info']['asset'] == asset and m['info']['category'] == 'price_target'])
    
    # If Fed is likely to cut rates (bullish for crypto),
    # crypto price targets should be more likely
    for fed_m in fed_markets:
        fed_title_lower = fed_m['title'].lower()
        if 'cut' in fed_title_lower or 'lower' in fed_title_lower:
            # Bullish for crypto
            fed_prob = fed_m['price']
            if fed_prob and fed_prob > 0.6:
                # Fed cuts are likely, check if crypto markets reflect this
                for cp in crypto_price_markets:
                    if cp['price'] and cp['price'] < 0.2 and cp['info']['direction'] == 'above':
                        # Fed likely cutting but crypto price targets very low?
                        if cp['info']['threshold'] and cp['info']['threshold'] < 120000:
                            mispricings.append({
                                'type': 'causal_inconsistency',
                                'severity': 'LOW',
                                'fed_market': fed_m['title'],
                                'fed_prob': fed_prob,
                                'crypto_market': cp['title'],
                                'crypto_prob': cp['price'],
                                'description': 'Fed likely cutting rates but moderate crypto targets seem low',
                                'direction': f"BUY {cp['title']}",
                                'kelly_fraction': 0.05,
                            })
    
    return mispricings


def analyze_time_based_milestones(markets):
    """Analyze time-based milestone markets for consistency."""
    mispricings = []
    
    # E.g., "BTC $100K by June" should be <= "BTC $100K by December"
    # Group by asset + threshold, compare by date
    
    for asset in ['BTC', 'ETH', 'SOL']:
        asset_markets = [m for m in markets if m['info']['asset'] == asset 
                         and m['info']['threshold'] is not None 
                         and m['price'] is not None and m['price'] > 0.005]
        
        # Group by threshold
        by_threshold = defaultdict(list)
        for m in asset_markets:
            by_threshold[m['info']['threshold']].append(m)
        
        for threshold, thresh_markets in by_threshold.items():
            # Markets with earlier deadlines should have LOWER probability
            # than markets with later deadlines (same threshold)
            for i, m1 in enumerate(thresh_markets):
                for m2 in thresh_markets[i+1:]:
                    if m1['price'] is None or m2['price'] is None:
                        continue
                    
                    # Check if earlier deadline has higher probability
                    title1_lower = m1['title'].lower()
                    title2_lower = m2['title'].lower()
                    
                    # Simple heuristic: "by 2025" < "by 2026" etc
                    year1 = re.search(r'20\d{2}', title1_lower)
                    year2 = re.search(r'20\d{2}', title2_lower)
                    
                    if year1 and year2:
                        y1, y2 = int(year1.group()), int(year2.group())
                        if y1 < y2 and m1['price'] > m2['price']:
                            mispricings.append({
                                'type': 'time_inconsistency',
                                'severity': 'MEDIUM',
                                'earlier_market': m1['title'],
                                'later_market': m2['title'],
                                'earlier_price': m1['price'],
                                'later_price': m2['price'],
                                'description': f'Earlier deadline ({y1}) has higher probability than later ({y2})',
                                'direction': f"BUY {m2['title']} / SELL {m1['title']}",
                                'kelly_fraction': min(0.15, (m1['price'] - m2['price']) * 0.5),
                            })
    
    return mispricings


def build_conditional_probability_matrix():
    """Main function to build the conditional probability matrix."""
    print("=" * 60)
    print("CONDITIONAL PROBABILITY MATRIX BUILDER")
    print("Strategy #2: Conditional Pairs Analysis")
    print("=" * 60)
    
    # Step 1: Fetch markets
    print("\n[1/5] Fetching Polymarket events and markets...")
    events, direct_markets = fetch_polymarket_events()
    print(f"  Fetched {len(events)} events, {len(direct_markets)} direct markets")
    
    # Step 2: Extract and classify all markets
    print("\n[2/5] Extracting and classifying markets...")
    all_markets = []
    
    # From events
    for event in events:
        event_markets = extract_markets_from_event(event)
        all_markets.extend(event_markets)
    
    # From direct markets
    all_markets.extend(direct_markets)
    
    # Deduplicate
    seen = set()
    unique_markets = []
    for m in all_markets:
        mid = m.get('id', m.get('conditionId', m.get('question', '')))
        if mid and mid not in seen:
            seen.add(mid)
            unique_markets.append(m)
    
    all_markets = unique_markets
    print(f"  Total unique markets: {len(all_markets)}")
    
    # Classify each market
    classified_markets = []
    for m in all_markets:
        title = m.get('title', m.get('question', m.get('description', '')))
        desc = m.get('description', '') or ''
        info = classify_market(title, desc)
        price = extract_market_price(m)
        
        classified_markets.append({
            'title': title,
            'price': price,
            'info': info,
            'raw': m,
        })
    
    # Group by asset
    markets_by_asset = defaultdict(list)
    for m in classified_markets:
        if m['info']['asset']:
            markets_by_asset[m['info']['asset']].append(m)
    
    print(f"  BTC markets: {len(markets_by_asset['BTC'])}")
    print(f"  ETH markets: {len(markets_by_asset['ETH'])}")
    print(f"  SOL markets: {len(markets_by_asset['SOL'])}")
    
    # Step 3: Run all analyses
    print("\n[3/5] Running conditional probability analyses...")
    
    all_mispricings = []
    
    # Nested price markets
    print("  - Analyzing nested price markets...")
    nested = analyze_nested_price_markets(markets_by_asset)
    all_mispricings.extend(nested)
    print(f"    Found {len(nested)} nested mispricings")
    
    # Election markets
    print("  - Analyzing election markets...")
    election = analyze_election_markets(classified_markets)
    all_mispricings.extend(election)
    print(f"    Found {len(election)} election mispricings")
    
    # Cross-asset correlations
    print("  - Analyzing cross-asset correlations...")
    cross_asset = analyze_cross_asset_correlations(markets_by_asset)
    all_mispricings.extend(cross_asset)
    print(f"    Found {len(cross_asset)} cross-asset mispricings")
    
    # Causal chains
    print("  - Analyzing causal chains...")
    causal = analyze_causal_chains(classified_markets)
    all_mispricings.extend(causal)
    print(f"    Found {len(causal)} causal chain mispricings")
    
    # Time-based milestones
    print("  - Analyzing time-based milestones...")
    time_based = analyze_time_based_milestones(classified_markets)
    all_mispricings.extend(time_based)
    print(f"    Found {len(time_based)} time-based mispricings")
    
    # Step 4: Rank and get top 20
    print("\n[4/5] Ranking mispricings...")
    
    # Sort by severity then by mispricing amount/kelly
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    all_mispricings.sort(key=lambda x: (
        severity_order.get(x.get('severity', 'LOW'), 3),
        -x.get('mispricing_amount', 0),
        -x.get('kelly_fraction', 0),
    ))
    
    top_20 = all_mispricings[:20]
    
    # Step 5: Build the conditional probability matrix for price markets
    print("\n[5/5] Building conditional probability matrix...")
    
    conditional_matrix = {}
    for asset in ['BTC', 'ETH', 'SOL']:
        asset_markets = markets_by_asset.get(asset, [])
        above_markets = [m for m in asset_markets 
                         if m['info']['direction'] == 'above' and m['info']['threshold'] and m['price'] is not None]
        above_markets.sort(key=lambda m: m['info']['threshold'])
        
        matrix = {}
        for i, m_high in enumerate(above_markets):
            for j, m_low in enumerate(above_markets):
                if m_high['info']['threshold'] <= m_low['info']['threshold']:
                    continue
                
                p_high = m_high['price']
                p_low = m_low['price']
                
                if p_low > 0.01:
                    p_conditional = p_high / p_low
                else:
                    p_conditional = None
                
                key = f"P({asset}>={m_high['info']['threshold']}|{asset}>={m_low['info']['threshold']})"
                matrix[key] = {
                    'conditional_prob': p_conditional,
                    'p_joint': p_high,
                    'p_condition': p_low,
                    'high_threshold': m_high['info']['threshold'],
                    'low_threshold': m_low['info']['threshold'],
                }
        
        conditional_matrix[asset] = matrix
    
    # Build output
    output = {
        'metadata': {
            'strategy': 'Conditional Probability Matrix (Strategy #2)',
            'source': 'Polymarket Gamma API',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'total_events': len(events),
            'total_markets': len(all_markets),
            'btc_markets': len(markets_by_asset.get('BTC', [])),
            'eth_markets': len(markets_by_asset.get('ETH', [])),
            'sol_markets': len(markets_by_asset.get('SOL', [])),
            'total_mispricings_found': len(all_mispricings),
        },
        'top_20_mispricings': top_20,
        'conditional_probability_matrix': conditional_matrix,
        'all_mispricings': all_mispricings,
        'market_inventory': {
            'btc_price_targets': [
                {'title': m['title'], 'threshold': m['info']['threshold'], 'price': m['price']}
                for m in markets_by_asset.get('BTC', [])
                if m['info']['category'] == 'price_target' and m['price'] is not None
            ],
            'eth_price_targets': [
                {'title': m['title'], 'threshold': m['info']['threshold'], 'price': m['price']}
                for m in markets_by_asset.get('ETH', [])
                if m['info']['category'] == 'price_target' and m['price'] is not None
            ],
            'election_markets': [
                {'title': m['title'], 'price': m['price']}
                for m in classified_markets
                if m['info']['category'] == 'election' and m['price'] is not None
            ],
        },
    }
    
    # Save
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    # Print summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"\nTotal mispricings found: {len(all_mispricings)}")
    print(f"\nTop 20 mispricings:")
    for i, m in enumerate(top_20, 1):
        print(f"\n  #{i} [{m.get('severity', '?')}] {m.get('type', '?')}")
        if 'violation' in m:
            print(f"     {m['violation']}")
        if 'description' in m:
            print(f"     {m['description']}")
        if 'direction' in m:
            print(f"     Direction: {m['direction']}")
        if 'kelly_fraction' in m:
            print(f"     Kelly fraction: {m['kelly_fraction']:.2%}")
    
    print(f"\nOutput saved to: {OUTPUT_PATH}")
    return output


if __name__ == '__main__':
    build_conditional_probability_matrix()
