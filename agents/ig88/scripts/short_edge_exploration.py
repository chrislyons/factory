#!/usr/bin/env python3
"""
Comprehensive Short Strategy Exploration

Hypothesis: Crypto shorts work DIFFERENTLY than longs.
- Shorts are faster (dumps are violent, not grinding)
- Shorts need overbought/reversal signals, not breakdown signals
- Shorts work best in specific regimes (bear market, high funding, extreme sentiment)
- Funding rate > 0.1% = market is overleveraged long → short opportunity

Tests 10 distinct short signal families across 5 assets, 2 timeframes.
"""

import numpy as np, pandas as pd, requests, json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "short_edge_hunt"
DATA_DIR.mkdir(parents=True, exist_ok=True)


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


def fetch_funding(symbol, limit=1000):
    """Fetch perpetual funding rates from Binance."""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": min(limit, 1000)}
    all_data = []
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data: break
        all_data.extend(data)
        if len(data) < 1000: break
        params["startTime"] = data[-1]["fundingTime"] + 1
    if not all_data:
        return None
    df = pd.DataFrame(all_data)
    df['fundingRate'] = df['fundingRate'].astype(float)
    df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
    return df.set_index('fundingTime')[['fundingRate']]


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

def compute_rsi(c, p=14):
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(p).mean()
    loss = (-delta.clip(upper=0)).rolling(p).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).values


def backtest_short(df, signal_fn, trail_mult=3.0, friction=0.005, max_hold=30):
    """
    Generic short backtester.
    signal_fn(c, h, l, v, atr, adx, rsi, i) -> bool: True to enter short
    For shorts: profit when price drops, stop when price rises.
    """
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c); adx=compute_adx(h,l,c); rsi=compute_rsi(c)
    vsma=pd.Series(v).rolling(20).mean().values

    trades = []
    in_trade = False
    lowest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            # For shorts: trail stop is lowest + ATR*mult (price rising = loss)
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            # Short PnL: (entry - exit) / entry - friction
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret)
                in_trade = False
                continue
        if in_trade:
            continue

        if signal_fn(c, h, l, v, atr, adx, rsi, vsma, i):
            in_trade = True
            entry_price = c[i]
            entry_idx = i
            lowest = c[i]

    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'total': 0, 'trades': []}
    pnls = np.array(trades)
    wins = pnls[pnls>0]
    gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {
        'n': len(pnls), 'pf': pf, 'wr': len(wins)/len(pnls),
        'avg': pnls.mean(), 'total': pnls.sum(), 'trades': trades
    }


# ============================================================================
# 10 SHORT SIGNAL FAMILIES
# ============================================================================

def sig_rsi_overbought(c, h, l, v, atr, adx, rsi, vsma, i):
    """RSI overbought + reversal candle"""
    return rsi[i] > 70 and c[i] < c[i-1] and v[i] > 1.0 * vsma[i]

def sig_rsi_extreme_ob(c, h, l, v, atr, adx, rsi, vsma, i):
    """RSI extreme overbought (>80) — exhaustion"""
    return rsi[i] > 80

def sig_keltner_rejection(c, h, l, v, atr, adx, rsi, vsma, i):
    """Price hits upper Keltner + closes below + volume spike"""
    ema20 = pd.Series(c[:i+1]).ewm(span=20, adjust=False).mean().values
    kelt_upper = ema20 + 2 * atr[:i+1]
    return c[i] < kelt_upper[i] and h[i] > kelt_upper[i] and v[i] > 1.2 * vsma[i]

def sig_double_top(c, h, l, v, atr, adx, rsi, vsma, i):
    """Local double top: high[i] ~ high[i-5:i-1] max, then close down"""
    if i < 10: return False
    recent_high = max(h[i-8:i])
    return (h[i] >= recent_high * 0.995 and c[i] < c[i-1] and
            c[i] < h[i] * 0.98 and v[i] > 1.0 * vsma[i])

def sig_break_sma(c, h, l, v, atr, adx, rsi, vsma, i):
    """Close drops below SMA(20) with ADX trend confirmation"""
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    return c[i] < sma20[i] and c[i-1] >= sma20[i-1] and adx[i] > 20 and v[i] > 1.2 * vsma[i]

def sig_break_ema50(c, h, l, v, atr, adx, rsi, vsma, i):
    """Close drops below EMA(50) — major trend break"""
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]

def sig_macd_bearish_cross(c, h, l, v, atr, adx, rsi, vsma, i):
    """MACD histogram turns negative (was positive)"""
    e12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    e26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = e12 - e26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig
    return hist[i] < 0 and hist[i-1] >= 0 and v[i] > 1.0 * vsma[i]

def sig_three_red_candles(c, h, l, v, atr, adx, rsi, vsma, i):
    """3 consecutive red candles with increasing volume — momentum dump"""
    if i < 3: return False
    return (c[i] < c[i-1] and c[i-1] < c[i-2] and c[i-2] < c[i-3] and
            v[i] > v[i-1] > v[i-2] and v[i] > 1.5 * vsma[i])

def sig_bearish_engulfing(c, h, l, v, atr, adx, rsi, vsma, i):
    """Bearish engulfing candle pattern"""
    if i < 2: return False
    prev_green = c[i-1] > c[i-2]
    curr_red = c[i] < c[i-1]
    engulfs = c[i] < c[i-1] and c[i] < c[i-2] and h[i] >= h[i-1]
    return prev_green and curr_red and engulfs and v[i] > 1.0 * vsma[i]

def sig_funding_rate_spike(c, h, l, v, atr, adx, rsi, vsma, i):
    """Placeholder — needs external funding data. Skip for now."""
    return False


def main():
    print("="*70)
    print("COMPREHENSIVE SHORT STRATEGY EXPLORATION")
    print("="*70)

    # Fetch data from 2020
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    assets = {
        'ETHUSDT': 'ETH',
        'BTCUSDT': 'BTC',
        'SOLUSDT': 'SOL',
        'LINKUSDT': 'LINK',
        'AVAXUSDT': 'AVAX',
    }
    timeframes = {'4h': '4h', '1d': '1d'}

    signals = {
        'RSI Overbought (>70)': sig_rsi_overbought,
        'RSI Extreme (>80)': sig_rsi_extreme_ob,
        'Keltner Rejection': sig_keltner_rejection,
        'Double Top': sig_double_top,
        'Break SMA20': sig_break_sma,
        'Break EMA50': sig_break_ema50,
        'MACD Bearish Cross': sig_macd_bearish_cross,
        '3 Red Candles': sig_three_red_candles,
        'Bearish Engulfing': sig_bearish_engulfing,
    }

    all_results = {}

    for tf_name, tf_interval in timeframes.items():
        print(f"\n{'='*70}")
        print(f"  TIMEFRAME: {tf_name}")
        print(f"{'='*70}")

        for asset_name, asset_label in assets.items():
            print(f"\n  --- {asset_label} ({asset_name}) ---")
            try:
                df = fetch_binance(asset_name, tf_interval, start_ms=start_ms)
            except Exception as e:
                print(f"    ERROR fetching {asset_name}: {e}")
                continue

            print(f"    Data: {len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

            for sig_name, sig_fn in signals.items():
                # Test multiple ATR trail stops
                for trail in [2.0, 3.0, 4.0]:
                    r = backtest_short(df, sig_fn, trail_mult=trail)
                    key = f"{asset_label}_{tf_name}_{sig_name}_trail{trail}"
                    all_results[key] = {k: v for k, v in r.items() if k != 'trades'}

                    if r['n'] >= 5:  # Only show meaningful results
                        marker = ""
                        if r['pf'] > 2.0:
                            marker = " *** EDGE ***"
                        elif r['pf'] > 1.5:
                            marker = " ** PROMISING **"
                        elif r['pf'] > 1.0:
                            marker = " * positive *"
                        print(f"    {sig_name:25s} trail={trail}x  n={r['n']:3d}  PF={r['pf']:.3f}  WR={r['wr']:.1%}  Avg={r['avg']:+.3f}  Total={r['total']:+.1%}{marker}")

    # Year-by-year for top candidates
    print(f"\n{'='*70}")
    print(f"  YEAR-BY-YEAR for PF>1.5 signals")
    print(f"{'='*70}")

    # Find top signals
    top_signals = [(k, v) for k, v in all_results.items() if v['pf'] > 1.5 and v['n'] >= 10]
    top_signals.sort(key=lambda x: x[1]['pf'], reverse=True)

    if top_signals:
        print(f"\n  Top {min(10, len(top_signals))} short signals:")
        for k, v in top_signals[:10]:
            print(f"    {k:50s} PF={v['pf']:.3f}  n={v['n']}  WR={v['wr']:.1%}")

        # Detailed year-by-year for top 3
        for key, _ in top_signals[:3]:
            parts = key.split('_')
            asset_label = parts[0]
            tf_name = parts[1]
            sig_name = '_'.join(parts[2:-1])
            trail = float(parts[-1].replace('trail',''))

            # Reconstruct
            asset_map = {v: k for k, v in assets.items()}
            asset_name = asset_map.get(asset_label)
            if not asset_name: continue

            sig_map = {name.replace(' ','_').replace('>',''): fn for name, fn in signals.items()}
            sig_fn = signals.get(sig_name.replace('_', ' '))
            if not sig_fn: continue

            try:
                df = fetch_binance(asset_name, '4h' if tf_name == '4h' else '1d', start_ms=start_ms)
            except:
                continue

            print(f"\n  Year-by-year: {key}")
            for year in range(2021, 2027):
                yr_df = df.loc[f'{year}-01-01':f'{year}-12-31']
                if len(yr_df) < 50: break
                r = backtest_short(yr_df, sig_fn, trail_mult=trail)
                if r['n'] > 0:
                    marker = " ← LOSS" if r['pf'] < 1.0 else ""
                    print(f"    {year}: n={r['n']:3d}  PF={r['pf']:.3f}  WR={r['wr']:.1%}  Total={r['total']:+.1%}{marker}")
    else:
        print("\n  No short signals with PF > 1.5 and n >= 10 found.")
        print("  Showing best PF signals regardless:")
        all_sorted = sorted(all_results.items(), key=lambda x: x[1]['pf'], reverse=True)
        for k, v in all_sorted[:15]:
            print(f"    {k:50s} PF={v['pf']:.3f}  n={v['n']}  WR={v['wr']:.1%}")

    # Also fetch and analyze funding rates
    print(f"\n{'='*70}")
    print(f"  FUNDING RATE ANALYSIS")
    print(f"{'='*70}")

    for asset_name, asset_label in assets.items():
        perp_name = asset_name  # Binance perps use same symbol
        try:
            fr = fetch_funding(perp_name, limit=1000)
            if fr is not None and len(fr) > 0:
                rates = fr['fundingRate'].values
                print(f"\n  {asset_label} ({len(fr)} periods):")
                print(f"    Mean:   {rates.mean()*100:+.4f}%")
                print(f"    Median: {np.median(rates)*100:+.4f}%")
                print(f"    P90:    {np.percentile(rates, 90)*100:+.4f}%")
                print(f"    P95:    {np.percentile(rates, 95)*100:+.4f}%")
                high = rates[rates > 0.0005]
                vhigh = rates[rates > 0.001]
                print(f"    >5bps:  {len(high)} ({len(high)/len(rates)*100:.1f}%)")
                print(f"    >10bps: {len(vhigh)} ({len(vhigh)/len(rates)*100:.1f}%)")
        except Exception as e:
            print(f"  {asset_label}: funding fetch error: {e}")

    # Save results
    out_path = DATA_DIR / "short_exploration_results.json"
    def convert(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        return obj
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=convert)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
