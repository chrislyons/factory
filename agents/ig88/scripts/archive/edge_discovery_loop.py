#!/usr/bin/env python3
"""
EDGE DISCOVERY LOOP
====================
Comprehensive strategy testing across all venues.
Runs continuously until significant edges found.

Priority: Maximum PnL%, verified with data.
"""
import json
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import time

DATA = Path('/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery')
DATA.mkdir(exist_ok=True)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def api_get(url, timeout=30):
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except:
        return None

def fetch_binance(symbol, interval='4h', limit=500):
    """Fetch OHLCV from Binance."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        return {
            'open': [float(d[1]) for d in data],
            'high': [float(d[2]) for d in data],
            'low': [float(d[3]) for d in data],
            'close': [float(d[4]) for d in data],
            'volume': [float(d[5]) for d in data],
        }
    except:
        return None

def calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.convolve(gains, np.ones(period)/period, mode='valid')
    avg_loss = np.convolve(losses, np.ones(period)/period, mode='valid')
    
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    
    # Pad beginning
    return np.concatenate([np.full(len(closes) - len(rsi), 50), rsi])

def calc_adx(highs, lows, closes, period=14):
    """Calculate ADX (trend strength)."""
    high_diff = np.diff(highs)
    low_diff = -np.diff(lows)
    
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    
    tr = np.maximum(
        np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1])),
        np.abs(lows[1:] - closes[:-1])
    )
    
    # Wilder smoothing
    atr = np.zeros(len(tr))
    plus_di = np.zeros(len(tr))
    minus_di = np.zeros(len(tr))
    
    atr[period-1] = tr[:period].mean()
    plus_di[period-1] = plus_dm[:period].mean() / atr[period-1] * 100 if atr[period-1] > 0 else 0
    minus_di[period-1] = minus_dm[:period].mean() / atr[period-1] * 100 if atr[period-1] > 0 else 0
    
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * 13 + tr[i]) / 14
        plus_di[i] = (plus_di[i-1] * 13 + (plus_dm[i] / atr[i] * 100 if atr[i] > 0 else 0)) / 14
        minus_di[i] = (minus_di[i-1] * 13 + (minus_dm[i] / atr[i] * 100 if atr[i] > 0 else 0)) / 14
    
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10) * 100
    
    # ADX is smoothed DX
    adx = np.zeros(len(dx))
    adx[period-1] = dx[:period].mean()
    for i in range(period, len(dx)):
        adx[i] = (adx[i-1] * 13 + dx[i]) / 14
    
    return adx

# ============================================================================
# POLYMARKET STRATEGIES
# ============================================================================

def scan_polymarket_correlated_arb():
    """
    Scan for correlated market arbitrage opportunities.
    Focus on 'before X' markets where events are correlated.
    """
    print("\n" + "=" * 60)
    print("POLYMARKET: CORRELATED ARB SCAN")
    print("=" * 60)
    
    events = api_get("https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200")
    if not events:
        return []
    
    opportunities = []
    
    # Find "before X" event groups
    before_groups = defaultdict(list)
    
    for event in events:
        title = event.get('title', '')
        if 'before' in title.lower():
            # Extract the "before X" part
            for m in event.get('markets', []):
                prices_str = m.get('outcomePrices', '[]')
                try:
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    prices = [float(p) for p in prices]
                except:
                    continue
                
                if len(prices) >= 2 and 0.005 < prices[0] < 0.995:
                    # Key is the "before X" event
                    key = title
                    before_groups[key].append({
                        'question': m.get('question', ''),
                        'yes': prices[0],
                        'no': prices[1],
                        'slug': m.get('slug', ''),
                    })
    
    # Analyze each group
    for group_name, markets in before_groups.items():
        if len(markets) < 3:
            continue
        
        # Find markets where YES is overpriced
        # If the "trigger event" (e.g., GTA VI release) is far away,
        # then "X before trigger" should be priced on X's probability alone
        
        for m in markets:
            q = m['question'].lower()
            yes = m['yes']
            
            # Pattern matching for overpriced events
            overpriced = False
            base_rate = 0.5
            
            if 'bitcoin' in q and '$1m' in q:
                base_rate = 0.03
                if yes > 0.20:
                    overpriced = True
            elif 'rihanna' in q and 'album' in q:
                base_rate = 0.15
                if yes > 0.30:
                    overpriced = True
            elif 'china' in q and ('invasion' in q or 'invade' in q or 'taiwan' in q):
                base_rate = 0.05
                if yes > 0.15:
                    overpriced = True
            elif 'jesus' in q or 'christ return' in q:
                base_rate = 0.01
                if yes > 0.10:
                    overpriced = True
            elif 'trump' in q and ('out' in q or 'leav' in q or 'resign' in q):
                base_rate = 0.10
                if yes > 0.25:
                    overpriced = True
            elif 'impeach' in q:
                base_rate = 0.05
                if yes > 0.15:
                    overpriced = True
            elif 'agi' in q or 'artificial general' in q:
                base_rate = 0.08
                if yes > 0.20:
                    overpriced = True
            elif 'nuclear' in q and ('iran' in q or 'test' in q):
                base_rate = 0.10
                if yes > 0.25:
                    overpriced = True
            
            if overpriced:
                edge = yes - base_rate
                opportunities.append({
                    'venue': 'polymarket',
                    'strategy': 'correlated_arb',
                    'question': m['question'][:80],
                    'slug': m['slug'],
                    'direction': 'BUY_NO',
                    'market_yes': yes,
                    'base_rate': base_rate,
                    'edge': edge,
                    'size_usd': min(100, max(25, edge * 200)),  # Scale with edge
                })
    
    print(f"Found {len(opportunities)} correlated arb opportunities")
    for opp in sorted(opportunities, key=lambda x: -x['edge'])[:5]:
        print(f"  Edge: {opp['edge']:.1%} | {opp['question'][:50]}...")
    
    return opportunities


def scan_polymarket_momentum():
    """
    Scan for momentum/reversion opportunities on Polymarket.
    
    Theory: Binary market prices that move fast may overreact.
    """
    print("\n" + "=" * 60)
    print("POLYMARKET: MOMENTUM/REVERSION SCAN")
    print("=" * 60)
    
    events = api_get("https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100")
    if not events:
        return []
    
    opportunities = []
    
    for event in events:
        for m in event.get('markets', []):
            prices_str = m.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                prices = [float(p) for p in prices]
            except:
                continue
            
            if len(prices) < 2:
                continue
            
            yes = prices[0]
            vol = float(event.get('volume', 0))
            
            # Extreme prices with high volume = potential reversion
            if vol > 100000:  # High volume markets only
                if yes > 0.90:
                    # Near-certainty - but is it justified?
                    opportunities.append({
                        'type': 'reversion_short',
                        'question': m.get('question', '')[:60],
                        'yes': yes,
                        'volume': vol,
                    })
                elif yes < 0.05:
                    # Long shot - but could it happen?
                    opportunities.append({
                        'type': 'reversion_long',
                        'question': m.get('question', '')[:60],
                        'yes': yes,
                        'volume': vol,
                    })
    
    print(f"Found {len(opportunities)} extreme price markets")
    return opportunities


def scan_polymarket_rewards_mm():
    """
    Identify best markets for rewards program market making.
    """
    print("\n" + "=" * 60)
    print("POLYMARKET: REWARDS MM TARGETS")
    print("=" * 60)
    
    events = api_get("https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200")
    if not events:
        return []
    
    targets = []
    
    for event in events:
        vol = float(event.get('volume', 0))
        liq = float(event.get('liquidity', 0))
        
        for m in event.get('markets', []):
            prices_str = m.get('outcomePrices', '[]')
            try:
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                prices = [float(p) for p in prices]
            except:
                continue
            
            if len(prices) < 2:
                continue
            
            spread = prices[1] - prices[0]
            
            # Rewards qualification: spread < 3.5%
            if abs(spread) < 0.035 and vol > 5000:
                targets.append({
                    'question': m.get('question', '')[:60],
                    'yes': prices[0],
                    'spread': abs(spread),
                    'volume': vol,
                    'liquidity': liq,
                    'est_daily_rebate': liq * 0.001,  # 0.1%
                })
    
    # Sort by volume (more volume = more fills)
    targets.sort(key=lambda x: -x['volume'])
    
    print(f"Reward-qualified markets: {len(targets)}")
    if targets:
        total_liq = sum(t['liquidity'] for t in targets)
        print(f"Total liquidity: ${total_liq:,.0f}")
        print(f"Est daily rebate pool: ${total_liq * 0.001:,.0f}")
    
    return targets[:20]  # Top 20


# ============================================================================
# KRAKEN STRATEGIES
# ============================================================================

def test_mean_reversion_regime_aware():
    """
    Test Mean Reversion WITH regime filter.
    Only trade when ADX < 25 (ranging market).
    """
    print("\n" + "=" * 60)
    print("KRAKEN: REGIME-AWARE MEAN REVERSION")
    print("=" * 60)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'NEARUSDT']
    
    results = []
    
    for pair in pairs:
        data = fetch_binance(pair, '4h', 500)
        if not data:
            continue
        
        closes = np.array(data['close'])
        highs = np.array(data['high'])
        lows = np.array(data['low'])
        
        if len(closes) < 100:
            continue
        
        # Calculate indicators
        rsi = calc_rsi(closes, 14)
        adx = calc_adx(highs, lows, closes, 14)
        
        # Current regime
        current_adx = adx[-1] if len(adx) > 0 else 50
        current_rsi = rsi[-1] if len(rsi) > 0 else 50
        
        # Regime classification
        if current_adx < 20:
            regime = 'RANGING'
            mr_favorable = True
        elif current_adx < 25:
            regime = 'TRANSITIONAL'
            mr_favorable = False
        else:
            regime = 'TRENDING'
            mr_favorable = False
        
        # Backtest MR in RANGING regime only
        trades = []
        in_range = False
        position = None
        
        for i in range(100, min(len(closes), len(adx))):
            is_ranging = adx[i] < 20 if i < len(adx) else False
            
            if not in_range and is_ranging:
                in_range = True
            elif in_range and not is_ranging:
                in_range = False
                position = None
            
            if in_range and position is None:
                # Entry: RSI < 30
                if rsi[i] < 30:
                    position = {
                        'entry': closes[i],
                        'idx': i,
                        'stop': closes[i] * 0.97,
                        'target': closes[i] * 1.04,
                    }
            
            elif position is not None:
                exit_price = None
                
                if lows[i] <= position['stop']:
                    exit_price = position['stop']
                elif highs[i] >= position['target']:
                    exit_price = position['target']
                elif rsi[i] > 70:
                    exit_price = closes[i]
                
                if exit_price:
                    pnl = (exit_price / position['entry'] - 1) * 100
                    trades.append(pnl)
                    position = None
        
        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            
            result = {
                'pair': pair,
                'regime': regime,
                'adx': current_adx,
                'rsi': current_rsi,
                'trades': len(trades),
                'win_rate': len(wins) / len(trades) if trades else 0,
                'avg_win': np.mean(wins) if wins else 0,
                'avg_loss': np.mean(losses) if losses else 0,
                'total_pnl': sum(trades),
                'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
                'mr_favorable': mr_favorable,
            }
            results.append(result)
    
    # Display
    print(f"\n{'Pair':8} {'Regime':12} {'ADX':6} {'Trades':6} {'WR':6} {'PF':6} {'PnL':8}")
    print("-" * 60)
    
    for r in results:
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != np.inf else "INF"
        print(f"{r['pair']:8} {r['regime']:12} {r['adx']:6.1f} {r['trades']:6} {r['win_rate']:5.1%} {pf_str:6} {r['total_pnl']:+7.1f}%")
    
    # Summary
    ranging = [r for r in results if r['mr_favorable']]
    if ranging:
        avg_pf = np.mean([r['profit_factor'] for r in ranging if r['profit_factor'] != np.inf])
        print(f"\nIn RANGING regime: {len(ranging)} pairs, avg PF: {avg_pf:.2f}")
    
    return results


def test_trend_following():
    """
    Test trend following strategies (opposite of MR).
    Should work in current trending regime.
    """
    print("\n" + "=" * 60)
    print("KRAKEN: TREND FOLLOWING")
    print("=" * 60)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT']
    
    results = []
    
    for pair in pairs:
        data = fetch_binance(pair, '4h', 500)
        if not data or len(data['close']) < 100:
            continue
        
        closes = np.array(data['close'])
        highs = np.array(data['high'])
        lows = np.array(data['low'])
        
        # EMA crossover strategy
        ema_fast = np.convolve(closes, np.ones(9)/9, mode='same')
        ema_slow = np.convolve(closes, np.ones(21)/21, mode='same')
        
        rsi = calc_rsi(closes, 14)
        adx = calc_adx(highs, lows, closes, 14)
        
        trades = []
        position = None
        
        for i in range(50, min(len(closes), len(adx))):
            is_trending = adx[i] > 25 if i < len(adx) else False
            
            if position is None and is_trending:
                # Entry: EMA cross up + RSI > 50
                if ema_fast[i] > ema_slow[i] and ema_fast[i-1] <= ema_slow[i-1] and rsi[i] > 50:
                    position = {
                        'entry': closes[i],
                        'idx': i,
                        'stop': closes[i] * 0.97,
                        'trailing': closes[i] * 0.97,
                    }
            
            elif position is not None:
                # Update trailing stop
                new_trailing = highs[i] * 0.97  # 3% trailing
                position['trailing'] = max(position['trailing'], new_trailing)
                
                # Exit conditions
                exit_price = None
                
                if lows[i] <= max(position['stop'], position['trailing']):
                    exit_price = max(position['stop'], position['trailing'])
                elif ema_fast[i] < ema_slow[i]:
                    exit_price = closes[i]
                
                if exit_price:
                    pnl = (exit_price / position['entry'] - 1) * 100
                    trades.append(pnl)
                    position = None
        
        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            
            result = {
                'pair': pair,
                'trades': len(trades),
                'win_rate': len(wins) / len(trades) if trades else 0,
                'avg_win': np.mean(wins) if wins else 0,
                'avg_loss': np.mean(losses) if losses else 0,
                'total_pnl': sum(trades),
                'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
            }
            results.append(result)
    
    # Display
    print(f"\n{'Pair':8} {'Trades':6} {'WR':6} {'PF':6} {'PnL':8}")
    print("-" * 40)
    
    for r in results:
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != np.inf else "INF"
        print(f"{r['pair']:8} {r['trades']:6} {r['win_rate']:5.1%} {pf_str:6} {r['total_pnl']:+7.1f}%")
    
    return results


# ============================================================================
# JUPITER PERPS STRATEGIES
# ============================================================================

def test_jupiter_h3b_current():
    """
    Test H3B Volume Ignition on current data.
    """
    print("\n" + "=" * 60)
    print("JUPITER: H3B VOLUME IGNITION (CURRENT)")
    print("=" * 60)
    
    # Same as Kraken but with leverage simulation
    pairs = ['SOLUSDT', 'AVAXUSDT', 'ETHUSDT', 'NEARUSDT', 'LINKUSDT']
    leverage = 3
    
    results = []
    
    for pair in pairs:
        data = fetch_binance(pair, '4h', 500)
        if not data or len(data['close']) < 100:
            continue
        
        closes = np.array(data['close'])
        volumes = np.array(data['volume'])
        highs = np.array(data['high'])
        lows = np.array(data['low'])
        
        # H3B indicators
        rsi = calc_rsi(closes, 14)
        vol_ma = np.convolve(volumes, np.ones(20)/20, mode='same')
        vol_spike = volumes > (vol_ma * 1.5)
        
        ema_fast = np.convolve(closes, np.ones(9)/9, mode='same')
        ema_slow = np.convolve(closes, np.ones(21)/21, mode='same')
        
        trades = []
        position = None
        trailing_stop = None
        
        for i in range(50, len(closes)):
            if position is None:
                # Entry: RSI crosses 30 up + volume spike + EMA bullish
                rsi_cross = rsi[i-1] < 30 and rsi[i] >= 30
                ema_bull = ema_fast[i] > ema_slow[i]
                
                if rsi_cross and vol_spike[i] and ema_bull:
                    position = {'entry': closes[i], 'idx': i}
                    trailing_stop = closes[i] * 0.96
            
            elif position is not None:
                # Update trailing stop
                new_stop = highs[i] * 0.96
                trailing_stop = max(trailing_stop, new_stop)
                
                # Exit
                if lows[i] <= trailing_stop:
                    pnl = (trailing_stop / position['entry'] - 1) * 100 * leverage
                    trades.append(pnl)
                    position = None
                    trailing_stop = None
                elif rsi[i] > 70:
                    pnl = (closes[i] / position['entry'] - 1) * 100 * leverage
                    trades.append(pnl)
                    position = None
                    trailing_stop = None
        
        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            
            result = {
                'pair': pair,
                'leverage': leverage,
                'trades': len(trades),
                'win_rate': len(wins) / len(trades) if trades else 0,
                'total_pnl': sum(trades),
                'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
            }
            results.append(result)
            print(f"  {pair}: {len(trades)} trades, WR={result['win_rate']:.0%}, PF={result['profit_factor']:.2f}, PnL={result['total_pnl']:+.1f}%")
    
    return results


# ============================================================================
# MAIN EXECUTION LOOP
# ============================================================================

def run_comprehensive_scan():
    """Run all strategy scans and aggregate results."""
    timestamp = datetime.now(timezone.utc).isoformat()
    
    print("=" * 80)
    print(f"EDGE DISCOVERY SCAN - {timestamp}")
    print("=" * 80)
    
    all_opportunities = []
    
    # Polymarket
    poly_arb = scan_polymarket_correlated_arb()
    all_opportunities.extend(poly_arb)
    
    poly_mom = scan_polymarket_momentum()
    poly_mm = scan_polymarket_rewards_mm()
    
    # Kraken
    kraken_mr = test_mean_reversion_regime_aware()
    kraken_tf = test_trend_following()
    
    # Jupiter
    jupiter_h3b = test_jupiter_h3b_current()
    
    # Aggregate results
    results = {
        'timestamp': timestamp,
        'polymarket': {
            'correlated_arb_count': len(poly_arb),
            'momentum_count': len(poly_mom),
            'rewards_mm_targets': len(poly_mm),
            'top_arbs': sorted(poly_arb, key=lambda x: -x['edge'])[:10],
        },
        'kraken': {
            'mr_results': kraken_mr,
            'tf_results': kraken_tf,
        },
        'jupiter': {
            'h3b_results': jupiter_h3b,
        },
        'all_opportunities': all_opportunities,
    }
    
    # Save
    with open(DATA / f'scan_{datetime.now().strftime("%Y%m%d_%H%M")}.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Summary
    print("\n" + "=" * 80)
    print("EDGE DISCOVERY SUMMARY")
    print("=" * 80)
    
    print(f"\nPOLYMARKET:")
    print(f"  Correlated arbs: {len(poly_arb)}")
    print(f"  Momentum signals: {len(poly_mom)}")
    print(f"  Rewards MM targets: {len(poly_mm)}")
    
    print(f"\nKRAKEN:")
    ranging_mr = [r for r in kraken_mr if r.get('mr_favorable')]
    print(f"  MR in ranging regime: {len(ranging_mr)} pairs")
    print(f"  TF results: {len(kraken_tf)} pairs tested")
    
    print(f"\nJUPITER:")
    print(f"  H3B tested: {len(jupiter_h3b)} pairs")
    
    print(f"\nTOTAL TRADEABLE OPPORTUNITIES: {len(all_opportunities)}")
    
    # Top edges
    if all_opportunities:
        print("\nTOP EDGES:")
        for opp in sorted(all_opportunities, key=lambda x: -x['edge'])[:5]:
            print(f"  {opp.get('venue', '?'):12} | Edge: {opp.get('edge', 0):.1%} | {opp.get('question', '')[:45]}...")
    
    return results


if __name__ == '__main__':
    results = run_comprehensive_scan()
