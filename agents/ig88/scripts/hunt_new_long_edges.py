#!/usr/bin/env python3
"""Hunt for new ETH long edges with PF > 2.0"""

import numpy as np, pandas as pd, requests, json
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "portfolio_v7"

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

def compute_rsi(c, p=14):
    delta = np.diff(c)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(p).mean().values
    avg_loss = pd.Series(loss).rolling(p).mean().values
    rs = np.where(avg_loss > 0, avg_gain / np.where(avg_loss > 0, avg_loss, 1), 100)
    rsi = 100 - 100 / (1 + rs)
    return np.concatenate([[50], rsi])

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
    if not trades: return {'n':0,'pf':0,'wr':0,'avg':0,'total':0}
    pnls = np.array(trades); wins = pnls[pnls>0]; gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n':len(pnls),'pf':pf,'wr':len(wins)/len(pnls),'avg':pnls.mean(),'total':pnls.sum()}

# === SIGNAL FUNCTIONS ===

def sig_rsi_trend_reversal(c, h, l, v, atr, adx, vsma, i):
    """RSI crosses above 30 AND close > EMA50"""
    if i < 55: return False
    rsi = compute_rsi(c[:i+1])
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return rsi[i-1] < 30 and rsi[i] >= 30 and c[i] > ema50[i] and v[i] > 1.2 * vsma[i]

def sig_ichimoku_tk_cross(c, h, l, v, atr, adx, vsma, i):
    """Tenkan crosses above Kijun AND price above cloud"""
    if i < 55: return False
    high9 = pd.Series(h[:i+1]).rolling(9).max().values
    low9 = pd.Series(l[:i+1]).rolling(9).min().values
    tenkan = (high9 + low9) / 2
    high26 = pd.Series(h[:i+1]).rolling(26).max().values
    low26 = pd.Series(l[:i+1]).rolling(26).min().values
    kijun = (high26 + low26) / 2
    # Cloud (senkou span A and B)
    span_a = (tenkan + kijun) / 2
    high52 = pd.Series(h[:i+1]).rolling(52).max().values
    low52 = pd.Series(l[:i+1]).rolling(52).min().values
    span_b = (high52 + low52) / 2
    cloud_top = np.maximum(span_a, span_b)
    return (tenkan[i] > kijun[i] and tenkan[i-1] <= kijun[i-1] and
            c[i] > cloud_top[i] and v[i] > 1.2 * vsma[i])

def sig_donchian_macd_confluence(c, h, l, v, atr, adx, vsma, i):
    """Close breaks 20-bar high AND MACD histogram > 0"""
    if i < 55: return False
    upper20 = pd.Series(h[:i]).rolling(20).max().values[-1]
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    return c[i] > upper20 and hist[i] > 0 and v[i] > 1.2 * vsma[i] and adx[i] > 20

def sig_ema_ribbon(c, h, l, v, atr, adx, vsma, i):
    """EMA8 > EMA21 > EMA50 AND close > EMA8"""
    if i < 55: return False
    e8 = pd.Series(c[:i+1]).ewm(span=8, adjust=False).mean().values
    e21 = pd.Series(c[:i+1]).ewm(span=21, adjust=False).mean().values
    e50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    # Only trigger on new alignment (prev bar was not aligned)
    prev_aligned = e8[i-1] > e21[i-1] and e21[i-1] > e50[i-1]
    return (e8[i] > e21[i] and e21[i] > e50[i] and not prev_aligned and
            c[i] > e8[i] and v[i] > 1.2 * vsma[i])

def sig_atr_squeeze_bb(c, h, l, v, atr, adx, vsma, i):
    """ATR < 0.7x SMA50(ATR) AND close breaks above Bollinger upper"""
    if i < 75: return False
    atr_sma = pd.Series(atr[:i+1]).rolling(50).mean().values
    sma20 = pd.Series(c[:i+1]).rolling(20).mean().values
    std20 = pd.Series(c[:i+1]).rolling(20).std().values
    bb_upper = sma20 + 2 * std20
    return (atr[i] < 0.7 * atr_sma[i] and c[i] > bb_upper[i] and
            c[i-1] <= bb_upper[i-1] and v[i] > 1.2 * vsma[i])

def sig_supertrend_flip(c, h, l, v, atr, adx, vsma, i):
    """Supertrend flips bullish"""
    if i < 55: return False
    a = atr[:i+1]
    mult = 3.0
    hl2 = (h[:i+1] + l[:i+1]) / 2
    upper_band = hl2 + mult * a
    lower_band = hl2 - mult * a
    # Simplified supertrend: close crosses above lower band after being below
    st = np.zeros(i+1)
    st[0] = upper_band[0]
    for j in range(1, i+1):
        if c[j] > upper_band[j-1]:
            st[j] = lower_band[j]
        elif c[j] < lower_band[j-1]:
            st[j] = upper_band[j]
        else:
            st[j] = st[j-1]
            if st[j] == upper_band[j-1] and lower_band[j] < st[j]:
                st[j] = lower_band[j]
            elif st[j] == lower_band[j-1] and upper_band[j] > st[j]:
                st[j] = upper_band[j]
    return c[i] > st[i] and c[i-1] <= st[i-1] and v[i] > 1.2 * vsma[i]

def sig_macd_rsi_combo(c, h, l, v, atr, adx, vsma, i):
    """MACD histogram crosses up AND RSI > 50 AND ADX > 25"""
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    rsi = compute_rsi(c[:i+1])
    return (hist[i] > 0 and hist[i-1] <= 0 and rsi[i] > 50 and
            adx[i] > 25 and v[i] > 1.2 * vsma[i])

def sig_macd_pullback(c, h, l, v, atr, adx, vsma, i):
    """MACD histogram > 0, price pulls back to EMA21, then bounces"""
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema21 = pd.Series(c[:i+1]).ewm(span=21, adjust=False).mean().values
    # Price touched EMA21 within last 3 bars and bounced above it
    touched = any(c[max(i-3,0):i+1] <= ema21[max(i-3,0):i+1] * 1.005)
    return (hist[i] > 0 and touched and c[i] > ema21[i] * 1.002 and
            adx[i] > 25 and v[i] > 1.2 * vsma[i])

def sig_eth_macd_v6(c, h, l, v, atr, adx, vsma, i):
    """Existing v6 MACD signal for comparison"""
    if i < 55: return False
    ema12 = pd.Series(c[:i+1]).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c[:i+1]).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - sig_line
    ema50 = pd.Series(c[:i+1]).ewm(span=50, adjust=False).mean().values
    return hist[i] > 0 and hist[i-1] <= 0 and c[i] > ema50[i] and v[i] > 1.2 * vsma[i] and adx[i] > 25

def main():
    print("Fetching ETH 4h data (2020-2026)...")
    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    df = fetch_binance('ETHUSDT', '4h', start_ms=start_ms)
    print(f"ETH 4h: {len(df)} bars\n")

    signals = {
        'RSI Trend Reversal': sig_rsi_trend_reversal,
        'Ichimoku TK Cross': sig_ichimoku_tk_cross,
        'Donchian+MACD': sig_donchian_macd_confluence,
        'EMA Ribbon': sig_ema_ribbon,
        'ATR Squeeze BB': sig_atr_squeeze_bb,
        'Supertrend Flip': sig_supertrend_flip,
        'MACD+RSI Combo': sig_macd_rsi_combo,
        'MACD Pullback': sig_macd_pullback,
        # Existing edges for comparison
        'ETH MACD (v6)': sig_eth_macd_v6,
    }

    print(f"{'Signal':<25s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>7s} {'Total':>8s} {'DD':>6s}")
    print(f"{'-'*25} {'-'*4} {'-'*7} {'-'*6} {'-'*7} {'-'*8} {'-'*6}")

    for name, sig_fn in signals.items():
        r = backtest_long(df, sig_fn)
        if r['n'] > 0:
            print(f"{name:<25s} {r['n']:4d} {r['pf']:7.3f} {r['wr']:5.0%} {r['avg']:+6.2%} {r['total']:+7.1%} {'':>6s}")
        else:
            print(f"{name:<25s} {r['n']:4d} {'—':>7s} {'—':>6s} {'—':>7s} {'—':>8s} {'—':>6s}")

    # Walk-forward for promising edges
    print(f"\n--- WALK-FORWARD OOS ---\n")
    total = len(df)
    for name, sig_fn in signals.items():
        r_full = backtest_long(df, sig_fn)
        if r_full['n'] < 10 or r_full['pf'] < 1.0:
            continue
        oos_pfs = []
        for k in range(1, 5):
            is_pct = 0.50 + k * 0.05
            is_idx = int(total * is_pct)
            if is_idx < 100 or total - is_idx < 100: continue
            r = backtest_long(df.iloc[is_idx:], sig_fn)
            if r['n'] > 0:
                oos_pfs.append(r['pf'])
        if oos_pfs:
            status = "ROBUST" if np.mean(oos_pfs) > 1.0 else "FRAGILE"
            print(f"  {name:<25s} OOS PF={np.mean(oos_pfs):.3f} ± {np.std(oos_pfs):.3f} [{status}]")

if __name__ == "__main__":
    main()
