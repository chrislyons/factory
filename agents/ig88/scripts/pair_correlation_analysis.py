"""
Pair Correlation Analysis
==========================
Determine if our 12 pairs are truly diversified or correlated.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']


def load_returns(pair):
    df = pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    # Normalize index to UTC and remove timezone
    df.index = pd.to_datetime(df.index).tz_localize(None)
    series = df['close'].pct_change()
    series.name = pair
    return series


# Load all returns and align on common dates
all_returns = {}
for pair in PAIRS:
    all_returns[pair] = load_returns(pair)

# Create DataFrame and align
returns = pd.DataFrame(all_returns)
# Drop rows where ANY pair has NaN
returns = returns.dropna()

print("=" * 80)
print("PAIR CORRELATION ANALYSIS")
print("=" * 80)
print(f"\nData: {len(returns)} bars")
print(f"Date range: {returns.index.min()} to {returns.index.max()}")


# ============================================================================
# CORRELATION MATRIX
# ============================================================================
print("\n" + "=" * 80)
print("4H RETURN CORRELATION MATRIX")
print("=" * 80)

corr = returns.corr()

# Print matrix
header = f"{'':>6}" + "".join(f"{p:>6}" for p in PAIRS)
print(f"\n{header}")
for p1 in PAIRS:
    row = f"{p1:>6}"
    for p2 in PAIRS:
        if p1 == p2:
            row += f"{'  -':>6}"
        else:
            val = corr.loc[p1, p2]
            row += f"{val:>6.2f}"
    print(row)


# ============================================================================
# TOP CORRELATED PAIRS
# ============================================================================
print("\n" + "=" * 80)
print("TOP 20 MOST CORRELATED PAIRS")
print("=" * 80)

corr_pairs = []
for i, p1 in enumerate(PAIRS):
    for j, p2 in enumerate(PAIRS):
        if i < j:
            corr_pairs.append((p1, p2, corr.loc[p1, p2]))

corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)

print(f"\n{'Rank':<6} {'Pair':<15} {'Correlation':<12} {'Risk Level'}")
print("-" * 50)
for idx, (p1, p2, c) in enumerate(corr_pairs[:20], 1):
    risk = "HIGH (>0.7)" if abs(c) > 0.7 else "MEDIUM (0.5-0.7)" if abs(c) > 0.5 else "LOW (<0.5)"
    print(f"{idx:<6} {p1}-{p2:<10} {c:>8.3f}      {risk}")


# ============================================================================
# AVERAGE CORRELATION PER PAIR
# ============================================================================
print("\n" + "=" * 80)
print("AVERAGE CORRELATION PER PAIR (sorted)")
print("=" * 80)

avg_corr = {}
for p in PAIRS:
    others = [c for c in PAIRS if c != p]
    avg_corr[p] = corr.loc[p, others].mean()

sorted_pairs = sorted(avg_corr.items(), key=lambda x: x[1], reverse=True)

print(f"\n{'Pair':<10} {'Avg Corr':<12} {'Diversification'}")
print("-" * 45)
for p, avg in sorted_pairs:
    score = (1 - avg) * 100
    bar = "█" * int(score / 5)
    print(f"{p:<10} {avg:>8.3f}      {score:>5.1f}/100 {bar}")


# ============================================================================
# CLUSTERS
# ============================================================================
print("\n" + "=" * 80)
print("CORRELATION CLUSTERS")
print("=" * 80)

# Simple clustering by correlation threshold
threshold = 0.6
print(f"\nUsing threshold: {threshold}")

clusters = []
assigned = set()

for p in PAIRS:
    if p in assigned:
        continue
    cluster = [p]
    assigned.add(p)
    
    for q in PAIRS:
        if q in assigned:
            continue
        # Check correlation with all cluster members
        avg_with_cluster = np.mean([corr.loc[p, q] for p in cluster])
        if avg_with_cluster > threshold:
            cluster.append(q)
            assigned.add(q)
    
    clusters.append(cluster)

print(f"\nFound {len(clusters)} clusters:")
for i, cluster in enumerate(clusters, 1):
    print(f"\n  Cluster {i}: {', '.join(cluster)}")
    # Intra-cluster correlation
    if len(cluster) > 1:
        intra_corrs = []
        for ii, p in enumerate(cluster):
            for j, q in enumerate(cluster):
                if ii < j:
                    intra_corrs.append(corr.loc[p, q])
        print(f"    Intra-cluster avg correlation: {np.mean(intra_corrs):.3f}")


# ============================================================================
# ROLLING CORRELATION STABILITY
# ============================================================================
print("\n" + "=" * 80)
print("ROLLING CORRELATION STABILITY (30-day windows = 180 bars)")
print("=" * 80)

key_pairs = [('SOL', 'AVAX'), ('SOL', 'NEAR'), ('LINK', 'AAVE'), ('SUI', 'OP'), ('SOL', 'SUI')]

for p1, p2 in key_pairs:
    rolling = returns[p1].rolling(180, min_periods=100).corr(returns[p2]).dropna()
    
    if len(rolling) > 0:
        print(f"\n{p1}-{p2}:")
        print(f"  Mean: {rolling.mean():.3f}, Std: {rolling.std():.3f}")
        print(f"  Range: [{rolling.min():.3f}, {rolling.max():.3f}]")
        print(f"  Stability: {'STABLE' if rolling.std() < 0.1 else 'VARIABLE' if rolling.std() < 0.2 else 'UNSTABLE'}")


# ============================================================================
# PCA
# ============================================================================
print("\n" + "=" * 80)
print("PCA: FACTOR INDEPENDENCE")
print("=" * 80)

from sklearn.decomposition import PCA

pca = PCA()
pca.fit(returns.values)

print(f"\n{'Factor':<10} {'Variance Explained':<20} {'Cumulative'}")
print("-" * 45)

cumulative = 0
for i, var in enumerate(pca.explained_variance_ratio_ * 100):
    cumulative += var
    print(f"Factor {i+1:<3} {var:>8.1f}%            {cumulative:>6.1f}%")

factor1_pct = pca.explained_variance_ratio_[0] * 100
print(f"""
INTERPRETATION:
- Factor 1 = {factor1_pct:.1f}% of variance
- {'DOMINATED by single factor (market risk)' if factor1_pct > 50 else 'Moderate factor independence'}
- 2-3 factors needed for >80% variance: {sum(pca.explained_variance_ratio_[:3]) * 100:.1f}%
""")


# ============================================================================
# RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("PORTFOLIO RECOMMENDATIONS")
print("=" * 80)

# Count high-correlation pairs
high_corr = sum(1 for _, _, c in corr_pairs if abs(c) > 0.7)
med_corr = sum(1 for _, _, c in corr_pairs if 0.5 <= abs(c) <= 0.7)
low_corr = sum(1 for _, _, c in corr_pairs if abs(c) < 0.5)

avg_all = np.mean([c for _, _, c in corr_pairs])

print(f"""
1. CORRELATION SUMMARY:
   - High (>0.7): {high_corr} pairs
   - Medium (0.5-0.7): {med_corr} pairs
   - Low (<0.5): {low_corr} pairs
   - Overall average: {avg_all:.3f}

2. DIVERSIFICATION VERDICT:
   - Crypto alts are {'HIGHLY' if avg_all > 0.6 else 'MODERATELY' if avg_all > 0.4 else 'LOWLY'} correlated
   - True diversification requires uncorrelated ALPHA, not uncorrelated assets
   - Portfolio risk is dominated by BTC/market factor ({factor1_pct:.1f}%)

3. POSITION SIZING RULES:
   - Max 2 positions from same cluster simultaneously
   - If correlation >0.7 pairs both trigger → treat as single position (split size)
   - Reduce total exposure when Factor 1 dominates (>50%)

4. BEST DIVERSIFIERS (lowest avg correlation):
   - {sorted_pairs[-1][0]}: {sorted_pairs[-1][1]:.3f}
   - {sorted_pairs[-2][0]}: {sorted_pairs[-2][1]:.3f}
   - {sorted_pairs[-3][0]}: {sorted_pairs[-3][1]:.3f}

5. WORST CONCENTRATION (highest avg correlation):
   - {sorted_pairs[0][0]}: {sorted_pairs[0][1]:.3f}
   - {sorted_pairs[1][0]}: {sorted_pairs[1][1]:.3f}
   - {sorted_pairs[2][0]}: {sorted_pairs[2][1]:.3f}
""")
