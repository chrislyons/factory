import json
import numpy as np

with open('/Users/nesbitt/dev/factory/agents/ig88/data/portfolio_optimization.json') as f:
    data = json.load(f)

# max drawdown per asset from validation (average across splits 2x)
dd_asset = {
    'AVAX': 0.45074011387563395,
    'ETH': 0.25666379485429913,
    'LINK': 0.3145343039553083,
    'NEAR': 0.5628321962549028,
    'SOL': 0.38635574205656537,
    'RNDR': 0.362414266679516,
    'WLD': 0.2880296126231789,
    'SUI': 0.3715623089700372,
    'FIL': 0.4443612179382494
}

# allocation strategies
allocs = data['metadata']['allocation_strategies']
# compute weighted average max drawdown for each allocation
for strat, weights in allocs.items():
    weighted_dd = sum(dd_asset[asset] * weight for asset, weight in weights.items())
    data['results'][strat]['max_drawdown_estimate'] = weighted_dd
    # also add note
    data['results'][strat]['max_drawdown_note'] = 'Weighted average of historical max drawdown from walk-forward validation (2x leverage, splits 50/50,60/40,70/30). Assumes zero correlation.'

# add overall note
data['metadata']['max_drawdown_method'] = 'Historical max drawdown from walk-forward validation, weighted by allocation.'

with open('/Users/nesbitt/dev/factory/agents/ig88/data/portfolio_optimization.json', 'w') as f:
    json.dump(data, f, indent=2)

print('Updated portfolio_optimization.json with max drawdown estimates.')
print('Equal weight:', data['results']['equal_weight_9']['max_drawdown_estimate'])
print('Top4:', data['results']['top4_by_PF']['max_drawdown_estimate'])
print('Top5:', data['results']['top5_by_PF']['max_drawdown_estimate'])