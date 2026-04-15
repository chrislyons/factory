"""
Test Jupiter Perps: Different Market Structure?
================================================
Perps might have different characteristics:
- Different liquidity
- Different volatility patterns
- Funding rates affect price action
- 24/7 trading without gaps
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Check what perp data we have
print("CHECKING AVAILABLE PERP DATA:")
print("=" * 60)

perp_files = list(DATA_DIR.glob('*perp*')) + list(DATA_DIR.glob('*PERP*'))
print(f"Perp files found: {len(perp_files)}")
for f in perp_files[:10]:
    print(f"  {f.name}")

# Also check for Jupiter data
jupiter_files = list(DATA_DIR.glob('*jupiter*')) + list(DATA_DIR.glob('*JUPITER*'))
print(f"\nJupiter files found: {len(jupiter_files)}")
for f in jupiter_files[:10]:
    print(f"  {f.name}")

# Check what data types we have
print(f"\nALL DATA FILES:")
all_files = list(DATA_DIR.glob('*.parquet'))
by_type = {}
for f in all_files:
    # Categorize by naming pattern
    name = f.name
    if 'perp' in name.lower():
        cat = 'perp'
    elif '60m' in name:
        cat = '60m'
    elif '240m' in name:
        cat = '4h'
    elif '1440m' in name:
        cat = '1d'
    elif '15m' in name:
        cat = '15m'
    elif '120m' in name:
        cat = '2h'
    else:
        cat = 'other'
    by_type[cat] = by_type.get(cat, 0) + 1

print(f"\nBy timeframe/type:")
for cat, count in sorted(by_type.items()):
    print(f"  {cat}: {count} files")

# Test the perp data if we have any
print(f"\n{'=' * 60}")
print("TESTING PERP DATA IF AVAILABLE")
print("=" * 60)

if perp_files:
    for f in perp_files[:5]:
        try:
            df = pd.read_parquet(f)
            print(f"\n{f.name}:")
            print(f"  Shape: {df.shape}")
            print(f"  Columns: {list(df.columns)[:6]}...")
            print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        except Exception as e:
            print(f"  Error: {e}")
else:
    print("No perp data available.")
    print("\nTo test perps, we need to fetch Jupiter/Solana perp data.")
    print("This would require integrating with Jupiter's API.")
