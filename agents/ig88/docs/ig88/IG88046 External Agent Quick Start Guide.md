# IG88046: External Agent Quick Start Guide

**Author:** IG-88  
**Date:** 2026-04-14  
**Purpose:** Fast onboarding for external agents helping with trading research  
**Reading Time:** 5 minutes

---

## What IG-88 Is

An autonomous trading agent looking for profitable trading strategies. Current status: **no proven edge found**, but some candidates look promising and are being paper traded.

---

## The Problem (One Paragraph)

I tested 12 strategy types across 9 crypto pairs on 3 timeframes (350+ combinations). The best candidates show +50-65% backtest PnL over 200+ trades, but statistical tests say p≈0.15 (not proven). The edge, if real, is small (~0.3% per trade). I need help figuring out: (1) is this edge real or noise? (2) how can we make it stronger? (3) what's the right approach to prove it?

---

## Where Everything Lives

```bash
# Root directory
/Users/nesbitt/dev/factory/agents/ig88/

# Run Python with this (has dependencies):
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3

# Core backtesting framework:
src/quant/backtest_framework.py

# All test scripts:
scripts/

# Test results:
data/systematic/

# Paper trade state:
data/paper_trades/
```

---

## Quick Commands

```bash
# Run the backtester on any strategy
cd /Users/nesbitt/dev/factory/agents/ig88
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/deep_scan.py

# Run paper traders
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/paper_trade_runner.py
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/poly_paper_runner.py

# Check test results
cat data/systematic/final_validation.json | python3 -m json.tool
```

---

## What's Been Tested

| Strategy | Result |
|----------|--------|
| Donchian Breakout (20, 1H) | Best: +65% PF 1.3 but p=0.15 |
| Double MA Crossover | Tested, marginal |
| RSI Mean Reversion | Tested, marginal |
| VWAP Bounce | Tested, marginal |
| ATR Channel | Tested, marginal |
| Bollinger Bands | Tested, marginal |
| Volume Momentum | Tested, marginal |

**Full results:** `data/systematic/deep_scan_results.json`

---

## How to Run Your Own Tests

### Test a New Strategy

1. Add your strategy class to `scripts/deep_scan.py` (or create new script)
2. Import from the framework:
```python
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')
from src.quant.backtest_framework import Backtester, Strategy, Position
```

3. Implement your strategy:
```python
class MyStrategy(Strategy):
    def __init__(self, param1=10):
        super().__init__()
        self.param1 = param1
        self.my_indicator = None
    
    def init_indicators(self, data):
        self.my_indicator = self.sma(data['close'], self.param1)
    
    def should_enter(self, i, data):
        if condition:
            return Position(data['close'][i], i, 1000, leverage=1)
        return None
    
    def should_exit(self, i, data, position):
        if condition:
            return 'EXIT_REASON'
        return None
```

4. Run and check results.

### Fetch Real-Time Data
```python
import subprocess
import json
import numpy as np

def fetch_binance(symbol, interval='1h', limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    return {
        'open': np.array([float(d[1]) for d in data]),
        'high': np.array([float(d[2]) for d in data]),
        'low': np.array([float(d[3]) for d in data]),
        'close': np.array([float(d[4]) for d in data]),
        'volume': np.array([float(d[5]) for d in data]),
    }
```

---

## Key Findings So Far

1. **Simple strategies don't have strong edges.** If they did, markets would be exploited.

2. **Sample size matters.** <50 trades = unreliable. >200 trades = still not enough for 0.3% edge.

3. **Walk-forward is brutal.** Strategies that look great in-sample often fail out-of-sample.

4. **Statistical tests are conservative.** p=0.15 doesn't mean "no edge" - it means "not proven."

---

## What We Need Help With

### Priority 1: Statistical Validation
- Calculate required sample size for 80% power at p<0.05
- Is our walk-forward design appropriate?
- Are we using the right tests?

### Priority 2: Edge Enhancement
- Regime filtering: Should we only trade when ADX > X?
- Multi-indicator: Combine Donchian with RSI/volume filters?
- Parameter optimization: Is 20-period optimal?

### Priority 3: Alternative Approaches
- What strategy types inherently have larger per-trade edges?
- Are there opportunities in cross-asset or cross-timeframe signals?
- What about market microstructure approaches?

---

## Contact

- **IG-88:** Can run code, test ideas, access market data
- **Chris:** Human operator, approves live trading, answers strategic questions
- **Room:** IG-88 Training (Matrix)

---

*This is a living document. Update as you learn things.*
