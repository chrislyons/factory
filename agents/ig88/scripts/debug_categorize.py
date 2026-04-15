#!/usr/bin/env python3

title = "Will Arsenal finish in the top 4 of the EPL 2025–26 standings?"
description = ""

text = f"{title} {description}".lower()

print(f"Text: '{text}'")
print()

# Price targets
price_keywords = ['price', 'reach', 'above', 'below', 'ath', 'all-time high', 
                  'strike', 'target price']
print("Price keywords check:")
for kw in price_keywords:
    if kw in text:
        print(f"  FOUND: '{kw}'")

# Check for specific crypto/stock tickers with price mentions
print("\nTicker check:")
tickers = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana']
for c in tickers:
    if c in text:
        print(f"  FOUND ticker: '{c}'")

# Check for price indicators
print("\nPrice indicator check:")
indicators = ['$', 'price', 'k', '000']
for p in indicators:
    if p in text:
        print(f"  FOUND indicator: '{p}'")

# Date ranges
print("\nDate range keywords check:")
date_keywords = ['when', 'date', 'by when', 'before', 'quarter', 'month',
                 'q1', 'q2', 'q3', 'q4']
for kw in date_keywords:
    if kw in text:
        print(f"  FOUND: '{kw}'")

# Has '?' check
print(f"\nHas '?': {'?' in title}")

# Numerical ranges
print("\nNumerical keywords check:")
numerical_keywords = ['how many', 'how much', 'number of', 'count', 'total',
                      'percent', 'rate', 'level', 'amount', 'gdp', 'inflation']
for kw in numerical_keywords:
    if kw in text:
        print(f"  FOUND: '{kw}'")

print("\nFinal category: yes_no")