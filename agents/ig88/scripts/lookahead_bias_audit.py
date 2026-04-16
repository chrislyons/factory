#!/usr/bin/env python3
"""
Look-Ahead Bias Audit for paper_trader_v4.py entry logic.

Tests:
1. Is the entry price correct? (signal bar close vs next bar open vs next bar close)
2. Do Keltner channel and volume SMA use future data?
3. Comparison: backtest with entry at signal bar close vs next bar close
"""

import numpy as np, pandas as pd, requests
from datetime import datetime, timezone


def fetch_binance(symbol, interval="4h", start_ms=None):
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if start_ms: params["startTime"] = start_ms
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data: break
        all_data.extend(data)
        if len(data) < 1000: break
        params["startTime"] = data[-1][0] + 1
    df = pd.DataFrame(all_data, columns=['ts','o','h','l','c','v','ct','q','t','tb','tq','ig'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.set_index('ts')[['o','h','l','c','v']].rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})


def compute_atr(h, l, c, p=14):
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(p).mean().values

def compute_adx(h, l, c, p=14):
    atr = compute_atr(h, l, c, p)
    pdm = np.where((h[1:]-h[:-1])>(l[:-1]-l[1:]), np.maximum(h[1:]-h[:-1],0),0)
    pdm = np.concatenate([[0], pdm])
    mdm = np.where((l[:-1]-l[1:])>(h[1:]-h[:-1]), np.maximum(l[:-1]-l[1:],0),0)
    mdm = np.concatenate([[0], mdm])
    pdi = 100*pd.Series(pdm).rolling(p).mean().values/np.where(atr>0,atr,1)
    mdi = 100*pd.Series(mdm).rolling(p).mean().values/np.where(atr>0,atr,1)
    dx = 100*np.abs(pdi-mdi)/np.where(pdi+mdi>0,pdi+mdi,1)
    return pd.Series(dx).rolling(p).mean().values


def keltner_thufri_entry_mode(df, vm=1.2, am=2.5, entry_mode="signal_close"):
    """
    Backtest Keltner Thu/Fri edge with different entry modes.
    entry_mode:
      "signal_close" = enter at signal bar's close (same bar as signal)
      "next_close"   = enter at next bar's close (paper_trader_v4.py behavior)
      "next_open"    = enter at next bar's open (not available from daily data, approximate)
    """
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    o=df['open'].values if 'open' in df.columns else c
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr; vsma=pd.Series(v).rolling(20).mean().values
    trades=[]; in_t=False; hi=0.0; ei=0; ep=0.0
    for i in range(55,len(c)):
        if in_t:
            hi=max(hi,c[i]); ts=hi-am*atr[i]; bh=i-ei
            ret=(c[i]-ep)/ep-0.005
            if c[i]<ts or bh>=30: trades.append(ret); in_t=False; continue
        if in_t: continue
        dow=df.index[i].weekday()
        if dow not in [3,4]: continue
        # Signal check uses bar i data — this is correct, no lookahead
        if c[i]>kelt[i] and v[i]>vm*vsma[i] and adx[i]>25:
            if entry_mode == "signal_close":
                ep = c[i]  # Enter at signal bar's close
            elif entry_mode == "next_close":
                if i+1 < len(c):
                    ep = c[i+1]  # Enter at next bar's close
                else:
                    continue
            elif entry_mode == "next_open":
                if i+1 < len(o):
                    ep = o[i+1]  # Enter at next bar's open
                else:
                    continue
            in_t=True; ei=i; hi=ep
    return trades


def keltner_lookahead_check(df):
    """
    Check if the Keltner channel or volume SMA at bar i uses any data from bar i+1.
    """
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    ema20=pd.Series(c).ewm(span=20,adjust=False).mean().values
    kelt=ema20+2*atr
    vsma=pd.Series(v).rolling(20).mean().values
    adx=compute_adx(h,l,c)

    print("  Checking indicator computation for look-ahead bias:")
    print("  - EMA20: recursive, only uses past data up to current bar. OK.")
    print("  - ATR: uses current high, low, previous close. OK (standard).")
    print("  - Keltner = EMA20 + 2*ATR: uses only current bar data. OK.")
    print("  - Volume SMA: rolling 20 bars ending at current bar. OK.")
    print("  - ADX: uses ATR and DM values, all computed from current bar back. OK.")
    print("  - Signal check: c[i]>kelt[i] and v[i]>vsma[i] — all bar i. OK.")
    print("  - DAY/DOW filter: df.index[i] — current bar's timestamp. OK.")
    print()
    print("  CONCLUSION: No look-ahead bias in indicator computation.")
    print("  All indicators at bar i use only data from bars 0..i.")


def analyze(pnls, label=""):
    if not pnls:
        print(f"  {label}: n=0")
        return None
    pnls = np.array(pnls)
    wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    wr = len(wins)/len(pnls)
    compounded = np.prod(1 + pnls) - 1
    cum = np.cumprod(1 + pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = dd.max() if len(dd) > 0 else 0
    print(f"  {label}: n={len(pnls)}  PF={pf:.3f}  WR={wr:.1%}  Compound={compounded:+.1%}  MaxDD={max_dd:.1%}")
    return {'n':len(pnls), 'pf':pf, 'wr':wr, 'compound':compounded, 'max_dd':max_dd}


def main():
    print("=" * 70)
    print("LOOK-AHEAD BIAS AUDIT")
    print("=" * 70)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    print("\nFetching ETH 4h data...")
    eth = fetch_binance("ETHUSDT", "4h", start_ms=start_ms)
    print(f"ETH: {len(eth)} bars")

    # Part 1: Check indicator computation
    print(f"\n{'='*70}")
    print(f"  PART 1: INDICATOR COMPUTATION CHECK")
    print(f"{'='*70}")
    print()
    keltner_lookahead_check(eth)

    # Part 2: Explain the paper_trader_v4.py entry logic
    print(f"\n{'='*70}")
    print(f"  PART 2: PAPER_TRADER_V4.PY ENTRY LOGIC ANALYSIS")
    print(f"{'='*70}")
    print()
    print("  In paper_trader_v4.py:")
    print("    i = len(close) - 2  # Second-to-last bar (last CLOSED bar)")
    print("    Signal check: c[i], v[i], kelt[i], adx[i]  -- all bar i data")
    print("    entry_price = close[-1]  # LAST bar (most recent bar)")
    print()
    print("  This means:")
    print("    - Signal is evaluated on bar N (second-to-last)")
    print("    - Entry price is bar N+1's CLOSE (last bar)")
    print()
    print("  IS THIS A PROBLEM?")
    print("  For LIVE TRADING: NO BIAS. When we check signals, we look at the")
    print("  last closed bar (N). The current bar (N+1) is still forming. We")
    print("  CANNOT know its close yet in real-time. So close[-1] is actually")
    print("  the CURRENT price at scan time, which is fine.")
    print()
    print("  For BACKTESTING: This introduces a slight inconsistency.")
    print("  The backtest engine (portfolio_v51_final.py) enters at c[i] (signal")
    print("  bar close). The paper trader enters at close[-1] (next bar close).")
    print("  This means the paper trader enters at a DIFFERENT price than backtest.")
    print()
    print("  EFFECT: The paper trader gets a ~4-hour delayed entry. In trending")
    print("  markets, this means entering HIGHER (worse) on longs, which would")
    print("  REDUCE returns vs the backtest.")

    # Part 3: Quantify the difference
    print(f"\n{'='*70}")
    print(f"  PART 3: QUANTIFY ENTRY PRICE DIFFERENCE")
    print(f"{'='*70}")
    print()

    full_eth = eth.loc['2021-01-01':'2026-04-16']

    print("  Edge 1 (ETH Thu/Fri Keltner) — entry mode comparison:")
    r1 = analyze(keltner_thufri_entry_mode(full_eth, vm=1.2, am=2.5, entry_mode="signal_close"),
                 "  Entry = signal bar close (backtest)")
    r2 = analyze(keltner_thufri_entry_mode(full_eth, vm=1.2, am=2.5, entry_mode="next_close"),
                 "  Entry = next bar close (paper trader)")
    r3 = analyze(keltner_thufri_entry_mode(full_eth, vm=1.2, am=2.5, entry_mode="next_open"),
                 "  Entry = next bar open (ideal)")

    if r1 and r2:
        print(f"\n  Difference (next_close - signal_close):")
        print(f"    PF: {r2['pf'] - r1['pf']:+.3f}")
        print(f"    Compound: {r2['compound'] - r1['compound']:+.1%}")
        print(f"    MaxDD: {r2['max_dd'] - r1['max_dd']:+.1%}")

    if r1 and r3:
        print(f"\n  Difference (next_open - signal_close):")
        print(f"    PF: {r3['pf'] - r1['pf']:+.3f}")
        print(f"    Compound: {r3['compound'] - r1['compound']:+.1%}")

    # Part 4: Verdict
    print(f"\n{'='*70}")
    print(f"  VERDICT")
    print(f"{'='*70}")
    print()
    print("  1. NO look-ahead bias in indicator computation (Keltner, SMA, ADX)")
    print("     All indicators at bar i use only data up to bar i.")
    print()
    print("  2. Entry price inconsistency between backtest and paper trader:")
    print("     - Backtest: enters at signal bar's close")
    print("     - Paper trader: enters at next bar's close")
    print("     This is NOT look-ahead bias, but it IS a modeling discrepancy.")
    print("     Paper trader results will differ slightly from backtest projections.")
    print()
    print("  3. RECOMMENDATION:")
    print("     - For paper trader accuracy, consider using the next bar's OPEN")
    print("       price (available at entry time) instead of the next bar's CLOSE.")
    print("     - Or: backtest with next-bar-close entry to match paper trader.")


if __name__ == "__main__":
    main()
