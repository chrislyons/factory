#!/usr/bin/env python3
import subprocess, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, '..', 'data', 'polymarket', 'spread_analysis.json')

os.makedirs(os.path.join(BASE, '..', 'data', 'polymarket'), exist_ok=True)

# Get active markets
r = subprocess.run(
    ['polymarket', '-o', 'json', 'markets', 'list', '--active', 'true', '--limit', '20'],
    capture_output=True, text=True, timeout=15
)
markets = json.loads(r.stdout)

print(f'Found {len(markets)} active markets')
print(f'Largest by liquidity:')

# Sort by liquidity
by_liq = sorted(markets, key=lambda m: float(m.get('liquidity', 0) or 0), reverse=True)
for m in by_liq[:5]:
    q = m.get('question', '')[:60]
    liq = float(m.get('liquidity', 0) or 0)
    cid = m.get('conditionId', '')
    print(f'  ${liq:>10,.0f} | {q}')
    print(f'             CID: {cid}')

# Get order books for top 3 markets to analyze spread structure
spread_data = []
for m in by_liq[:3]:
    cid = m.get('conditionId')
    q = m.get('question', '')[:50]
    liq = float(m.get('liquidity', 0) or 0)

    r2 = subprocess.run(
        ['polymarket', '-o', 'json', 'clob', 'book', cid],
        capture_output=True, text=True, timeout=10
    )
    try:
        book = json.loads(r2.stdout)
        yes_asks = book.get('yes', {}).get('asks', [])
        yes_bids = book.get('yes', {}).get('bids', [])
        no_asks = book.get('no', {}).get('asks', [])
        no_bids = book.get('no', {}).get('bids', [])

        best_yes_bid = float(yes_bids[0]['price']) if yes_bids else 0
        best_yes_ask = float(yes_asks[0]['price']) if yes_asks else 1
        best_no_bid = float(no_bids[0]['price']) if no_bids else 0
        best_no_ask = float(no_asks[0]['price']) if no_asks else 1

        mid_yes = (best_yes_bid + best_yes_ask) / 2
        mid_no = (best_no_bid + best_no_ask) / 2
        implied_prob = mid_yes / (mid_yes + mid_no) if (mid_yes + mid_no) > 0 else 0.5
        spread_cost = (best_yes_ask - best_yes_bid) / best_yes_ask if best_yes_ask > 0 else 0
        no_spread_cost = (best_no_ask - best_no_bid) / best_no_ask if best_no_ask > 0 else 0

        print(f'\n{q}...')
        print(f'  YES: bid={best_yes_bid:.4f} ask={best_yes_ask:.4f} spread={spread_cost*100:.2f}%')
        print(f'  NO:  bid={best_no_bid:.4f} ask={best_no_ask:.4f} spread={no_spread_cost*100:.2f}%')
        print(f'  Mid YES={mid_yes:.4f} NO={mid_no:.4f} => implied prob {implied_prob:.2%}')

        spread_data.append({
            'question': q,
            'condition_id': cid,
            'liquidity': liq,
            'yes_bid': best_yes_bid,
            'yes_ask': best_yes_ask,
            'no_bid': best_no_bid,
            'no_ask': best_no_ask,
            'mid_yes': mid_yes,
            'mid_no': mid_no,
            'implied_prob': implied_prob,
            'yes_spread_pct': round(spread_cost*100, 2),
            'no_spread_pct': round(no_spread_cost*100, 2),
        })
    except Exception as e:
        print(f'Error fetching book for {cid}: {e}')

# Save results
with open(OUT, 'w') as f:
    json.dump({'timestamp': __import__('datetime').datetime.now().isoformat(), 'markets': spread_data}, f, indent=2)
print(f'\nSaved to {OUT}')