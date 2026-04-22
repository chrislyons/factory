#!/usr/bin/env python3
"""
Stop Hunt Mitigation Testing.
Compare baseline stops vs. anti-hunt alternatives:
1. Close-based stop (wait for candle CLOSE below stop, not wick touch)
2. ATR-based stop (volatility-adaptive)
3. Buffer stop (stop = baseline - ATR buffer)
4. Time-of-day filter (avoid illiquid hours)
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): return None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    return df.resample('4h').agg({
        'open':'first','high':'max','low':'min','close':'last','volume':'sum'
    }).dropna()

def compute_atr(c, h, l, period=14):
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr).rolling(period).mean().values

def stats_report(pnls, label):
    if len(pnls) < 5: return
    pnls = np.array(pnls)
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    med = np.median(pnls) * 100
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    pf = sum(wins)/abs(sum(losses)) if len(losses)>0 and sum(losses)!=0 else float('inf')
    t, p = stats.ttest_1samp(pnls, 0)
    avg_win = np.mean(wins)*100 if len(wins)>0 else 0
    avg_loss = np.mean(losses)*100 if len(losses)>0 else 0
    print(f"  {label:<30s} n={len(pnls):>4d} PF={pf:>5.2f} WR={wr:>5.1f}% Avg={avg:>+6.2f}% Med={med:>+6.2f}% W={avg_win:>+.2f}% L={avg_loss:>+.2f}%")


def test_long_variants(df4h):
    """Test multiple stop logic variants for LONG strategy."""
    c, h, l, o = df4h['close'].values, df4h['high'].values, df4h['low'].values, df4h['open'].values
    atr = compute_atr(c, h, l, 14)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
    friction = 0.0014
    results = {k: [] for k in [
        "baseline",       # wick touch, 1.5% trail
        "close_stop",     # CLOSE below trail (not wick)
        "atr_stop",       # trail = entry - 2*ATR (dynamic)
        "buffer_stop",    # trail = pct - 1*ATR buffer
        "close_atr",      # close-based + ATR buffer
        "donchian_exit",  # exit on close below Donchian10
    ]}

    for i in range(120, len(c)):
        # Entry signal
        if not (c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]):
            continue

        entry = c[i-1]  # enter at previous close
        entry_atr = atr[i-1] if not np.isnan(atr[i-1]) else entry * 0.02

        # Simulate forward from entry bar
        highest = h[i-1]
        for j in range(i, min(i+60, len(c))):  # max 60 bars = 240h
            highest = max(highest, h[j])

            # Baseline: wick touch, 1.5% trail
            baseline_stop = highest * 0.985
            if l[j] <= baseline_stop:
                xp = baseline_stop
                results["baseline"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["baseline"].append((c[j]/entry - 1 - friction))

            # Close-based: wait for CLOSE below trail
            close_stop = highest * 0.985
            if c[j] <= close_stop:
                xp = c[j]
                results["close_stop"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["close_stop"].append((c[j]/entry - 1 - friction))

            # ATR-based: stop = entry - 2*ATR (or highest - 2*ATR)
            atr_stop = highest - entry_atr * 2.0
            if l[j] <= atr_stop:
                xp = atr_stop
                results["atr_stop"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["atr_stop"].append((c[j]/entry - 1 - friction))

            # Buffer: trail - ATR cushion
            buffer_stop = highest * 0.985 - entry_atr * 0.5
            if l[j] <= buffer_stop:
                xp = buffer_stop
                results["buffer_stop"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["buffer_stop"].append((c[j]/entry - 1 - friction))

            # Close + ATR: close below (trail - ATR*0.5)
            close_atr_stop = highest * 0.985 - entry_atr * 0.5
            if c[j] <= close_atr_stop:
                xp = c[j]
                results["close_atr"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["close_atr"].append((c[j]/entry - 1 - friction))

            # Donchian exit: close below 10-bar low
            dc10_low = pd.Series(l).rolling(10).min().values[j]
            if c[j] <= dc10_low:
                xp = c[j]
                results["donchian_exit"].append((xp/entry - 1 - friction))
                break
            if j == min(i+59, len(c)-1):
                results["donchian_exit"].append((c[j]/entry - 1 - friction))

    return results


# === RUN ON ALL PAIRS ===
pairs = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "AVAXUSDT", "ARBUSDT", "OPUSDT",
         "LINKUSDT", "RENDERUSDT", "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT"]

all_results = {k: [] for k in [
    "baseline", "close_stop", "atr_stop", "buffer_stop", "close_atr", "donchian_exit"
]}

print("=" * 90)
print("STOP HUNT MITIGATION — 4H ATR LONG Strategy")
print("Comparing stop logic variants across 12 pairs")
print("=" * 90)

for pair in pairs:
    df = load_pair(pair)
    if df is None: continue
    df4h = resample_4h(df)
    if len(df4h) < 500: continue

    pair_results = test_long_variants(df4h)
    for k, v in pair_results.items():
        all_results[k].extend(v)

    # Per-pair summary
    print(f"\n--- {pair} ---")
    for k in ["baseline", "close_stop", "atr_stop", "buffer_stop", "close_atr", "donchian_exit"]:
        if len(pair_results[k]) > 5:
            stats_report(pair_results[k], k)

# Portfolio aggregate
print(f"\n{'=' * 90}")
print("PORTFOLIO AGGREGATE")
print(f"{'=' * 90}")
for k in ["baseline", "close_stop", "atr_stop", "buffer_stop", "close_atr", "donchian_exit"]:
    if len(all_results[k]) > 10:
        stats_report(all_results[k], k)

# Whipsaw analysis: how many trades go from profitable to stopped out by wick?
print(f"\n{'=' * 90}")
print("WHIPSAW ANALYSIS")
print(f"{'=' * 90}")
baseline_pnls = np.array(all_results["baseline"])
close_pnls = np.array(all_results["close_stop"])
if len(baseline_pnls) == len(close_pnls):
    diff = close_pnls - baseline_pnls
    rescued = (diff > 0.005).sum()  # trades where close-based saved >0.5%
    killed = (diff < -0.005).sum()  # trades where close-based lost >0.5%
    print(f"Trades rescued by close-based stop (saved >0.5%): {rescued} ({rescued/len(diff)*100:.1f}%)")
    print(f"Trades harmed by close-based stop (lost >0.5%):   {killed} ({killed/len(diff)*100:.1f}%)")
    print(f"Net P&L difference: {diff.sum()*100:+.2f}%")
    print(f"Avg difference per trade: {np.mean(diff)*100:+.4f}%")
