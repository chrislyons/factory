#!/usr/bin/env python3
"""
CHOP Regime Strategy Development

Two approaches tested:
1. Bollinger Band Mean Reversion (buy lower band, sell upper band)
2. Volatility Squeeze Breakout (BB inside Keltner → explosion)

Both tested ONLY during CHOP regime (BTC SMA50/200 = CHOP).
Compared against ATR BO performance in CHOP.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

ATR_PERIOD = 10
FRICTION = 0.0014

# BB MR params
BB_PERIOD = 20
BB_STD = 2.0
MR_TRAIL = 0.02
MR_MAX_HOLD = 48

# Squeeze params
SQZ_BB_PERIOD = 20
SQZ_BB_STD = 1.5
SQZ_KC_PERIOD = 20
SQZ_KC_ATR_MULT = 1.5
SQZ_MAX_HOLD = 72
SQZ_TRAIL = 0.015
SQZ_SQUEEZE_BARS = 10  # BB inside KC for N bars


def load_pair(pair):
    for pat in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        f = DATA_DIR / pat
        if f.exists():
            df = pd.read_parquet(f)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df = df.set_index('time').sort_index()
                return df
    return None


def compute_atr(df):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(ATR_PERIOD).mean().values


def classify_chop(btc_df):
    """CHOP = BTC close between SMA50 and SMA200 (either direction)."""
    c = btc_df['close'].values
    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    chop = []
    for i in range(len(c)):
        if i < 200:
            chop.append(False)
        elif c[i] > sma50[i] > sma200[i]:
            chop.append(False)  # BULL
        elif c[i] < sma50[i] < sma200[i]:
            chop.append(False)  # BEAR
        else:
            chop.append(True)   # CHOP
    return pd.Series(chop, index=btc_df.index)


def bb_mr_long(df, chop_mask):
    """BB Mean Reversion LONG: buy when price touches lower BB, exit at middle/upper."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    middle_bb = sma

    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if not chop_mask.iloc[i]:
            if in_trade:
                pnl = (c[i] - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "type": "chop_exit"})
                in_trade = False
            continue

        if in_trade:
            hours = i - entry_bar
            # Exit at middle BB or upper BB
            if c[i] >= middle_bb[i] or hours >= MR_MAX_HOLD:
                exit_p = max(middle_bb[i], c[i])
                if c[i] >= upper_bb[i]:
                    exit_p = upper_bb[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                in_trade = False

        if not in_trade and l[i] <= lower_bb[i]:
            in_trade = True
            entry_price = lower_bb[i]  # Buy at the band
            entry_bar = i

    return trades


def bb_mr_short(df, chop_mask):
    """BB Mean Reversion SHORT: sell when price touches upper BB, exit at middle/lower."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    middle_bb = sma

    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if not chop_mask.iloc[i]:
            if in_trade:
                pnl = (entry_price - c[i]) / entry_price - FRICTION
                trades.append({"pnl": pnl, "type": "chop_exit"})
                in_trade = False
            continue

        if in_trade:
            hours = i - entry_bar
            if c[i] <= middle_bb[i] or hours >= MR_MAX_HOLD:
                exit_p = min(middle_bb[i], c[i])
                if c[i] <= lower_bb[i]:
                    exit_p = lower_bb[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                in_trade = False

        if not in_trade and h[i] >= upper_bb[i]:
            in_trade = True
            entry_price = upper_bb[i]
            entry_bar = i

    return trades


def squeeze_breakout(df, chop_mask):
    """Volatility Squeeze: BB inside Keltner for N bars → breakout in either direction."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)

    # Bollinger Bands
    sma = pd.Series(c).rolling(SQZ_BB_PERIOD).mean().values
    std = pd.Series(c).rolling(SQZ_BB_PERIOD).std().values
    bb_upper = sma + SQZ_BB_STD * std
    bb_lower = sma - SQZ_BB_STD * std

    # Keltner Channel
    kc_upper = sma + SQZ_KC_ATR_MULT * atr
    kc_lower = sma - SQZ_KC_ATR_MULT * atr

    # Squeeze: BB inside KC
    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    squeeze_count = pd.Series(squeeze, index=df.index).rolling(SQZ_SQUEEZE_BARS).sum().values

    trades, in_trade = [], False
    entry_price = entry_bar = direction = highest = lowest = 0
    for i in range(max(SQZ_BB_PERIOD, SQZ_KC_PERIOD, SQZ_SQUEEZE_BARS) + 1, len(c)):
        if not chop_mask.iloc[i]:
            if in_trade:
                if direction > 0:
                    pnl = (c[i] - entry_price) / entry_price - FRICTION
                else:
                    pnl = (entry_price - c[i]) / entry_price - FRICTION
                trades.append({"pnl": pnl, "type": "chop_exit"})
                in_trade = False
            continue

        if in_trade:
            if direction > 0:
                highest = max(highest, h[i])
                trail = highest * (1 - SQZ_TRAIL)
                hours = i - entry_bar
                if l[i] <= trail or hours >= SQZ_MAX_HOLD:
                    exit_p = trail if l[i] <= trail else c[i]
                    pnl = (exit_p - entry_price) / entry_price - FRICTION
                    trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                    in_trade = False
            else:
                lowest = min(lowest, l[i])
                trail = lowest * (1 + SQZ_TRAIL)
                hours = i - entry_bar
                if h[i] >= trail or hours >= SQZ_MAX_HOLD:
                    exit_p = trail if h[i] >= trail else c[i]
                    pnl = (entry_price - exit_p) / entry_price - FRICTION
                    trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                    in_trade = False

        # Entry: squeeze has been on for N bars, then exits
        if not in_trade and squeeze_count[i-1] >= SQZ_SQUEEZE_BARS and not squeeze[i]:
            if c[i] > sma[i]:  # Breakout up
                direction = 1
                entry_price = c[i]
                entry_bar = i
                highest = h[i]
                in_trade = True
            elif c[i] < sma[i]:  # Breakout down
                direction = -1
                entry_price = c[i]
                entry_bar = i
                lowest = l[i]
                in_trade = True

    return trades


def analyze(trades, label):
    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0, "cumul": 0}
    pnls = [t['pnl'] for t in trades if 'type' not in t or t['type'] != 'chop_exit']
    if not pnls:
        pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    avg = np.mean(pnls) * 100
    cumul = (np.prod([1+p for p in pnls]) - 1) * 100
    return {"n": len(pnls), "pf": pf, "wr": wr, "avg": avg, "cumul": cumul}


# === MAIN ===
print("=" * 100)
print("CHOP REGIME STRATEGY DEVELOPMENT")
print("=" * 100)

# Load BTC for regime classification
btc = load_pair("BTCUSDT")
chop_mask = classify_chop(btc)
chop_pct = chop_mask.sum() / len(chop_mask) * 100
print(f"\nCHOP regime: {chop_mask.sum()} bars ({chop_pct:.1f}% of total)")

ASSETS = [
    "ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT",
    "DOGEUSDT", "LTCUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "AAVEUSDT"
]

# Re-run existing ATR BO in CHOP for comparison
DONCHIAN = 20
ATR_MULT_SHORT = 1.5
TRAIL_LONG = 0.01
TRAIL_SHORT = 0.025
MAX_HOLD_LONG = 96
MAX_HOLD_SHORT = 48
SMA_REGIME = 100


def atr_long_chop(df, chop_m):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    upper = pd.Series(h).rolling(DONCHIAN).max().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
    entry_price = entry_bar = highest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if not chop_m.iloc[i]:
            if in_trade:
                pnl = (c[i] - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl})
                in_trade = False
            continue
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * (1 - TRAIL_LONG)
            hours = i - entry_bar
            if hours < 4 and atr[i] > 0:
                trail = max(trail, entry_price - atr[i] * 1.5)
            if l[i] <= trail or hours >= MAX_HOLD_LONG:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl})
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades


def atr_short_chop(df, chop_m):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    lower = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
    entry_price = entry_bar = lowest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if not chop_m.iloc[i]:
            if in_trade:
                pnl = (entry_price - c[i]) / entry_price - FRICTION
                trades.append({"pnl": pnl})
                in_trade = False
            continue
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades


for pair in ASSETS:
    df = load_pair(pair)
    if df is None:
        continue

    # Align chop to pair's index
    chop_aligned = chop_mask.reindex(df.index, method='ffill')

    # Existing ATR BO in CHOP
    atr_long = atr_long_chop(df, chop_aligned)
    atr_short = atr_short_chop(df, chop_aligned)

    # BB Mean Reversion
    mr_long = bb_mr_long(df, chop_aligned)
    mr_short = bb_mr_short(df, chop_aligned)

    # Squeeze Breakout
    sqz = squeeze_breakout(df, chop_aligned)

    l_stats = analyze(atr_long, "ATR L")
    s_stats = analyze(atr_short, "ATR S")
    mrl = analyze(mr_long, "MR L")
    mrs = analyze(mr_short, "MR S")
    sqz_stats = analyze(sqz, "SQZ")

    print(f"\n{pair} (CHOP regime only):")
    print(f"  ATR BO LONG  n={l_stats['n']:4d}  PF={l_stats['pf']:5.2f}  WR={l_stats['wr']:5.1f}%  Avg={l_stats['avg']:+.2f}%")
    print(f"  ATR BO SHORT n={s_stats['n']:4d}  PF={s_stats['pf']:5.2f}  WR={s_stats['wr']:5.1f}%  Avg={s_stats['avg']:+.2f}%")
    print(f"  BB MR LONG   n={mrl['n']:4d}  PF={mrl['pf']:5.2f}  WR={mrl['wr']:5.1f}%  Avg={mrl['avg']:+.2f}%")
    print(f"  BB MR SHORT  n={mrs['n']:4d}  PF={mrs['pf']:5.2f}  WR={mrs['wr']:5.1f}%  Avg={mrs['avg']:+.2f}%")
    print(f"  Squeeze BO   n={sqz_stats['n']:4d}  PF={sqz_stats['pf']:5.2f}  WR={sqz_stats['wr']:5.1f}%  Avg={sqz_stats['avg']:+.2f}%")


# Summary
print("\n\n" + "=" * 100)
print("CHOP STRATEGY SUMMARY")
print("=" * 100)

mr_results = []
sqz_results = []

for pair in ASSETS:
    df = load_pair(pair)
    if df is None:
        continue
    chop_aligned = chop_mask.reindex(df.index, method='ffill')
    mr_long = bb_mr_long(df, chop_aligned)
    mr_short = bb_mr_short(df, chop_aligned)
    sqz = squeeze_breakout(df, chop_aligned)

    mrl = analyze(mr_long, "")
    mrs = analyze(mr_short, "")
    sqz_stats = analyze(sqz, "")

    if mrl['n'] > 0 or mrs['n'] > 0:
        mr_results.append({"pair": pair, "long": mrl, "short": mrs})
    if sqz_stats['n'] > 0:
        sqz_results.append({"pair": pair, "stats": sqz_stats})

print("\nBB Mean Reversion (combined L+S) — CHOP regime only:")
for r in mr_results:
    l, s = r['long'], r['short']
    total_n = l['n'] + s['n']
    all_pnls = [l['avg']/100]*l['n'] + [s['avg']/100]*s['n'] if l['n'] > 0 and s['n'] > 0 else []
    if all_pnls:
        gp = sum(p for p in all_pnls if p > 0)
        gl = abs(sum(p for p in all_pnls if p < 0))
        cpf = gp / gl if gl > 0 else float('inf')
        print(f"  {r['pair']:12s}  L: n={l['n']:3d} PF={l['pf']:5.2f}  S: n={s['n']:3d} PF={s['pf']:5.2f}  Combined PF={cpf:.2f}")
    else:
        better = "LONG" if l['pf'] > s['pf'] else "SHORT"
        print(f"  {r['pair']:12s}  L: n={l['n']:3d} PF={l['pf']:5.2f}  S: n={s['n']:3d} PF={s['pf']:5.2f}  Better: {better}")

print("\nSqueeze Breakout — CHOP regime only:")
for r in sqz_results:
    s = r['stats']
    print(f"  {r['pair']:12s}  n={s['n']:3d}  PF={s['pf']:5.2f}  WR={s['wr']:5.1f}%  Avg={s['avg']:+.2f}%")
