#!/usr/bin/env python3
"""
Portfolio v7 — Port exact v6 validated signals with aggressive allocations.

Replicates the EXACT logic from portfolio_v6_edges.py that was walk-forward
validated, then models aggressive allocation scenarios.
"""

import numpy as np, pandas as pd, json
from pathlib import Path
from datetime import datetime, timezone
import requests

DATA = Path(__file__).resolve().parents[1] / "data" / "portfolio_v7"
DATA.mkdir(parents=True, exist_ok=True)


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
    return df.set_index('ts')[['o','h','l','c','v']].rename(
        columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})


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


def backtest_long(df, signal_fn, trail_mult=2.5, friction=0.005, max_hold=30):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values
    trades = []; in_trade = False; highest = 0.0; entry_idx = 0; entry_price = 0.0
    for i in range(55, len(c)):
        if in_trade:
            highest = max(highest, c[i])
            trail_stop = highest - trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (c[i] - entry_price) / entry_price - friction
            if c[i] < trail_stop or bars_held >= max_hold:
                trades.append(ret); in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, adx, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; highest = c[i]
    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[]}
    pnls = np.array(trades); wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
            'total':pnls.sum(),'trades':trades}


def backtest_short(df, signal_fn, trail_mult=2.0, friction=0.001, max_hold=30):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    vsma=pd.Series(v).rolling(20).mean().values
    trades = []; in_trade = False; lowest = 0.0; entry_idx = 0; entry_price = 0.0
    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret); in_trade = False; continue
        if in_trade: continue
        if signal_fn(c, h, l, v, atr, vsma, i):
            in_trade = True; entry_price = c[i]; entry_idx = i; lowest = c[i]
    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0,'trades':[]}
    pnls = np.array(trades); wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),
            'total':pnls.sum(),'trades':trades}


# EXACT v6 signals
def sig_eth_keltner(c, h, l, v, atr, adx, vsma, i):
    if i < 25: return False
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_upper = ema20 + 2 * atr[:i+1]
    return c[i] > kelt_upper[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_eth_vol_breakout(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    atr_sma = pd.Series(atr[:i+1]).rolling(50).mean().values
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return atr[i] > 1.5 * atr_sma[i] and c[i] > sma20[i] and v[i] > 1.2 * vsma[i]

def sig_eth_macd(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] > 0 and hist[i-1] <= 0 and c[i] > ema50[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_eth_ema50_short(c, h, l, v, atr, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

def sig_eth_20low_short(c, h, l, v, atr, vsma, i):
    if i < 22: return False
    low20 = pd.Series(l[:i]).rolling(20).min().values
    return c[i] < low20[-1] and v[i] > 1.5 * vsma[i]

def sig_btc_ema50_short(c, h, l, v, atr, vsma, i):
    if i < 52: return False
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

# NEW: SOL and additional signals
def sig_sol_macd(c, h, l, v, atr, adx, vsma, i):
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    return hist[i] > 0 and hist[i-1] <= 0 and v[i] > 1.2 * vsma[i] and adx[i] > 25

def sig_sol_donchian(c, h, l, v, atr, adx, vsma, i):
    if i < 25: return False
    upper = pd.Series(h[:i]).rolling(20).max().values[-1]
    return c[i] > upper and v[i] > 1.2 * vsma[i] and adx[i] > 20


def walk_forward(df, sig_fn, side='long', trail=2.5, fric=0.005, hold=30):
    """Walk-forward OOS validation across 4 splits."""
    total = len(df)
    oos_pfs = []
    oos_totals = []
    oos_trades = []

    for k in range(1, 5):
        is_pct = 0.50 + k * 0.05
        is_idx = int(total * is_pct)
        if is_idx < 100 or total - is_idx < 100: continue
        df_oos = df.iloc[is_idx:]
        if side == 'short':
            r = backtest_short(df_oos, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        else:
            r = backtest_long(df_oos, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        if r['n'] > 0:
            oos_pfs.append(r['pf'])
            oos_totals.append(r['total'])
            oos_trades.append(r['n'])

    if oos_pfs:
        return {
            'oos_pf': np.mean(oos_pfs), 'oos_pf_std': np.std(oos_pfs),
            'oos_total': np.mean(oos_totals),
            'oos_trades': sum(oos_trades),
            'robust': np.mean(oos_pfs) > 1.0,
        }
    return None


def equity_curve_from_trades(trade_lists, weights, capital=10000):
    """Build portfolio equity curve from interleaved trades."""
    # Flatten all trades with weights
    all_trades = []
    for name, trades in trade_lists.items():
        w = weights.get(name, 0)
        for t in trades:
            all_trades.append({'ret': t, 'weight': w})

    # Sort by... well, we don't have timestamps in the raw trade list
    # So we compute cumulative equity assuming trades are chronologically ordered within each edge
    eq = [capital]
    peak = capital
    max_dd = 0
    wins = 0

    for t in all_trades:
        pnl = t['ret'] * t['weight']
        new_eq = eq[-1] * (1 + pnl)
        eq.append(max(new_eq, 1))
        peak = max(peak, eq[-1])
        dd = (peak - eq[-1]) / peak
        max_dd = max(max_dd, dd)
        if pnl > 0: wins += 1

    return {
        'final': eq[-1],
        'total_ret': eq[-1] / capital - 1,
        'max_dd': max_dd,
        'n_trades': len(all_trades),
        'win_rate': wins / len(all_trades) if all_trades else 0,
        'equity': eq,
    }


def main():
    print("=" * 72)
    print("  PORTFOLIO v7 — EXACT v6 SIGNALS + AGGRESSIVE ALLOCATIONS")
    print("=" * 72)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    print("\nFetching Binance data (2020-2026)...")
    df_eth_4h = fetch_binance('ETHUSDT', '4h', start_ms=start_ms)
    df_link_4h = fetch_binance('LINKUSDT', '4h', start_ms=start_ms)
    df_sol_4h = fetch_binance('SOLUSDT', '4h', start_ms=start_ms)
    df_eth_daily = fetch_binance('ETHUSDT', '1d', start_ms=start_ms)
    df_btc_daily = fetch_binance('BTCUSDT', '1d', start_ms=start_ms)

    print(f"ETH 4h: {len(df_eth_4h)} bars")
    print(f"LINK 4h: {len(df_link_4h)} bars")
    print(f"SOL 4h: {len(df_sol_4h)} bars")
    print(f"ETH Daily: {len(df_eth_daily)} bars")
    print(f"BTC Daily: {len(df_btc_daily)} bars")

    # Run backtests
    edges = {
        'L1: ETH Keltner': (df_eth_4h, sig_eth_keltner, 'long', 2.5, 0.005, 30),
        'L2: ETH Vol Breakout': (df_eth_4h, sig_eth_vol_breakout, 'long', 4.0, 0.005, 30),
        'L3: ETH MACD': (df_eth_4h, sig_eth_macd, 'long', 3.0, 0.005, 30),
        'S1: ETH EMA50 Short': (df_eth_daily, sig_eth_ema50_short, 'short', 2.0, 0.001, 30),
        'S2: ETH 20-Low Short': (df_eth_daily, sig_eth_20low_short, 'short', 2.0, 0.001, 30),
        'S3: BTC EMA50 Short': (df_btc_daily, sig_btc_ema50_short, 'short', 2.0, 0.001, 30),
        'L4: SOL MACD': (df_sol_4h, sig_sol_macd, 'long', 3.0, 0.005, 30),
        'L5: SOL Donchian': (df_sol_4h, sig_sol_donchian, 'long', 2.5, 0.005, 30),
    }

    print(f"\n{'='*72}")
    print(f"  FULL-SAMPLE RESULTS")
    print(f"{'='*72}")
    print(f"\n{'Edge':<25s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>8s} {'Total':>8s} {'Trail':>6s}")
    print(f"{'-'*25} {'-'*4} {'-'*7} {'-'*6} {'-'*8} {'-'*8} {'-'*6}")

    results = {}
    for name, (df, sig_fn, side, trail, fric, hold) in edges.items():
        if side == 'short':
            r = backtest_short(df, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        else:
            r = backtest_long(df, sig_fn, trail_mult=trail, friction=fric, max_hold=hold)
        results[name] = r
        print(f"{name:<25s} {r['n']:4d} {r['pf']:7.3f} {r['wr']:5.0%} {r['avg']:+8.3f} {r['total']:+7.1%} {trail:5.1f}x")

    # Walk-forward OOS
    print(f"\n{'='*72}")
    print(f"  WALK-FORWARD OOS VALIDATION")
    print(f"{'='*72}\n")

    wf_results = {}
    for name, (df, sig_fn, side, trail, fric, hold) in edges.items():
        wf = walk_forward(df, sig_fn, side, trail, fric, hold)
        wf_results[name] = wf
        if wf:
            status = "ROBUST" if wf['robust'] else "FRAGILE"
            print(f"  {name:<25s}  OOS PF={wf['oos_pf']:.3f} ± {wf['oos_pf_std']:.3f}  "
                  f"Avg OOS Total={wf['oos_total']:+.1%}  n={wf['oos_trades']}  [{status}]")
        else:
            print(f"  {name:<25s}  INSUFFICIENT TRADES")

    # Portfolio allocation scenarios
    print(f"\n{'='*72}")
    print(f"  PORTFOLIO SCENARIOS (aggressive)")
    print(f"{'='*72}")

    # Only use ROBUST edges
    robust_edges = {k: v for k, v in wf_results.items() if v and v['robust']}
    print(f"\n  Robust edges: {list(robust_edges.keys())}")

    scenarios = {
        'PF>2 Concentration': {k: 1.0/len([e for e,v in robust_edges.items()
            if wf_results[e]['oos_pf'] > 2.0]) for k in robust_edges
            if wf_results[k]['oos_pf'] > 2.0},
        'All Robust (equal)': {k: 1.0/len(robust_edges) for k in robust_edges},
        'PF>1.5 Weighted': {k: wf_results[k]['oos_pf'] for k in robust_edges
            if wf_results[k]['oos_pf'] > 1.5},
    }

    # Normalize weights
    for name in scenarios:
        total = sum(scenarios[name].values())
        if total > 0:
            scenarios[name] = {k: v/total for k, v in scenarios[name].items()}

    for scenario_name, alloc in scenarios.items():
        if not alloc:
            print(f"\n  {scenario_name}: No qualifying edges")
            continue

        # Combined equity curve from trades
        trade_lists = {}
        for edge_name in alloc:
            if edge_name in results:
                trade_lists[edge_name] = results[edge_name]['trades']

        # Interleave trades by edge (simplified — assumes edges don't overlap perfectly)
        combined_trades = []
        for edge_name, weight in alloc.items():
            if edge_name in results:
                for t in results[edge_name]['trades']:
                    combined_trades.append(t * weight)

        if not combined_trades:
            continue

        eq = [10000]
        peak = 10000
        max_dd = 0
        for t in combined_trades:
            eq.append(max(eq[-1] * (1 + t), 1))
            peak = max(peak, eq[-1])
            max_dd = max(max_dd, (peak - eq[-1]) / peak)

        total_ret = eq[-1] / 10000 - 1
        # Annualize from ~5 years
        years = 5.0
        ann = (1 + total_ret) ** (1/years) - 1 if total_ret > -0.99 else -0.99

        print(f"\n  {scenario_name}")
        print(f"    Allocation: {', '.join(f'{k}={v:.0%}' for k,v in alloc.items())}")
        print(f"    Combined: {total_ret:+.1%} total, {ann:+.1%} annualized, DD={max_dd:.1%}")
        print(f"    Trades: {len(combined_trades)}")

    # Save
    out = {}
    for name, r in results.items():
        out[name] = {'pf': r['pf'], 'n': r['n'], 'total': r['total'], 'wr': r['wr']}
    for name, wf in wf_results.items():
        if wf:
            out[name]['oos_pf'] = wf['oos_pf']
            out[name]['robust'] = wf['robust']
    with open(DATA / "exact_v6_results.json", 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to data/portfolio_v7/exact_v6_results.json")


if __name__ == "__main__":
    main()
