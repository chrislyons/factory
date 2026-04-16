#!/usr/bin/env python3
"""
Regime Assessment & Edge Readiness Report for Portfolio v5
"""
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timezone

def fetch_binance_4h(pair: str, limit: int = 500) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": pair, "interval": "4h", "limit": limit}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df.set_index('open_time')[['open', 'high', 'low', 'close', 'volume']]

def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:]-low[1:], np.maximum(np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(period).mean().values

def compute_adx(high, low, close, period=14):
    atr = compute_atr(high, low, close, period)
    plus_dm = np.where((high[1:]-high[:-1])>(low[:-1]-low[1:]), np.maximum(high[1:]-high[:-1],0),0)
    plus_dm = np.concatenate([[0], plus_dm])
    minus_dm = np.where((low[:-1]-low[1:])>(high[1:]-high[:-1]), np.maximum(low[:-1]-low[1:],0),0)
    minus_dm = np.concatenate([[0], minus_dm])
    plus_di = 100*pd.Series(plus_dm).rolling(period).mean().values/np.where(atr>0,atr,1)
    minus_di = 100*pd.Series(minus_dm).rolling(period).mean().values/np.where(atr>0,atr,1)
    dx = 100*np.abs(plus_di-minus_di)/np.where(plus_di+minus_di>0,plus_di+minus_di,1)
    return pd.Series(dx).rolling(period).mean().values

def main():
    print("=" * 65)
    print("REGIME ASSESSMENT & EDGE READINESS — Portfolio v5")
    print(f"Timestamp: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 65)

    # Fetch data
    print("\nFetching ETHUSDT 4h (500 bars)...")
    eth_df = fetch_binance_4h("ETHUSDT", 500)
    print(f"Fetching LINKUSDT 4h (500 bars)...")
    link_df = fetch_binance_4h("LINKUSDT", 500)

    close_e = eth_df['close'].values
    high_e = eth_df['high'].values
    low_e = eth_df['low'].values
    vol_e = eth_df['volume'].values

    close_l = link_df['close'].values
    high_l = link_df['high'].values
    low_l = link_df['low'].values
    vol_l = link_df['volume'].values

    # Indicators for ETH
    atr_e = compute_atr(high_e, low_e, close_e)
    adx_e = compute_adx(high_e, low_e, close_e)
    ema20_e = pd.Series(close_e).ewm(span=20, adjust=False).mean().values
    ema50_e = pd.Series(close_e).ewm(span=50, adjust=False).mean().values
    sma20_e = pd.Series(close_e).rolling(20).mean().values
    atr_sma50_e = pd.Series(atr_e).rolling(50).mean().values
    vol_sma20_e = pd.Series(vol_e).rolling(20).mean().values
    keltner_e = ema20_e + 2 * atr_e

    # MACD
    ema12 = pd.Series(close_e).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close_e).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    signal_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - signal_line

    # Indicators for LINK
    atr_l = compute_atr(high_l, low_l, close_l)
    ema20_l = pd.Series(close_l).ewm(span=20, adjust=False).mean().values
    keltner_l = ema20_l + 2 * atr_l
    vol_sma20_l = pd.Series(vol_l).rolling(20).mean().values

    i = len(close_e) - 2  # signal bar (second to last)

    # ---- CURRENT SNAPSHOT ----
    print("\n" + "-" * 65)
    print("1. CURRENT MARKET SNAPSHOT")
    print("-" * 65)
    eth_price = close_e[-1]
    link_price = close_l[-1]
    print(f"ETH Price:    ${eth_price:.2f}")
    print(f"LINK Price:   ${link_price:.2f}")
    print(f"Current ADX:  {adx_e[i]:.1f}")
    print(f"Current ATR:  {atr_e[i]:.4f} ({atr_e[i]/eth_price*100:.3f}%)")
    print(f"ATR SMA(50):  {atr_sma50_e[i]:.4f} ({atr_sma50_e[i]/eth_price*100:.3f}%)")
    print(f"ATR Ratio:    {atr_e[i]/atr_sma50_e[i]:.2f}x")
    print(f"EMA20:        ${ema20_e[i]:.2f}  |  SMA20: ${sma20_e[i]:.2f}")
    print(f"EMA50:        ${ema50_e[i]:.2f}")
    print(f"Keltner Up:   ${keltner_e[i]:.2f}")
    print(f"Vol SMA(20):  {vol_sma20_e[i]:.2f}")
    print(f"Current Vol:  {vol_e[i]:.2f}  (ratio: {vol_e[i]/vol_sma20_e[i]:.2f}x)")
    print(f"MACD Hist:    {hist[i]:.4f}  (prev: {hist[i-1]:.4f})")
    dow = eth_df.index[i].weekday()
    day_of_month = eth_df.index[i].day
    print(f"Day of week:  {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][dow]}")
    print(f"Day of month: {day_of_month}")

    # ---- BREAKOUT FREQUENCY (30 days = ~180 bars of 4h) ----
    print("\n" + "-" * 65)
    print("2. BREAKOUT FREQUENCY (last 30 days / ~180 bars)")
    print("-" * 65)
    lookback = min(180, i)
    start_idx = i - lookback + 1

    # Volume breakout bars
    vol_breakouts = sum(1 for j in range(start_idx, i+1) if vol_e[j] > 1.5 * vol_sma20_e[j])
    atr_breakouts = sum(1 for j in range(start_idx, i+1) if atr_e[j] > 1.5 * atr_sma50_e[j])
    close_above_sma = sum(1 for j in range(start_idx, i+1) if close_e[j] > sma20_e[j])
    close_above_keltner = sum(1 for j in range(start_idx, i+1) if close_e[j] > keltner_e[j])
    adx_above_25 = sum(1 for j in range(start_idx, i+1) if adx_e[j] > 25)
    macd_cross_up = sum(1 for j in range(start_idx+1, i+1) if hist[j] > 0 and hist[j-1] <= 0)

    print(f"Bars with Vol > 1.5x SMA(20):       {vol_breakouts}/{lookback} ({vol_breakouts/lookback*100:.1f}%)")
    print(f"Bars with ATR > 1.5x ATR_SMA(50):    {atr_breakouts}/{lookback} ({atr_breakouts/lookback*100:.1f}%)")
    print(f"Bars with Close > SMA(20):           {close_above_sma}/{lookback} ({close_above_sma/lookback*100:.1f}%)")
    print(f"Bars with Close > Keltner Upper:     {close_above_keltner}/{lookback} ({close_above_keltner/lookback*100:.1f}%)")
    print(f"Bars with ADX > 25:                  {adx_above_25}/{lookback} ({adx_above_25/lookback*100:.1f}%)")
    print(f"MACD Hist Cross Up:                  {macd_cross_up}/{lookback}")

    # ---- ATR REGIME ----
    print("\n" + "-" * 65)
    print("3. VOLATILITY REGIME (ATR% percentiles)")
    print("-" * 65)
    atr_pct_series = atr_e[start_idx:i+1] / close_e[start_idx:i+1] * 100
    print(f"Current ATR%: {atr_e[i]/close_e[i]*100:.3f}%")
    print(f"30d Mean ATR%: {np.mean(atr_pct_series):.3f}%")
    print(f"30d P25 ATR%: {np.percentile(atr_pct_series, 25):.3f}%")
    print(f"30d P50 ATR%: {np.percentile(atr_pct_series, 50):.3f}%")
    print(f"30d P75 ATR%: {np.percentile(atr_pct_series, 75):.3f}%")
    if atr_e[i]/close_e[i]*100 < np.percentile(atr_pct_series, 25):
        vol_regime = "VERY LOW"
    elif atr_e[i]/close_e[i]*100 < np.percentile(atr_pct_series, 50):
        vol_regime = "LOW"
    elif atr_e[i]/close_e[i]*100 < np.percentile(atr_pct_series, 75):
        vol_regime = "MODERATE"
    else:
        vol_regime = "HIGH"
    print(f"Vol Regime Classification: {vol_regime}")

    # ---- EDGE READINESS SCORING ----
    print("\n" + "-" * 65)
    print("4. EDGE READINESS SCORES (0-100)")
    print("-" * 65)

    # Edge 1: ETH Thu/Fri Keltner
    # Needs: dow in [3,4], close>keltner, vol>1.5x, ADX>25
    e1_dow_ok = dow in [3, 4]
    e1_close_ok = close_e[i] > keltner_e[i]
    e1_vol_ok = vol_e[i] > 1.5 * vol_sma20_e[i]
    e1_adx_ok = adx_e[i] > 25
    e1_score = 0
    e1_conditions = []
    if e1_dow_ok: e1_score += 35; e1_conditions.append("Thu/Fri OK")
    else: e1_conditions.append(f"Not Thu/Fri (is {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][dow]})")
    if e1_close_ok: e1_score += 25; e1_conditions.append("Close>Keltner OK")
    else: e1_conditions.append(f"Close ${close_e[i]:.2f} < Keltner ${keltner_e[i]:.2f}")
    if e1_vol_ok: e1_score += 20; e1_conditions.append("Vol>1.5x OK")
    else: e1_conditions.append(f"Vol {vol_e[i]/vol_sma20_e[i]:.2f}x < 1.5x")
    if e1_adx_ok: e1_score += 20; e1_conditions.append("ADX>25 OK")
    else: e1_conditions.append(f"ADX {adx_e[i]:.1f} < 25")

    print(f"\nEdge 1 — ETH Thu/Fri Keltner:    {e1_score}/100")
    for c in e1_conditions:
        status = "OK" if ">" in c and "OK" in c else ("OK" if c.endswith("OK") else "MISS")
        print(f"  [{'+' if status=='OK' else '-'}] {c}")

    # Edge 2: ETH Vol Breakout
    # Needs: ATR>1.5x ATR_SMA50, close>SMA20, vol>1.5x
    e2_atr_ok = atr_e[i] > 1.5 * atr_sma50_e[i]
    e2_close_ok = close_e[i] > sma20_e[i]
    e2_vol_ok = vol_e[i] > 1.5 * vol_sma20_e[i]
    e2_score = 0
    e2_conditions = []
    if e2_atr_ok: e2_score += 40; e2_conditions.append("ATR>1.5x SMA50 OK")
    else: e2_conditions.append(f"ATR {atr_e[i]/atr_sma50_e[i]:.2f}x < 1.5x")
    if e2_close_ok: e2_score += 30; e2_conditions.append("Close>SMA20 OK")
    else: e2_conditions.append(f"Close ${close_e[i]:.2f} < SMA20 ${sma20_e[i]:.2f}")
    if e2_vol_ok: e2_score += 30; e2_conditions.append("Vol>1.5x OK")
    else: e2_conditions.append(f"Vol {vol_e[i]/vol_sma20_e[i]:.2f}x < 1.5x")

    print(f"\nEdge 2 — ETH Vol Breakout:       {e2_score}/100")
    for c in e2_conditions:
        status = "OK" if "OK" in c else "MISS"
        print(f"  [{'+' if status=='OK' else '-'}] {c}")

    # Edge 3: LINK Thu/Fri Keltner
    e3_dow_ok = dow in [3, 4]
    e3_close_ok = close_l[i] > keltner_l[i]
    e3_vol_ok = vol_l[i] > 1.5 * vol_sma20_l[i]
    e3_score = 0
    e3_conditions = []
    if e3_dow_ok: e3_score += 40; e3_conditions.append("Thu/Fri OK")
    else: e3_conditions.append(f"Not Thu/Fri (is {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][dow]})")
    if e3_close_ok: e3_score += 30; e3_conditions.append("Close>Keltner OK")
    else: e3_conditions.append(f"Close ${close_l[i]:.2f} < Keltner ${keltner_l[i]:.2f}")
    if e3_vol_ok: e3_score += 30; e3_conditions.append("Vol>1.5x OK")
    else: e3_conditions.append(f"Vol {vol_l[i]/vol_sma20_l[i]:.2f}x < 1.5x")

    print(f"\nEdge 3 — LINK Thu/Fri Keltner:   {e3_score}/100")
    for c in e3_conditions:
        status = "OK" if "OK" in c else "MISS"
        print(f"  [{'+' if status=='OK' else '-'}] {c}")

    # Edge 4: ETH Week 2 Keltner
    e4_day_ok = 8 <= day_of_month <= 14
    e4_not_thufri = dow not in [3, 4]
    e4_close_ok = close_e[i] > keltner_e[i]
    e4_vol_ok = vol_e[i] > 1.5 * vol_sma20_e[i]
    e4_score = 0
    e4_conditions = []
    if e4_day_ok: e4_score += 35; e4_conditions.append("Day 8-14 OK")
    else: e4_conditions.append(f"Day {day_of_month} not in 8-14")
    if e4_not_thufri: e4_score += 10; e4_conditions.append("Not Thu/Fri OK")
    else: e4_conditions.append(f"Is Thu/Fri (excluded)")
    if e4_close_ok: e4_score += 30; e4_conditions.append("Close>Keltner OK")
    else: e4_conditions.append(f"Close ${close_e[i]:.2f} < Keltner ${keltner_e[i]:.2f}")
    if e4_vol_ok: e4_score += 25; e4_conditions.append("Vol>1.5x OK")
    else: e4_conditions.append(f"Vol {vol_e[i]/vol_sma20_e[i]:.2f}x < 1.5x")

    print(f"\nEdge 4 — ETH Week 2 Keltner:     {e4_score}/100")
    for c in e4_conditions:
        status = "OK" if "OK" in c else "MISS"
        print(f"  [{'+' if status=='OK' else '-'}] {c}")

    # Edge 5: ETH MACD Hist Cross
    e5_cross_ok = hist[i] > 0 and hist[i-1] <= 0
    e5_close_ok = close_e[i] > ema50_e[i]
    e5_vol_ok = vol_e[i] > 1.2 * vol_sma20_e[i]
    e5_score = 0
    e5_conditions = []
    if e5_cross_ok: e5_score += 40; e5_conditions.append("MACD Hist cross UP OK")
    else: 
        if hist[i] > 0 and hist[i-1] > 0:
            e5_conditions.append(f"MACD Hist already positive ({hist[i]:.4f}), no cross")
        elif hist[i] <= 0:
            e5_conditions.append(f"MACD Hist negative ({hist[i]:.4f}), no cross")
    if e5_close_ok: e5_score += 30; e5_conditions.append("Close>EMA50 OK")
    else: e5_conditions.append(f"Close ${close_e[i]:.2f} < EMA50 ${ema50_e[i]:.2f}")
    if e5_vol_ok: e5_score += 30; e5_conditions.append("Vol>1.2x OK")
    else: e5_conditions.append(f"Vol {vol_e[i]/vol_sma20_e[i]:.2f}x < 1.2x")

    print(f"\nEdge 5 — ETH MACD Hist Cross:    {e5_score}/100")
    for c in e5_conditions:
        status = "OK" if "OK" in c else "MISS"
        print(f"  [{'+' if status=='OK' else '-'}] {c}")

    # ---- REGIME ASSESSMENT ----
    print("\n" + "-" * 65)
    print("5. REGIME ASSESSMENT")
    print("-" * 65)

    # Breakout strategies need: expanding volatility, volume surges, trend confirmation
    vol_favorable = atr_e[i] > atr_sma50_e[i] * 0.9  # at least 90% of avg ATR
    vol_expanding = atr_e[i] > atr_sma50_e[i]
    trend_ok = close_e[i] > sma20_e[i] or close_e[i] > ema20_e[i]
    adx_trending = adx_e[i] > 20

    print(f"Volatility favorable (ATR > 0.9x avg):  {'YES' if vol_favorable else 'NO'}")
    print(f"Volatility expanding (ATR > avg):        {'YES' if vol_expanding else 'NO'}")
    print(f"Trend confirmation (close > MA):         {'YES' if trend_ok else 'NO'}")
    print(f"ADX shows trending (ADX > 20):           {'YES' if adx_trending else 'NO'}")

    regime_score = sum([vol_favorable, vol_expanding, trend_ok, adx_trending])
    if regime_score >= 3:
        regime_verdict = "FAVORABLE for breakout strategies"
    elif regime_score >= 2:
        regime_verdict = "MIXED — some conditions met, proceed with caution"
    else:
        regime_verdict = "UNFAVORABLE for breakout strategies — low vol, range-bound"

    print(f"\nRegime Verdict: {regime_verdict} (score: {regime_score}/4)")
    print(f"  Current: NEUTRAL direction, {vol_regime} volatility")
    print(f"  ADX {adx_e[i]:.1f} suggests {'trending' if adx_e[i]>25 else 'weak trend' if adx_e[i]>20 else 'range-bound/ranging'} market")

    # ---- SUMMARY ----
    print("\n" + "=" * 65)
    print("EDGE READINESS RANKING (most likely to fire next)")
    print("=" * 65)
    edges = [
        ("Edge 5 — ETH MACD Hist Cross", e5_score, e5_conditions),
        ("Edge 4 — ETH Week 2 Keltner", e4_score, e4_conditions),
        ("Edge 2 — ETH Vol Breakout", e2_score, e2_conditions),
        ("Edge 1 — ETH Thu/Fri Keltner", e1_score, e1_conditions),
        ("Edge 3 — LINK Thu/Fri Keltner", e3_score, e3_conditions),
    ]
    edges.sort(key=lambda x: x[1], reverse=True)
    for rank, (name, score, conds) in enumerate(edges, 1):
        missing = [c for c in conds if "OK" not in c]
        print(f"\n{rank}. {name}: {score}/100")
        if missing:
            print(f"   Blocking: {'; '.join(missing)}")

    print("\n" + "=" * 65)
    print("BOTTOM LINE")
    print("=" * 65)
    print(f"""
The current regime is {vol_regime} volatility (ATR% {atr_e[i]/close_e[i]*100:.3f}%).
ADX at {adx_e[i]:.1f} indicates {'trending' if adx_e[i]>25 else 'weak/mixed'} conditions.

All 5 edges are BREAKOUT strategies requiring:
- Volume expansion (>1.5x avg)
- Volatility expansion (ATR spike or Keltner breach)
- Trend confirmation

Current conditions show volume ratio at {vol_e[i]/vol_sma20_e[i]:.2f}x and
ATR ratio at {atr_e[i]/atr_sma50_e[i]:.2f}x — {'EXPANSION' if atr_e[i]/atr_sma50_e[i]>1.3 else 'NORMAL' if atr_e[i]/atr_sma50_e[i]>0.9 else 'COMPRESSION'}.

Most likely edge to fire: {edges[0][0]}
Next trigger window: {edges[0][1]}% conditions met.
""")

if __name__ == "__main__":
    main()
