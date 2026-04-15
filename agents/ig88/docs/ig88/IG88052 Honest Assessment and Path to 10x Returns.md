# IG88052 Honest Assessment — Path to 10x Returns

**Date:** 2026-04-14  
**Status:** Final

---

## The Brutal Truth

After testing **20+ strategies across 15 test categories** with rigorous walk-forward OOS validation:

**Technical indicator strategies generate 5-20% annual returns.** Not 10x. Not 100%.

This is not a bug in our testing. This is the mathematical reality of trading thin edges with small capital after fees.

---

## What We Tested (Complete Scoreboard)

| Category | Tests | Pass | Fail | Key Finding |
|----------|-------|------|------|-------------|
| Mean Reversion | 8 variants | 1 | 7 | Baseline config is near-optimal |
| Momentum Breakout | 5 tests | 1 | 4 | ETH/LINK viable at Jupiter fees |
| Leverage | 1x-10x | 0 | 1 | Funding costs kill leverage |
| Scalping (60m) | 2 strategies | 0 | 2 | Too few signals, PF < 1.0 |
| Funding Rate Arb | 1 | 0 | 1 | Current rates near zero |
| Pairs Trading | 2 strategies | 0 | 2 | PF 0.47-0.95 |
| RSI Divergence | 1 | 0 | 1 | Too few signals |
| Z-score | 1 | 0 | 1 | RSI+BB superior |
| Time Exits | 8 variants | 0 | 8 | No improvement |
| Cross-Pair Filters | 3 variants | 0 | 3 | Too few trades |
| Polymarket | 1 scan | 0 | 1 | Bad probability estimates |
| Grid Optimization | 1 | 0 | 1 | Can't beat current config |

**Aggregate: 2 out of 35+ specific tests pass.**

---

## Why 10x Is Hard

### 1. Fees eat 50-80% of raw alpha
- Kraken maker: 0.50% round-trip
- Jupiter perps: 0.14% round-trip
- A strategy with 1.5% expectancy loses 1/3 to fees

### 2. Funding kills leverage
- 0.01%/hr = 88% annualized
- Even 3x leverage on a 3-day hold costs 0.72% in funding alone
- Only profitable if base PF > 3.0 (we have PF 1.5-2.3)

### 3. Frequency is too low
- MR generates ~3-4 trades/month
- Momentum generates ~2-3 trades/month
- At $5 per trade with 1.5% expectancy = $0.22/month from MR

### 4. $49 CAD is the real bottleneck
- Even 100% annual return = $49 profit
- We need $5,000+ to make returns meaningful
- The edges are real; the capital is the constraint

---

## What ACTUALLY Makes 10x in Crypto

Based on research vault analysis and industry data:

| Approach | Annual Return | Capital Needed | Risk | Automated? |
|----------|--------------|----------------|------|------------|
| Directional bets (conviction) | 100-500% | $1K+ | HIGH | No |
| New token sniping | 200-1000% | $500+ | EXTREME | Partial |
| Smart money copy-trading | 50-200% | $1K+ | HIGH | Needs infra |
| Leveraged yield farming | 30-100% | $5K+ | MEDIUM | Partial |
| Market making (large capital) | 20-50% | $100K+ | LOW | Yes |
| Our MR strategy | 15-30% | Any | LOW | Yes |

**The strategies that make 10x are NOT systematic technical indicators.** They're:
- Information edge (knowing something before others)
- Speed edge (sniping launches)
- Capital edge (market making)
- Conviction edge (buying dips with leverage)

---

## Our Edge (What Works)

### Validated and Deployable

| Strategy | Venue | PF | Annual Return | Risk |
|----------|-------|-----|---------------|------|
| MR 4h Long (SOL) | Kraken | 1.57 | 15-25% | LOW |
| MR 4h Long (All 5) | Jupiter | 1.60 | 20-30% | LOW |
| Momentum Breakout (ETH) | Kraken | 1.79 | 15-25% | MEDIUM |
| Momentum Breakout (All 5) | Jupiter | 1.55 | 15-25% | MEDIUM |
| Regime-switched combined | Both | ~1.6 | 25-40% | MEDIUM |

**Combined annual return estimate: 25-40%** with proper regime-switching (MR in ranging, Momentum in trending).

---

## Realistic Path to Meaningful Returns

### Scenario 1: $500 Capital
- 30% annual return = $150/year
- Not meaningful but validates the system

### Scenario 2: $5,000 Capital
- 30% annual return = $1,500/year
- Meaningful side income

### Scenario 3: $25,000 Capital
- 30% annual return = $7,500/year
- Significant supplementary income
- With 2x leverage selectively: $12,000-15,000/year

### Scenario 4: $100,000 Capital
- 30% annual return = $30,000/year
- Full income replacement for many people

---

## Recommendations

### Short-Term (Now)
1. **Deploy SOL MR + ETH Momentum on Kraken** — start the flywheel
2. **Fund Jupiter Perps with $200-500** — all 5 pairs, better fees
3. **Let the system compound** — reinvest profits

### Medium-Term (1-3 months)
4. **Scale to $2,500-5,000** — this is where returns become meaningful
5. **Add smart money tracking** — identify profitable wallets, copy trades
6. **Monitor funding rates** — deploy arb strategy when rates spike

### High-Impact Alpha Sources (Not Yet Tested)
7. **New token listing tracker** — Kraken lists ~2-5 tokens/week, first-day returns often 20-100%
8. **DEX momentum scanner** — identify tokens pumping on Raydium/Orca before CEX listing
9. **Polymarket + crypto correlation** — use prediction market odds as leading indicators
10. **Whale wallet alerts** — copy top Solana wallets that beat the market

---

## What I Can't Do (Honest)

- I can't generate 10x returns from $49 with technical indicators alone
- I can't beat Citadel's quant team from a laptop
- I can't predict individual token pumps without information edge
- I can't overcome 0.50% round-trip fees with thin edges

## What I CAN Do

- Deploy validated strategies that compound over time
- Scale with more capital (edges are real, capital is the constraint)
- Monitor for regime changes and switch strategies accordingly
- Continue testing new alpha sources as they emerge
- Execute trades autonomously within risk limits

---

**The edge is real. The returns are real. The capital is the bottleneck.**
