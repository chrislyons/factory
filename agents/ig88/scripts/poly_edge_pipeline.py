#!/usr/bin/env python3
"""
Polymarket Edge Pipeline
==========================
Systematic approach to finding and exploiting informational edge.

Strategy Matrix:
1. Calibration Arbitrage - LLM vs market prices (primary)
2. Temporal Edge - Early assessment before market updates
3. Category Specialization - Focus on domains with asymmetric knowledge
4. Cross-Market Correlation - Related market inefficiencies
"""
import json
import subprocess
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import hashlib

OUTPUT_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
CALIBRATION_FILE = OUTPUT_DIR / 'llm_calibration_history.json'
EDGE_LOG_FILE = OUTPUT_DIR / 'polymarket_edge_log.json'


def fetch_active_markets(limit=100, category=None):
    """Fetch active markets from Polymarket."""
    url = f"https://gamma-api.polymarket.com/events?active=true&closed=false&limit={limit}"
    if category:
        url += f"&tag={category}"
    
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(result.stdout)
    except:
        return []


def fetch_market_details(slug):
    """Get detailed market info including order book."""
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        return data[0] if data else None
    except:
        return None


def get_clob_midpoint(token_id):
    """Get CLOB midpoint price for accurate market price."""
    url = f"https://clob.polymarket.com/midpoint?token_id={token_id}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=10)
    try:
        data = json.loads(result.stdout)
        return float(data.get('midpoint', 0))
    except:
        return None


@dataclass
class MarketAssessment:
    """LLM assessment of a market."""
    market_slug: str
    question: str
    category: str
    market_price: float          # Current market probability
    llm_probability: float       # Our estimate
    confidence: float            # LLM confidence (0-1)
    edge: float                  # |market - llm|
    reasoning: str
    assessment_time: str
    resolution_date: str
    resolution_source: str
    tokens: dict                 # token_id -> outcome mapping
    trade_recommended: bool
    trade_size_usd: float
    expected_value: float        # Edge * potential payout - fees


def assess_geopolitical(question: str, context: str = "") -> tuple[float, float, str]:
    """Assess geopolitical markets - area where LLMs may have edge."""
    q = question.lower()
    
    # Russia-Ukraine
    if 'russia' in q and 'ukraine' in q:
        if 'ceasefire' in q:
            # Historical: active conflicts rarely end in ceasefire quickly
            # But diplomatic pressure can force progress
            if '2025' in q or '2026' in q:
                return 0.25, 0.55, "Active conflict, 3+ years in. Ceasefire historically unlikely but diplomatic pressure mounting. Base rate ~20-30%."
            return 0.20, 0.5, "Ceasefire probability low in active conflict"
        
        if 'treaty' in q or 'peace' in q:
            return 0.15, 0.5, "Formal treaty even rarer than ceasefire. Base rate <20%."
    
    # China-Taiwan
    if 'china' in q and 'taiwan' in q:
        if 'invasion' in q or 'military' in q:
            return 0.04, 0.7, "Economic costs prohibitive. US deterrence. Historical base rate <5% for direct action."
        if 'blockade' in q:
            return 0.10, 0.55, "Blockade more likely than invasion but still low probability"
    
    # US Politics
    if 'trump' in q:
        if 'impeach' in q or 'remov' in q:
            return 0.08, 0.6, "Historically only Nixon resigned. Base rate <10%."
        if '2026' in q or 'election' in q:
            return 0.45, 0.4, "Midterms historically swing against incumbent. Polling uncertain."
    
    # Middle East
    if 'israel' in q or 'gaza' in q or 'iran' in q:
        if 'ceasefire' in q or 'peace' in q:
            return 0.30, 0.45, "Complex conflict with multiple actors. Ceasefire possible but fragile."
        if 'iran' in q and ('nuclear' in q or 'attack' in q):
            return 0.08, 0.5, "Direct conflict very costly. Base rate <10%."
    
    return 0.50, 0.3, "Insufficient domain knowledge for confident assessment"


def assess_crypto_event(question: str) -> tuple[float, float, str]:
    """Assess crypto-related event markets."""
    q = question.lower()
    
    # ETF approval
    if 'etf' in q:
        if 'solana' in q or 'sol' in q:
            return 0.75, 0.6, "SEC has approved BTC/ETH ETFs. SOL ETF applications pending. Precedent favors approval."
        if 'xrp' in q:
            return 0.55, 0.5, "XRP has favorable court ruling but SEC may appeal"
        if 'ethereum' in q or 'eth' in q:
            return 0.90, 0.7, "ETH ETF already approved in 2024"
    
    # Price targets (less informed than markets)
    if '$100k' in q or '$100,000' in q:
        return 0.55, 0.4, "BTC price prediction inherently uncertain"
    
    # Halving effects
    if 'halving' in q:
        if 'all time high' in q or 'ath' in q:
            return 0.70, 0.55, "Post-halving ATH historically occurs within 12-18 months"
    
    return 0.50, 0.35, "Crypto events highly uncertain"


def assess_technology(question: str) -> tuple[float, float, str]:
    """Assess technology/AI markets."""
    q = question.lower()
    
    # AI milestones
    if 'agi' in q or 'artificial general intelligence' in q:
        if '2026' in q or '2027' in q:
            return 0.15, 0.4, "AGI timeline highly debated. Industry insiders give 10-25% for near-term."
        return 0.25, 0.35, "AGI probability increases with timeframe"
    
    if 'ai' in q and ('regulat' in q or 'ban' in q):
        return 0.40, 0.45, "AI regulation momentum increasing. EU AI Act passed. US likely to follow."
    
    # Product launches
    if 'gta' in q or 'grand theft auto' in q:
        if '2025' in q or '2026' in q:
            return 0.65, 0.55, "Rockstar targeting 2025-2026. Historical delays common but window realistic."
    
    if 'apple' in q and ('ar' in q or 'vision' in q):
        return 0.30, 0.4, "Apple Vision pro has niche adoption. New product launches uncertain."
    
    return 0.50, 0.35, "Technology predictions inherently uncertain"


def assess_sports(question: str) -> tuple[float, float, str]:
    """Assess sports markets - generally no LLM edge over markets."""
    q = question.lower()
    
    # Sports outcomes are efficiently priced
    # Base rate approach: most games are ~50/50 without detailed analysis
    
    if 'nba' in q:
        # Slight home court advantage
        if 'home' in q:
            return 0.55, 0.3, "Home court advantage ~4-5% in NBA"
        return 0.50, 0.25, "Sports outcomes near 50/50 without matchup analysis"
    
    if 'nfl' in q:
        return 0.50, 0.25, "NFL outcomes near 50/50 without matchup analysis"
    
    if 'championship' in q or 'win' in q:
        # 30 teams, base rate ~3%
        return 0.05, 0.3, "Championship outcomes dominated by small number of contenders"
    
    return 0.50, 0.25, "Sports markets efficiently priced"


def assess_market_blind(question: str, category: str, context: str = "") -> tuple[float, float, str]:
    """
    Main LLM assessment function - dispatches to category specialists.
    
    Returns: (probability, confidence, reasoning)
    """
    cat_lower = category.lower() if category else ""
    
    # Dispatch to specialist
    if any(g in cat_lower for g in ['politic', 'geopolit', 'current affairs', 'government']):
        return assess_geopolitical(question, context)
    
    if any(c in cat_lower for c in ['crypto', 'bitcoin', 'ethereum', 'defi']):
        return assess_crypto_event(question)
    
    if any(t in cat_lower for t in ['tech', 'ai', 'science', 'space']):
        return assess_technology(question)
    
    if any(s in cat_lower for s in ['sport', 'nba', 'nfl', 'nhl', 'soccer', 'football']):
        return assess_sports(question)
    
    # Check question content for category hints
    q = question.lower()
    if 'ceasefire' in q or 'invasion' in q or 'treaty' in q:
        return assess_geopolitical(question, context)
    if 'bitcoin' in q or 'crypto' in q or 'etf' in q:
        return assess_crypto_event(question)
    if 'ai' in q or 'agi' in q or 'tech' in q:
        return assess_technology(question)
    
    return 0.50, 0.25, f"Unknown category '{category}'. Using uninformative prior."


def calculate_expected_value(edge: float, market_price: float, fees: float = 0.0) -> float:
    """Calculate expected value of a trade."""
    if abs(edge) < 0.05:
        return 0  # Minimum edge threshold
    
    if edge > 0:
        # Buy YES at market_price, payout = 1
        ev = edge * (1 - market_price) - (1 - edge) * market_price - fees
    else:
        # Buy NO at (1-market_price), payout = 1
        ev = abs(edge) * market_price - (1 - abs(edge)) * (1 - market_price) - fees
    
    return ev


def kelly_size(edge: float, market_price: float, bankroll: float = 10000, kelly_frac: float = 0.25) -> float:
    """Quarter-Kelly position sizing."""
    if abs(edge) < 0.05:
        return 0
    
    # Kelly formula: f* = (p*b - q) / b
    # For binary: b = (1 - price) / price, p = edge + 0.5
    win_prob = 0.5 + abs(edge) / 2
    
    if edge > 0:
        odds = (1 - market_price) / market_price
    else:
        odds = market_price / (1 - market_price)
    
    if odds <= 0:
        return 0
    
    kelly = (win_prob * odds - (1 - win_prob)) / odds
    
    # Quarter Kelly for safety
    position = bankroll * max(0, kelly * kelly_frac)
    
    # Clamp to $5-$500 range
    return min(max(position, 5), 500)


def scan_markets_for_edge(min_edge=0.10, min_confidence=0.4):
    """Scan active markets for informational edge."""
    print("=" * 80)
    print("POLYMARKET EDGE SCANNER")
    print("=" * 80)
    
    # Fetch active markets
    print("\n[1] Fetching active markets...")
    events = fetch_active_markets(limit=200)
    print(f"  Found {len(events)} active events")
    
    # Process each market
    assessments = []
    
    for event in events:
        markets = event.get('markets', [])
        category = event.get('category', 'Unknown')
        
        for market in markets:
            question = market.get('question', '')
            if not question:
                continue
            
            # Get prices from outcomePrices
            prices_str = market.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                prices = [float(p) for p in prices]
            except:
                continue
            
            if len(prices) < 2:
                continue
            
            # Get Yes price (first outcome is typically Yes)
            yes_price = prices[0]
            no_price = prices[1]
            
            # Skip resolved markets (price at 0 or 1)
            if yes_price <= 0.01 or yes_price >= 0.99:
                continue
            
            token_map = {'Yes': '', 'No': ''}
            for token in market.get('tokens', []):
                token_map[token.get('outcome', '')] = token.get('token_id', '')
            
            # LLM assessment (BLIND - no market price)
            category = event.get('category', '')
            llm_prob, confidence, reasoning = assess_market_blind(question, category)
            
            # Calculate edge
            edge = llm_prob - yes_price
            
            # Expected value
            ev = calculate_expected_value(edge, yes_price, fees=0)  # Zero fees!
            
            # Position size
            position = kelly_size(edge, yes_price)
            
            # Check thresholds
            if abs(edge) >= min_edge and confidence >= min_confidence:
                assessment = MarketAssessment(
                    market_slug=market.get('slug', ''),
                    question=question[:150],
                    category=category,
                    market_price=yes_price,
                    llm_probability=llm_prob,
                    confidence=confidence,
                    edge=edge,
                    reasoning=reasoning[:200],
                    assessment_time=datetime.now(timezone.utc).isoformat(),
                    resolution_date=market.get('endDate', ''),
                    resolution_source=market.get('resolutionSource', ''),
                    tokens=token_map,
                    trade_recommended=abs(ev) > 0.02,
                    trade_size_usd=position,
                    expected_value=ev,
                )
                assessments.append(assessment)
    
    # Sort by edge
    assessments.sort(key=lambda a: abs(a.edge), reverse=True)
    
    # Display results
    print(f"\n[2] Scanned {len(events)} events, found {len(assessments)} with edge > {min_edge:.0%}")
    
    if assessments:
        print("\n--- TOP OPPORTUNITIES ---")
        for a in assessments[:10]:
            direction = "BUY YES" if a.edge > 0 else "BUY NO"
            print(f"\n  [{a.category:15}] Edge: {a.edge:+.1%} | EV: {a.expected_value:+.1%}")
            print(f"  LLM: {a.llm_probability:.0%} vs Market: {a.market_price:.0%} | Conf: {a.confidence:.0%}")
            print(f"  {direction} ${a.trade_size_usd:.0f} @ {a.market_price:.2%}")
            print(f"  {a.question[:70]}...")
            print(f"  Reasoning: {a.reasoning[:80]}...")
    
    # Summary stats
    print("\n" + "=" * 80)
    print("EDGE SUMMARY")
    print("=" * 80)
    
    buy_yes = [a for a in assessments if a.edge > 0]
    buy_no = [a for a in assessments if a.edge < 0]
    
    print(f"\nTotal opportunities: {len(assessments)}")
    print(f"BUY YES: {len(buy_yes)} (avg edge: {np.mean([a.edge for a in buy_yes]):.1%})" if buy_yes else "BUY YES: 0")
    print(f"BUY NO: {len(buy_no)} (avg edge: {np.mean([abs(a.edge) for a in buy_no]):.1%})" if buy_no else "BUY NO: 0")
    
    total_ev = sum(a.expected_value for a in assessments)
    total_position = sum(a.trade_size_usd for a in assessments)
    print(f"\nTotal expected value: ${total_ev:.2f}")
    print(f"Total position size: ${total_position:.2f}")
    
    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(EDGE_LOG_FILE, 'w') as f:
        json.dump({
            'scan_time': datetime.now(timezone.utc).isoformat(),
            'events_scanned': len(events),
            'opportunities': len(assessments),
            'assessments': [asdict(a) for a in assessments],
        }, f, indent=2)
    
    print(f"\nResults saved to {EDGE_LOG_FILE}")
    
    return assessments


if __name__ == '__main__':
    scan_markets_for_edge(min_edge=0.10, min_confidence=0.4)
