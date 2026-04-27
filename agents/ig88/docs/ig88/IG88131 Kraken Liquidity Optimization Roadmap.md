# Recommended Next Steps for IG-88 Kraken Liquidity Optimization

Based on the 2-year liquidity analysis, here are prioritized action items to maximize PnL% while respecting risk limits:

## **IMMEDIATE ACTIONS (0-2 weeks)**

### **1. Add Missing High-Liquidity Quote Variants**
**Action:** Expand Kraken pair list in `config/trading.yaml` and `config/venues.yaml` to include:
- **BTC/USDT** (currently missing - $2.06B/day liquidity)
- **XRP/USD** (currently missing - $439M/day liquidity)  
- **DOGE/USD** (currently missing - $323M/day liquidity)

**Implementation:**
```yaml
# In config/trading.yaml under kraken_spot.pairs:
# Add these to the "BIG DOGS" or "BAGS" section based on Chris's preferences
- BTC/USDT   # Add alongside BTC/USD
- XRP/USD    # Add alongside XRP/USDT  
- DOGE/USD   # Add alongside DOGE/USDT
```

**Impact:** Captures ~15-20% additional liquidity in top 3 assets without increasing pair count significantly.

### **2. Update Pair Tier Classifications**
**Action:** Review and update `pair_tiers` in `config/venues.yaml`:
- Move BTC/USDT to `majors` tier (same as BTC/USD)
- Consider XRP/USD for `large_cap` tier (similar to XRP/USDT)
- Consider DOGE/USD for `large_cap` tier (similar to DOGE/USDT)

## **MEDIUM-TERM VALIDATION (2-6 weeks)**

### **3. Backtest New Pairs with Existing Strategies**
**Action:** Run validation cycle on the three new pairs using:
- Existing mean-reversion scanner (KrakenScanner)
- Current regime detection and signal generation
- Paper trading simulation for 30-60 days

**Process:**
1. Fetch 2-year OHLCV for new pairs via Kraken API
2. Run existing MR strategy parameters through backtest engine
3. Compare performance metrics (win rate, profit factor, Sharpe) against USDT pairs
4. Validate regime compatibility (ensure signals occur in RISK_ON/NEUTRAL regimes)

**Tools:** Use existing `src/quant/spot_backtest.py` and `src/scanner/kraken.py`

### **4. Optimize Position Sizing for New Pairs**
**Action:** Calculate appropriate position sizes based on:
- Volatility comparison vs. existing pairs
- Spread/taker fee analysis  
- Correlation with existing portfolio
- Max position limits from `risk.max_position_pct`

## **ONGOING OPERATIONS**

### **5. Implement Liquidity Regime Detection**
**Action:** Enhance regime assessment to include liquidity-sensitive filters:
- Volume deviation signals (current vs. 30-day average)
- Spread widening detection  
- Order book depth proxies (via trade frequency/size)

**Purpose:** Temporarily reduce size or pause trading on pairs experiencing liquidity droughts, even if regime is RISK_ON.

### **6. Monthly Liquidity Health Check**
**Action:** Automate monthly re-run of liquidity analysis to:
- Detect emerging high-volume pairs
- Identify pairs with declining liquidity (potential delisting risk)
- Update pair priority lists based on 6-month rolling volumes

**Implementation:** Add to `/scripts/scan-loop.py` as a monthly maintenance task.

## **RISK CONSIDERATIONS**

### **Liquidity-Adjusted Risk Limits**
For pairs outside the ultra-high tier:
- Consider reducing `max_position_pct` for mid-cap pairs
- Increase `min_hold_hours` to reduce churn in wider-spread pairs
- Monitor funding rates for perp-equivalent pairs (where applicable)

### **Validation Gateway**
Any new pair must pass:
1. **Liquidity threshold**: >$50M avg daily volume (to avoid slippage issues)
2. **Data quality**: Clean 2-year OHLCV with <5% missing bars
3. **Strategy compatibility**: Existing edge shows positive expectancy in backtest
4. **Chris approval**: First live trade requires manual approval per autonomy mandate

## **EXPECTED OUTCOMES**

**Short-term (1-3 months):**
- 5-15% increase in tradable opportunity set
- Better capture of BTC/ETH/SOL volatility moves via USDT pairs
- Reduced single-point failure risk (having both USD and USDT options)

**Medium-term (3-6 months):**
- Data-driven pair rotation based on liquidity regimes
- Potential discovery of new high-alpha pairs in medium-liquidity tier
- Improved portfolio diversification through broader asset coverage

**Long-term (6+ months):**
- Liquidity-aware position scaling (size inversely correlates with spread cost)
- Cross-asset liquidity correlation analysis for portfolio optimization
- Autonomous liquidity-based strategy parameter adjustment

---

**Next Immediate Step:** Execute the pair additions to config files and initiate backtest validation on the three new pairs using existing MR strategy parameters.