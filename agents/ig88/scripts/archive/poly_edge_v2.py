#!/usr/bin/env python3
"""
Polymarket Edge Pipeline v2
==============================
Improved LLM assessment with better probability calibration.

Key improvements:
1. Proper base rates for long-shot events
2. Confidence-weighted edge
3. Skip markets where LLM has no advantage
"""
import json
import subprocess
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict

OUTPUT_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')


@dataclass
class TradeSignal:
    market_slug: str
    question: str
    category: str
    market_price: float
    llm_probability: float
    edge: float
    confidence: float
    direction: str  # YES or NO
    expected_value: float
    reasoning: str
    resolution_date: str


def assess_with_base_rates(question: str) -> tuple[float, float, str]:
    """
    Improved assessment using proper base rates.
    
    Key principle: Most prediction markets are efficiently priced.
    We only bet when we have SPECIFIC knowledge the market lacks.
    """
    q = question.lower()
    
    # === GEOPOLITICS (where LLMs have advantage) ===
    
    # Russia-Ukraine ceasefire/treaty
    if 'russia' in q and 'ukraine' in q:
        if 'ceasefire' in q:
            # Active conflicts: ceasefire probability depends on military situation
            # Current (2026): Russia has territorial gains, Ukraine counteroffensive stalled
            if '2026' in q or 'june' in q:
                return 0.22, 0.6, "Military stalemate favors negotiated pause. Prior ceasefires ~20%."
            return 0.18, 0.55, "Active conflict, ceasefire historically unlikely without military exhaustion"
        
        if 'treaty' in q or 'peace deal' in q:
            return 0.08, 0.65, "Formal treaties require political resolution. Base rate <10% in active conflicts."
        
        if 'war' in q and 'end' in q:
            return 0.15, 0.55, "Wars end via treaty, exhaustion, or escalation. Timeline uncertain."
    
    # Israel-Hamas/Middle East
    if ('israel' in q or 'gaza' in q or 'hamas' in q):
        if 'ceasefire' in q:
            if 'phase' in q or 'ii' in q:
                return 0.40, 0.5, "Phase I partially implemented. Phase II depends on hostage negotiations."
            return 0.35, 0.5, "Multiple ceasefire rounds attempted. Probability moderate."
        
        if 'iran' in q:
            if 'attack' in q or 'strike' in q:
                return 0.06, 0.6, "Direct Iran-Israel conflict would be regionally devastating. Deterrence holds."
            if 'nuclear' in q:
                return 0.12, 0.55, "Iran nuclear breakout timeline 6-12 months. Political decision unclear."
    
    # US Politics
    if 'trump' in q:
        if 'impeach' in q or 'remov' in q or 'resign' in q:
            return 0.04, 0.7, "No president has been removed. Nixon resigned under pressure. Base rate ~4%."
        if '2028' in q or 'third term' in q:
            return 0.02, 0.8, "Constitutional prohibition. Base rate effectively zero."
        if '2026' in q or 'midterm' in q:
            return 0.45, 0.45, "Midterms typically swing against incumbent. Margin uncertain."
    
    if 'democrat' in q and '2028' in q:
        return 0.50, 0.35, "Primary field completely open. Too early to assess."
    
    # China-Taiwan
    if 'china' in q and 'taiwan' in q:
        if 'invasion' in q or 'attack' in q or 'war' in q:
            return 0.02, 0.8, "Economic costs ~$2T+. US deterrence strong. Historical base rate <2%."
        if 'blockade' in q or 'quarantine' in q:
            return 0.08, 0.6, "Blockade more plausible than invasion but still low probability."
        if 'reunif' in q or 'take' in q:
            return 0.05, 0.7, "Peaceful or coercive more likely than military. Low base rate."
    
    # === CRYPTO (market efficient, limited edge) ===
    
    if 'etf' in q:
        if 'solana' in q or 'sol' in q:
            # SOL ETF applications filed, SEC reviewing
            if '2025' in q or '2026' in q:
                return 0.72, 0.55, "SOL ETF applications pending. BTC/ETH precedent favors approval. Timeline uncertain."
            return 0.65, 0.5, "ETF approval likely within 1-2 years given precedent"
        
        if 'xrp' in q:
            return 0.55, 0.45, "Ripple court victory positive but SEC may still appeal"
        
        if 'doge' in q:
            return 0.25, 0.5, "DOGE ETF less likely given memecoin status"
        
        return 0.40, 0.35, "New ETF launches uncertain without specific filing info"
    
    # Bitcoin price targets (markets are efficient)
    if 'bitcoin' in q or 'btc' in q:
        if '$100k' in q or '100,000' in q:
            if '2025' in q:
                return 0.55, 0.35, "BTC ~$85k now. Need 18% move. Historical probability ~55%."
            return 0.65, 0.4, "Longer timeframe increases probability"
        if '$50k' in q or '50,000' in q:
            return 0.20, 0.5, "Would require 40% drop. Unlikely without major catalyst"
        if '$1m' in q or '1,000,000' in q:
            return 0.02, 0.7, "12x move in timeframe. Base rate <2%."
    
    # Halving
    if 'halv' in q:
        if 'all time high' in q or 'ath' in q:
            if '2025' in q:
                return 0.75, 0.5, "Post-halving ATH historically within 12-18 months"
            return 0.85, 0.55, "ATH likely within 2 years of halving"
    
    # === ENTERTAINMENT ===
    
    if 'gta' in q or 'grand theft auto' in q:
        if '2025' in q:
            return 0.40, 0.5, "Rockstar announced but delays common. 40% for 2025."
        if '2026' in q:
            return 0.75, 0.55, "If not 2025, almost certainly 2026. Window realistic."
    
    if 'rihanna' in q and 'album' in q:
        return 0.15, 0.5, "No album since 2016. Base rate for return ~15% annually"
    
    if 'beyonce' in q and 'tour' in q:
        return 0.40, 0.4, "Tour decisions based on album cycle. Moderate probability."
    
    # === SPORTS (markets are efficient, no edge) ===
    
    if any(s in q for s in ['nba', 'nfl', 'nhl', 'mlb', 'soccer', 'champions league']):
        # Sports markets are highly efficient - no edge for LLM
        return 0.50, 0.15, "Sports markets efficiently priced. No informational advantage."
    
    # === SCIENCE/TECH ===
    
    if 'agi' in q or 'artificial general intelligence' in q:
        if '2026' in q:
            return 0.08, 0.5, "AGI timeline highly debated. Industry insiders give 5-15% for 2026."
        if '2030' in q:
            return 0.25, 0.4, "AGI by 2030: experts estimate 20-30%"
    
    if 'spacex' in q and ('mars' in q or 'starship' in q):
        if 'crew' in q or 'human' in q:
            return 0.05, 0.6, "Crewed Mars mission extremely ambitious. Base rate <5% near-term."
    
    if 'openai' in q and 'public' in q:
        return 0.30, 0.4, "IPO timeline uncertain. Microsoft relationship complicates structure."
    
    # === WEATHER/CLIMATE ===
    
    if 'hottest' in q or 'temperature' in q:
        if '2025' in q:
            return 0.70, 0.5, "Climate trend favors record temperatures. Base rate ~70% for new record."
    
    # === FINANCE (no edge over markets) ===
    
    if 'recession' in q:
        if '2025' in q or '2026' in q:
            return 0.25, 0.35, "Recession probability models vary. Base rate ~25%."
    
    if 'fed' in q and 'rate' in q:
        if 'cut' in q:
            if '2025' in q:
                return 0.60, 0.4, "Fed likely to cut if inflation continues declining"
        if 'raise' in q:
            return 0.15, 0.45, "Further hikes unlikely unless inflation re-accelerates"
    
    # === DEFAULT: NO EDGE ===
    # Better to admit uncertainty than to fabricate edge
    return 0.50, 0.10, "Insufficient domain knowledge. Markets likely efficient."


def calculate_trade_edge(llm_prob: float, market_price: float, confidence: float) -> tuple[float, float, str, str]:
    """
    Calculate trade edge and expected value.
    
    Returns: (edge, ev, direction, reasoning)
    """
    edge = llm_prob - market_price
    
    # Adjust edge by confidence
    # Low confidence = edge is unreliable
    effective_edge = edge * confidence
    
    if abs(effective_edge) < 0.05:
        return 0, 0, "HOLD", "Edge below threshold"
    
    # Calculate EV (binary market, 0% fees)
    if effective_edge > 0:
        # Buy YES
        ev = effective_edge  # Simplified: edge * payout - (1-edge) * cost
        direction = "BUY YES"
    else:
        # Buy NO
        ev = abs(effective_edge)
        direction = "BUY NO"
    
    return edge, ev, direction, f"LLM: {llm_prob:.0%} vs Mkt: {market_price:.0%}"


def scan_for_edge(min_edge=0.10, min_confidence=0.4):
    """Scan markets for trading edge."""
    print("=" * 80)
    print("POLYMARKET EDGE SCANNER v2")
    print("=" * 80)
    
    # Fetch active markets
    url = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=60)
    events = json.loads(result.stdout)
    
    print(f"\nScanning {len(events)} active events...")
    
    trades = []
    skipped_no_edge = 0
    skipped_low_conf = 0
    
    for event in events:
        category = event.get('category', 'Unknown')
        
        for market in event.get('markets', []):
            question = market.get('question', '')
            if not question:
                continue
            
            # Get price
            prices_str = market.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                prices = [float(p) for p in prices]
            except:
                continue
            
            if len(prices) < 2:
                continue
            
            yes_price = prices[0]
            
            # Skip resolved markets
            if yes_price <= 0.01 or yes_price >= 0.99:
                continue
            
            # LLM assessment (BLIND)
            llm_prob, confidence, reasoning = assess_with_base_rates(question)
            
            # Calculate edge
            edge, ev, direction, _ = calculate_trade_edge(llm_prob, yes_price, confidence)
            
            if abs(edge) < 0.05:
                skipped_no_edge += 1
                continue
            
            if confidence < min_confidence:
                skipped_low_conf += 1
                continue
            
            # Qualifying trade
            trades.append(TradeSignal(
                market_slug=market.get('slug', ''),
                question=question[:150],
                category=category,
                market_price=yes_price,
                llm_probability=llm_prob,
                edge=edge,
                confidence=confidence,
                direction=direction,
                expected_value=ev,
                reasoning=reasoning[:150],
                resolution_date=market.get('endDate', ''),
            ))
    
    # Sort by EV
    trades.sort(key=lambda t: t.expected_value, reverse=True)
    
    # Results
    print(f"\nResults:")
    print(f"  Markets scanned: {sum(len(e.get('markets', [])) for e in events)}")
    print(f"  Skipped (no edge): {skipped_no_edge}")
    print(f"  Skipped (low confidence): {skipped_low_conf}")
    print(f"  Tradeable opportunities: {len(trades)}")
    
    if trades:
        print("\n" + "=" * 80)
        print("TOP TRADE OPPORTUNITIES")
        print("=" * 80)
        
        for t in trades[:15]:
            print(f"\n  [{t.direction}] {t.question[:60]}...")
            print(f"    Market: {t.market_price:.1%} | LLM: {t.llm_probability:.1%} | Edge: {t.edge:+.1%}")
            print(f"    Confidence: {t.confidence:.0%} | EV: {t.expected_value:.1%}")
            print(f"    Reasoning: {t.reasoning[:80]}...")
    
    # Summary
    buy_yes = [t for t in trades if t.direction == "BUY YES"]
    buy_no = [t for t in trades if t.direction == "BUY NO"]
    
    print("\n" + "=" * 80)
    print("EDGE SUMMARY")
    print("=" * 80)
    print(f"\nBUY YES: {len(buy_yes)} opportunities")
    print(f"BUY NO: {len(buy_no)} opportunities")
    
    if trades:
        total_ev = sum(t.expected_value for t in trades)
        print(f"\nTotal portfolio EV: {total_ev:.1%}")
        
        # Category breakdown
        categories = {}
        for t in trades:
            cat = t.category or 'Unknown'
            if cat not in categories:
                categories[cat] = {'count': 0, 'total_ev': 0}
            categories[cat]['count'] += 1
            categories[cat]['total_ev'] += t.expected_value
        
        print("\nBy Category:")
        for cat, data in sorted(categories.items(), key=lambda x: -x[1]['total_ev']):
            print(f"  {cat:20}: {data['count']:2d} trades, EV: {data['total_ev']:+.1%}")
    
    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / 'polymarket_edge_v2.json', 'w') as f:
        json.dump({
            'scan_time': datetime.now(timezone.utc).isoformat(),
            'events_scanned': len(events),
            'opportunities': len(trades),
            'trades': [asdict(t) for t in trades],
        }, f, indent=2)
    
    return trades


if __name__ == '__main__':
    scan_for_edge(min_edge=0.10, min_confidence=0.4)
