#!/usr/bin/env python3
"""
Polymarket Wolf Hour Spread History Fetcher
===========================================

Fetches historical trade/price data from Polymarket's public endpoints
for BTC-related markets, computes spread and trade frequency by UTC hour,
and outputs CSV with focus on the 02:30-04:00 "Wolf Hour" window.

API Endpoints:
  - Gamma API: https://gamma-api.polymarket.com
  - CLOB API:  https://clob.polymarket.com

Usage:
  python3 scripts/pm_spread_history.py              # Full run
  python3 scripts/pm_spread_history.py --live-only   # Just current spread snapshot
  python3 scripts/pm_spread_history.py --poll 60     # Poll every 60s for live data
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median, mean
from typing import Any, Optional

import requests

# Paths
WORKSPACE = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = WORKSPACE / "data" / "polymarket"
OUTPUT_CSV = DATA_DIR / "wolf_hour_spreads.csv"
LIVE_SNAPSHOTS_FILE = DATA_DIR / "live_snapshots.jsonl"

# API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Wolf Hour window (UTC)
WOLF_HOUR_START = 2.5   # 02:30
WOLF_HOUR_END = 4.0     # 04:00

# BTC search keywords
BTC_KEYWORDS = ["btc", "bitcoin", "btc price", "bitcoin price"]

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between API calls


class PolymarketSpreadFetcher:
    """Fetches spread and trade data from Polymarket BTC markets."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "WolfHourFetcher/1.0",
            "Accept": "application/json",
        })

    def log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")

    def _get(self, url: str, params: dict = None) -> Optional[Any]:
        """Rate-limited GET request."""
        time.sleep(REQUEST_DELAY)
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            self.log(f"  [WARN] Request failed: {url} -> {e}")
            return None

    # ---- Market Discovery ----

    def fetch_btc_markets(self) -> list[dict]:
        """Fetch active BTC-related markets from Gamma API."""
        print("[1/5] Discovering BTC markets...")
        all_markets = []

        # Fetch multiple pages if available
        for offset in [0, 100]:
            data = self._get(f"{GAMMA_API}/markets", params={
                "active": True,
                "closed": False,
                "limit": 100,
                "offset": offset,
            })
            if not data:
                break
            all_markets.extend(data)
            if len(data) < 100:
                break

        # Filter for BTC-related markets
        btc_markets = []
        for m in all_markets:
            q = m.get("question", "").lower()
            if any(kw in q for kw in BTC_KEYWORDS):
                # Must have clobTokenIds and some volume
                tokens_str = m.get("clobTokenIds", "")
                if not tokens_str:
                    continue
                try:
                    tokens = json.loads(tokens_str)
                    if not tokens:
                        continue
                except (json.JSONDecodeError, TypeError):
                    continue

                vol = m.get("volumeNum", 0) or m.get("volume24hrClob", 0) or 0
                btc_markets.append({
                    "id": m["id"],
                    "question": m.get("question", ""),
                    "condition_id": m.get("conditionId", ""),
                    "tokens": tokens,
                    "volume": float(vol),
                    "current_spread": m.get("spread"),
                    "best_bid": m.get("bestBid"),
                    "best_ask": m.get("bestAsk"),
                    "last_trade_price": m.get("lastTradePrice"),
                    "outcome_prices": m.get("outcomePrices", []),
                })

        self.log(f"Found {len(btc_markets)} BTC markets")
        for m in btc_markets:
            self.log(f"  [{m['id']}] Vol=${m['volume']:,.0f}  Q: {m['question'][:60]}")

        return btc_markets

    # ---- Orderbook Snapshot ----

    def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch current orderbook for a token from CLOB /book endpoint."""
        data = self._get(f"{CLOB_API}/book", params={"token_id": token_id})
        if not data:
            return None

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return {"bid": None, "ask": None, "spread": None, "mid": None,
                     "bid_depth": 0, "ask_depth": 0}

        # Parse prices and sizes
        bid_prices = [(float(b["price"]), float(b["size"])) for b in bids]
        ask_prices = [(float(a["price"]), float(a["size"])) for a in asks]

        best_bid = max(bid_prices, key=lambda x: x[0])
        best_ask = min(ask_prices, key=lambda x: x[0])

        spread = best_ask[0] - best_bid[0]
        mid = (best_bid[0] + best_ask[0]) / 2

        # Depth (total size in top 5 levels)
        bid_depth = sum(s for _, s in sorted(bid_prices, reverse=True)[:5])
        ask_depth = sum(s for _, s in sorted(ask_prices)[:5])

        return {
            "bid": best_bid[0],
            "bid_size": best_bid[1],
            "ask": best_ask[0],
            "ask_size": best_ask[1],
            "spread": spread,
            "mid": mid,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "tick_size": data.get("tick_size"),
        }

    def fetch_midpoint(self, token_id: str) -> Optional[float]:
        """Fetch current midpoint price from CLOB."""
        data = self._get(f"{CLOB_API}/midpoint", params={"token_id": token_id})
        if data and "mid" in data:
            return float(data["mid"])
        return None

    # ---- Price History ----

    def fetch_price_history(self, token_id: str, interval: str = "max",
                            fidelity: int = 60) -> list[dict]:
        """Fetch price history from CLOB /prices-history endpoint.

        Returns list of {t: unix_timestamp, p: price}.
        """
        data = self._get(f"{CLOB_API}/prices-history", params={
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        })
        if not data:
            return []
        return data.get("history", [])

    # ---- Spread Computation ----

    def compute_spread_from_price_volatility(self, prices: list[dict],
                                              window_seconds: int = 3600) -> list[dict]:
        """Estimate spread from price update frequency and volatility.

        When orderbook data isn't available historically, we use price update
        intervals and price variance as proxies for spread/liquidity.
        """
        if len(prices) < 2:
            return []

        hourly_data = {}

        for i in range(len(prices) - 1):
            ts = prices[i]["t"]
            price = prices[i]["p"]
            next_ts = prices[i + 1]["t"]
            next_price = prices[i + 1]["p"]

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            hour = dt.hour

            if hour not in hourly_data:
                hourly_data[hour] = {
                    "prices": [],
                    "intervals": [],
                    "price_changes": [],
                }

            hourly_data[hour]["prices"].append(price)
            interval = next_ts - ts
            hourly_data[hour]["intervals"].append(interval)
            hourly_data[hour]["price_changes"].append(abs(next_price - price))

        results = []
        for hour in range(24):
            if hour not in hourly_data:
                results.append({
                    "utc_hour": hour,
                    "median_price": None,
                    "price_std": None,
                    "median_update_interval_s": None,
                    "avg_update_interval_s": None,
                    "num_updates": 0,
                    "median_abs_change": None,
                    "is_wolf_hour": WOLF_HOUR_START <= hour < WOLF_HOUR_END,
                })
                continue

            hd = hourly_data[hour]
            prices_list = hd["prices"]
            intervals = hd["intervals"]
            changes = hd["price_changes"]

            results.append({
                "utc_hour": hour,
                "median_price": round(median(prices_list), 6),
                "price_std": round(
                    (sum((p - mean(prices_list)) ** 2 for p in prices_list)
                     / len(prices_list)) ** 0.5, 6
                ) if len(prices_list) > 1 else 0,
                "median_update_interval_s": round(median(intervals), 1),
                "avg_update_interval_s": round(mean(intervals), 1),
                "num_updates": len(intervals),
                "median_abs_change": round(median(changes), 6),
                "is_wolf_hour": WOLF_HOUR_START <= hour < WOLF_HOUR_END,
            })

        return results

    # ---- Live Spread Collection ----

    def collect_live_snapshot(self, markets: list[dict]) -> dict:
        """Collect a live spread snapshot from orderbooks."""
        now = datetime.now(timezone.utc)
        snapshot = {
            "timestamp": now.isoformat(),
            "unix_ts": int(now.timestamp()),
            "utc_hour": now.hour,
            "markets": [],
        }

        for m in markets:
            market_data = {
                "id": m["id"],
                "question": m["question"][:80],
                "tokens": [],
            }
            for token_id in m["tokens"]:
                book = self.fetch_orderbook(token_id)
                mid = self.fetch_midpoint(token_id)
                market_data["tokens"].append({
                    "token_id": token_id[:20] + "...",
                    "book": book,
                    "midpoint": mid,
                })
            snapshot["markets"].append(market_data)

        return snapshot

    # ---- CSV Output ----

    def write_csv(self, hourly_data: list[dict], live_snapshots: list[dict],
                  markets: list[dict]):
        """Write combined hourly spread/trade-frequency CSV."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Enrich hourly data with live spread if we have snapshots at that hour
        live_by_hour = {}
        for snap in live_snapshots:
            h = snap["utc_hour"]
            if h not in live_by_hour:
                live_by_hour[h] = []
            for mkt in snap["markets"]:
                for tok in mkt["tokens"]:
                    book = tok.get("book") or {}
                    if book.get("spread") is not None:
                        live_by_hour[h].append(book["spread"])

        rows = []
        for hd in hourly_data:
            hour = hd["utc_hour"]
            live_spreads = live_by_hour.get(hour, [])

            row = {
                "utc_hour": f"{hour:02d}:00",
                "hour_int": hour,
                "is_wolf_hour": hd["is_wolf_hour"],
                "median_price": hd["median_price"],
                "price_std": hd["price_std"],
                "median_update_interval_s": hd["median_update_interval_s"],
                "avg_update_interval_s": hd["avg_update_interval_s"],
                "num_updates": hd["num_updates"],
                "median_abs_change": hd["median_abs_change"],
                "live_spread_median": round(median(live_spreads), 6) if live_spreads else "",
                "live_spread_count": len(live_spreads),
            }
            rows.append(row)

        fieldnames = [
            "utc_hour", "hour_int", "is_wolf_hour",
            "median_price", "price_std",
            "median_update_interval_s", "avg_update_interval_s",
            "num_updates", "median_abs_change",
            "live_spread_median", "live_spread_count",
        ]

        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"\n[5/5] CSV written to: {OUTPUT_CSV}")

    # ---- Main Pipeline ----

    def run(self, live_only: bool = False, poll_interval: Optional[int] = None):
        """Run the full Wolf Hour spread analysis pipeline."""
        print("=" * 65)
        print("  Polymarket Wolf Hour Spread History Fetcher")
        print("=" * 65)
        print(f"  UTC Now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Wolf Hour: {WOLF_HOUR_START:04.2f}-{WOLF_HOUR_END:04.2f} UTC")
        print(f"  Output: {OUTPUT_CSV}")
        print("=" * 65)

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Discover BTC markets
        markets = self.fetch_btc_markets()
        if not markets:
            print("ERROR: No BTC markets found on Polymarket.")
            return

        # 2. Collect live orderbook snapshots
        print("\n[2/5] Collecting live orderbook snapshots...")
        live_snapshots = []
        snapshot = self.collect_live_snapshot(markets)
        live_snapshots.append(snapshot)

        # Print current spreads
        for mkt in snapshot["markets"]:
            for tok in mkt["tokens"]:
                book = tok.get("book") or {}
                if book.get("spread") is not None:
                    print(f"  {mkt['question'][:40]:40s}  "
                          f"bid={book['bid']:.4f}  ask={book['ask']:.4f}  "
                          f"spread={book['spread']:.4f}")

        # Save snapshot to JSONL
        with open(LIVE_SNAPSHOTS_FILE, "a") as f:
            f.write(json.dumps(snapshot) + "\n")
        self.log(f"Snapshot saved to {LIVE_SNAPSHOTS_FILE}")

        if live_only:
            # Just print current spread summary and exit
            print("\n--- Live Spread Summary ---")
            all_spreads = []
            for mkt in snapshot["markets"]:
                for tok in mkt["tokens"]:
                    book = tok.get("book") or {}
                    if book.get("spread") is not None:
                        all_spreads.append(book["spread"])
            if all_spreads:
                print(f"  Spreads: min={min(all_spreads):.4f}  "
                      f"median={median(all_spreads):.4f}  "
                      f"max={max(all_spreads):.4f}")
            return

        # 3. Fetch price history for each token
        print("\n[3/5] Fetching price history from CLOB API...")
        all_hourly = {}  # hour -> list of per-market hourly data

        for m in markets:
            for token_id in m["tokens"]:
                self.log(f"  Fetching history for token {token_id[:20]}...")
                history = self.fetch_price_history(token_id)

                if not history:
                    self.log(f"    No history data available")
                    continue

                self.log(f"    Got {len(history)} price points")

                # Convert timestamps to dates for context
                first_dt = datetime.fromtimestamp(history[0]["t"], tz=timezone.utc)
                last_dt = datetime.fromtimestamp(history[-1]["t"], tz=timezone.utc)
                self.log(f"    Range: {first_dt.date()} to {last_dt.date()}")

                hourly = self.compute_spread_from_price_volatility(history)
                for h in hourly:
                    hour = h["utc_hour"]
                    if hour not in all_hourly:
                        all_hourly[hour] = []
                    all_hourly[hour].append(h)

        # 4. Aggregate across markets
        print("\n[4/5] Aggregating hourly spread data...")
        aggregated = []
        for hour in range(24):
            entries = all_hourly.get(hour, [])

            if not entries:
                aggregated.append({
                    "utc_hour": hour,
                    "is_wolf_hour": WOLF_HOUR_START <= hour < WOLF_HOUR_END,
                    "median_price": None,
                    "price_std": None,
                    "median_update_interval_s": None,
                    "avg_update_interval_s": None,
                    "num_updates": 0,
                    "median_abs_change": None,
                })
                continue

            all_medians = [e["median_price"] for e in entries if e["median_price"] is not None]
            all_stds = [e["price_std"] for e in entries if e["price_std"] is not None]
            all_med_intervals = [e["median_update_interval_s"] for e in entries
                                  if e["median_update_interval_s"] is not None]
            all_avg_intervals = [e["avg_update_interval_s"] for e in entries
                                  if e["avg_update_interval_s"] is not None]
            all_changes = [e["median_abs_change"] for e in entries
                           if e["median_abs_change"] is not None]
            total_updates = sum(e["num_updates"] for e in entries)

            aggregated.append({
                "utc_hour": hour,
                "is_wolf_hour": WOLF_HOUR_START <= hour < WOLF_HOUR_END,
                "median_price": round(median(all_medians), 6) if all_medians else None,
                "price_std": round(median(all_stds), 6) if all_stds else None,
                "median_update_interval_s": round(median(all_med_intervals), 1)
                    if all_med_intervals else None,
                "avg_update_interval_s": round(mean(all_avg_intervals), 1)
                    if all_avg_intervals else None,
                "num_updates": total_updates,
                "median_abs_change": round(median(all_changes), 6) if all_changes else None,
            })

        # 5. Write CSV
        self.write_csv(aggregated, live_snapshots, markets)

        # Print Wolf Hour summary
        print("\n" + "=" * 65)
        print("  WOLF HOUR ANALYSIS (02:30 - 04:00 UTC)")
        print("=" * 65)
        wolf_hours = [h for h in aggregated
                      if WOLF_HOUR_START <= h["utc_hour"] < WOLF_HOUR_END]
        other_hours = [h for h in aggregated
                       if not (WOLF_HOUR_START <= h["utc_hour"] < WOLF_HOUR_END)
                       and h["num_updates"] > 0]

        if wolf_hours:
            wolf_intervals = [h["median_update_interval_s"] for h in wolf_hours
                             if h["median_update_interval_s"]]
            other_intervals = [h["median_update_interval_s"] for h in other_hours
                              if h["median_update_interval_s"]]
            wolf_changes = [h["median_abs_change"] for h in wolf_hours
                           if h["median_abs_change"]]
            other_changes = [h["median_abs_change"] for h in other_hours
                            if h["median_abs_change"]]

            print(f"\n  Wolf Hour price update intervals:")
            for h in wolf_hours:
                marker = " <<<" if h["num_updates"] > 0 else ""
                print(f"    {h['utc_hour']:02d}:00  "
                      f"interval={h['median_update_interval_s']}s  "
                      f"updates={h['num_updates']}{marker}")

            if wolf_intervals and other_intervals:
                print(f"\n  Median update interval:")
                print(f"    Wolf Hours:  {median(wolf_intervals):.1f}s")
                print(f"    Other Hours: {median(other_intervals):.1f}s")

            if wolf_changes and other_changes:
                print(f"\n  Median abs price change:")
                print(f"    Wolf Hours:  {median(wolf_changes):.6f}")
                print(f"    Other Hours: {median(other_changes):.6f}")

        # Live spread for wolf hour
        now_utc = datetime.now(timezone.utc)
        current_hour = now_utc.hour + now_utc.minute / 60
        if WOLF_HOUR_START <= current_hour < WOLF_HOUR_END:
            print(f"\n  *** CURRENTLY IN WOLF HOUR WINDOW ***")
            all_spreads = []
            for mkt in snapshot["markets"]:
                for tok in mkt["tokens"]:
                    book = tok.get("book") or {}
                    if book.get("spread") is not None:
                        all_spreads.append(book["spread"])
            if all_spreads:
                print(f"  Current live spreads: {all_spreads}")
                print(f"  Median live spread: {median(all_spreads):.4f}")
        else:
            next_wolf = now_utc.replace(hour=2, minute=30, second=0, microsecond=0)
            if current_hour >= WOLF_HOUR_END:
                next_wolf += timedelta(days=1)
            hours_until = (next_wolf - now_utc).total_seconds() / 3600
            print(f"\n  Next Wolf Hour in {hours_until:.1f}h (at {next_wolf.strftime('%Y-%m-%d %H:%M')} UTC)")

        print("\n" + "=" * 65)
        print("  Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Wolf Hour Spread History Fetcher")
    parser.add_argument("--live-only", action="store_true",
                        help="Only collect current spread snapshot, no history")
    parser.add_argument("--poll", type=int, metavar="SECONDS",
                        help="Poll orderbooks every N seconds (live monitoring)")
    parser.add_argument("--quiet", action="store_true",
                        help="Reduce output verbosity")
    args = parser.parse_args()

    fetcher = PolymarketSpreadFetcher(verbose=not args.quiet)

    if args.poll:
        print(f"Polling every {args.poll}s. Ctrl+C to stop.")
        try:
            while True:
                fetcher.run(live_only=True)
                print(f"\n  Sleeping {args.poll}s...")
                time.sleep(args.poll)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        fetcher.run(live_only=args.live_only)


if __name__ == "__main__":
    main()
