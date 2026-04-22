#!/usr/bin/env python3
"""Debug SHORT entry proximity for all below-SMA100 assets."""
import requests
import numpy as np

BINANCE = "https://api.binance.com"
SYMBOLS = {
    "ARB": "ARBUSDT", "OP": "OPUSDT", "ETH": "ETHUSDT", "APT": "APTUSDT",
    "AVAX": "AVAXUSDT", "SOL": "SOLUSDT", "LINK": "LINKUSDT",
    "DOGE": "DOGEUSDT", "LTC": "LTCUSDT", "FIL": "FILUSDT",
    "SUI": "SUIUSDT", "NEAR": "NEARUSDT", "AAVE": "AAVEUSDT",
}

DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT = 1.5  # IG88081 optimized
SMA_REGIME = 100

def fetch(asset):
    sym = SYMBOLS.get(asset, f"{asset}USDT")
    r = requests.get(f"{BINANCE}/api/v3/klines",
                     params={"symbol": sym, "interval": "1h", "limit": 200}, timeout=15)
    d = r.json()
    return [{"h": float(k[2]), "l": float(k[3]), "c": float(k[4])} for k in d]

print(f"{'Asset':>6s} {'Close':>10s} {'SMA100':>10s} {'DonLow':>10s} {'ATR':>8s} {'Trigger':>10s} {'Gap%':>7s} {'Status'}")
print("-" * 80)

for asset in sorted(SYMBOLS.keys()):
    candles = fetch(asset)
    n = len(candles)
    close = [c["c"] for c in candles]
    high = [c["h"] for c in candles]
    low = [c["l"] for c in candles]

    # ATR
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = [0] * n
    for i in range(ATR_PERIOD, n):
        atr[i] = sum(tr[i-ATR_PERIOD+1:i+1]) / ATR_PERIOD

    # Donchian
    dlow = [0] * n
    for i in range(DONCHIAN-1, n):
        dlow[i] = min(low[i-DONCHIAN+1:i+1])

    # SMA100
    sma = [0] * n
    for i in range(SMA_REGIME-1, n):
        sma[i] = sum(close[i-SMA_REGIME+1:i+1]) / SMA_REGIME

    last_close = close[-1]
    last_sma = sma[-1]
    prev_dlow = dlow[-2]
    last_atr = atr[-1]
    trigger = prev_dlow - last_atr * ATR_MULT

    below_sma = last_close < last_sma
    would_trigger = last_close < trigger
    gap_pct = (last_close - trigger) / last_close * 100

    status = "TRIGGER!" if (below_sma and would_trigger) else (
        "close" if gap_pct < 2 else "---"
    )
    regime = "S" if below_sma else "L"

    print(f"{asset:>6s} {last_close:>10.4f} {last_sma:>10.4f} {prev_dlow:>10.4f} {last_atr:>8.4f} {trigger:>10.4f} {gap_pct:>+6.1f}% {regime} {status}")
