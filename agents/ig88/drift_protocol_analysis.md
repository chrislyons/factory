# Drift Protocol Analysis - Alternative to Jupiter Perps

## Executive Summary

Drift Protocol is a Solana-based perpetual futures DEX that offers significantly lower trading fees than Jupiter Perps. However, **Drift is NOT accessible from Ontario, Canada** due to explicit geo-restrictions in their Terms of Use.

## 1. Ontario Accessibility: NO

**Status: BLOCKED**

According to Drift's Terms of Use (Section 3.1.4), Canada is explicitly listed as a Restricted Territory:

> "you are not a resident, national, or agent of, or incorporated in, and do not have a registered office in Antigua and Barbuda, Algeria, Bangladesh, Bolivia, Belarus, Burundi, **Canada**, Cote D'Ivoire (Ivory Coast), Cuba..."

The Terms also explicitly prohibit using VPNs or other circumvention methods:
> "USE OF A VIRTUAL PRIVATE NETWORK ("VPN") OR ANY OTHER SIMILAR MEANS INTENDED TO CIRCUMVENT THE RESTRICTIONS SET FORTH HEREIN IS PROHIBITED."

**Conclusion: Drift Protocol cannot be legally used from Ontario, Canada.**

## 2. Fee Comparison: Drift vs Jupiter Perps

### Drift Protocol Fee Structure (Perp Markets)

| Tier | 30-Day Volume | Rookie Taker | Rookie Maker | Champion Taker | Champion Maker |
|------|---------------|--------------|--------------|----------------|----------------|
| 1    | ≤ $2M         | 0.0350%      | -0.0025%     | 0.0210%        | -0.0035%       |
| 2    | > $2M         | 0.0300%      | -0.0025%     | 0.0180%        | -0.0035%       |
| 3    | > $10M        | 0.0275%      | -0.0025%     | 0.0165%        | -0.0035%       |
| 4    | > $20M        | 0.0250%      | -0.0025%     | 0.0150%        | -0.0035%       |
| 5    | > $80M        | 0.0225%      | -0.0025%     | 0.0135%        | -0.0035%       |
| VIP  | > $200M       | 0.0200%      | -0.0025%     | 0.0120%        | -0.0035%       |

### DRIFT Staking Benefits (Additional Discounts)

| Staking Tier | DRIFT Staked | Taker Fee Discount | Maker Fee Rebate |
|--------------|--------------|-------------------|------------------|
| Rookie       | 0            | 0%                | 0%               |
| Kickstarter  | 1,000        | -5%               | +5%              |
| Racer        | 10,000       | -10%              | +10%             |
| Elite        | 50,000       | -20%              | +20%             |
| Master       | 100,000      | -30%              | +30%             |
| Champion     | 250,000      | -40%              | +40%             |

### Jupiter Perps Fee Structure
- Taker Fee: ~0.14% round-trip (0.07% per side)
- Maker Fee: 0% (no rebate)

### Fee Comparison Summary

| Metric | Drift Protocol (Tier 1) | Jupiter Perps | Advantage |
|--------|------------------------|---------------|-----------|
| Taker Fee (RT) | 0.070% | 0.140% | Drift (50% cheaper) |
| Maker Fee (RT) | -0.005% (rebate) | 0% | Drift (earns rebate) |
| With Staking | 0.063% RT (10% discount) | 0.140% | Drift (55% cheaper) |

**If accessible, Drift would offer ~50% lower trading friction than Jupiter Perps.**

## 3. Supported Assets

Based on Drift's documentation and API structure, they support various perpetual futures markets on Solana. The exact asset list isn't specified in the documentation reviewed, but as a major Solana DEX, they likely support:

- Major crypto assets: SOL, BTC, ETH
- Various altcoins (specific list not confirmed)

**Note**: The specific assets requested (ETH, AVAX, SOL, LINK, NEAR, FIL, SUI, WLD, RNDR) would need to be verified against their live markets. As a Solana-based platform, cross-chain assets would be wrapped versions.

## 4. API Availability

### Data API
- **Endpoint**: `https://data.api.drift.trade`
- **Documentation**: OpenAPI spec available
- **Playground**: Available at their developer docs

### Drift SDK
- Full TypeScript SDK available
- Supports: market data, orders, positions, PnL, events, swaps
- Trading automation documentation exists

### API Features
- Real-time and historical protocol data
- No need to index the chain yourself
- OpenAPI compliant

## 5. Recommendation

**DO NOT USE DRIFT PROTOCOL FROM ONTARIO, CANADA**

Despite Drift's superior fee structure (50% cheaper than Jupiter Perps), the platform explicitly prohibits Canadian users in their Terms of Use. Using Drift from Ontario would violate their terms and potentially expose users to legal risk.

### Alternative Considerations
1. **Continue with Jupiter Perps**: While fees are higher (0.14% RT vs 0.07% RT), it's legally accessible
2. **Explore other DEXs**: Investigate other perpetual DEXs that may not have Canadian restrictions
3. **Wait for regulatory changes**: Monitor if Drift updates their geo-restrictions

## Summary Table

| Factor | Drift Protocol | Jupiter Perps | Winner |
|--------|---------------|---------------|--------|
| Ontario Access | ❌ NO (Restricted) | ✅ YES | Jupiter |
| Taker Fee (RT) | 0.07% | 0.14% | Drift |
| Maker Rebate | Yes (-0.005%) | No | Drift |
| Fee Discounts | Up to 40% with staking | None | Drift |
| API Quality | Excellent (OpenAPI) | Good | Drift |
| Solana Native | Yes | Yes | Tie |

**Final Verdict**: Drift offers better fees but is inaccessible from Ontario. Jupiter Perps remains the viable choice for Ontario-based trading.