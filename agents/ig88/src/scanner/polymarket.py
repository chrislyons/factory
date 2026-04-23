"""
Polymarket Scanner
==================
Scans Polymarket prediction markets for calibration arbitrage and
base-rate opportunities. Different from perps — works on binary outcomes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.scanner.base import (
    VenueScanner, Signal, SignalType, RegimeState, PositionInfo,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class PolymarketScanner(VenueScanner):
    """Scanner for Polymarket prediction markets."""

    venue_name = "polymarket"
    venue_type = "prediction"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("api_url", "https://gamma-api.polymarket.com")
        self.clob_url = config.get("clob_url", "https://clob.polymarket.com")
        self.edge_threshold = config.get("edge_threshold", 0.05)
        self.confidence_min = config.get("confidence_min", 0.6)
        self.max_markets_per_scan = config.get("max_markets_per_scan", 50)

    def scan(self) -> list[Signal]:
        """Scan Polymarket for calibration and edge opportunities.

        Polymarket strategy differs from perps:
        - We have a model probability estimate for each market
        - We look for |model_estimate - market_price| > edge_threshold
        - Confidence is based on Brier score track record
        """
        signals: list[Signal] = []

        # In paper mode, scan from local market data if available
        markets = self._load_markets()
        if not markets:
            return []

        for market in markets[:self.max_markets_per_scan]:
            try:
                sig = self._check_calibration_edge(market)
                if sig:
                    signals.append(sig)
            except Exception as e:
                logger.warning(f"Error scanning market {market.get('id', '?')}: {e}")
                continue

        return signals

    def _load_markets(self) -> list[dict[str, Any]]:
        """Load markets from local data or API."""
        # Try local cache first
        markets_file = DATA_DIR / "polymarket_scan.json"
        if markets_file.exists():
            try:
                with open(markets_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Placeholder: in production, would fetch from API
        # For now, return empty — scanner needs market data
        return []

    def _check_calibration_edge(self, market: dict[str, Any]) -> Optional[Signal]:
        """Check if a market has a calibration edge.

        A calibration edge exists when:
        - Model probability != market price
        - The edge exceeds the threshold
        - The market is liquid enough
        """
        market_id = market.get("id", "")
        question = market.get("question", "")
        market_price = market.get("price", 0.5)
        model_estimate = market.get("model_estimate", None)
        liquidity = market.get("liquidity", 0)

        if model_estimate is None:
            return None

        edge = abs(model_estimate - market_price)
        if edge < self.edge_threshold:
            return None

        min_liquidity = self.risk_limits.get("max_notional_usd", 5000) * 0.1
        if liquidity < min_liquidity:
            return None

        # Direction: buy if model > market, sell if model < market
        if model_estimate > market_price:
            direction = "long"
            score = edge / 0.30  # Normalize to 0-1 (max expected edge ~30%)
        else:
            direction = "short"
            score = edge / 0.30

        score = min(1.0, score)
        confidence = min(1.0, edge / 0.15)  # Higher edge = higher confidence

        # Size scales with edge but caps at max position
        size_frac = min(0.10, edge * 2.0)  # 2x edge as size fraction, max 10%

        now = datetime.now(timezone.utc).isoformat()
        return Signal(
            signal_id=f"polymarket:{market_id}:{now}",
            venue="polymarket",
            symbol=market_id,
            signal_type=SignalType.ENTRY,
            direction=direction,
            score=score,
            conviction=confidence,
            size_fraction=size_frac,
            strategy_type="calibration_arbitrage",
            price=float(market_price),
            stop_pct=0.0,  # Binary outcome, no stop
            target_pct=float(abs(model_estimate - market_price)),
            timeframe="event",
            regime="ANY",  # Polymarket is regime-independent
            timestamp=now,
            extra={
                "question": question,
                "model_estimate": float(model_estimate),
                "market_price": float(market_price),
                "edge": float(edge),
                "liquidity": float(liquidity),
            },
        )

    def get_regime(self) -> RegimeState:
        """Polymarket is largely regime-independent."""
        return RegimeState(
            regime="ANY",
            score=5.0,
            trend_strength=0.0,
            volatility_regime="normal",
        )

    def get_positions(self) -> list[PositionInfo]:
        """Get current Polymarket positions."""
        return []

    def execute(self, signal: Signal) -> dict[str, Any]:
        """Execute on Polymarket."""
        now = datetime.now(timezone.utc).isoformat()

        if self.config.get("paper_mode", True):
            return {
                "status": "paper_filled",
                "signal_id": signal.signal_id,
                "venue": "polymarket",
                "symbol": signal.symbol,
                "direction": signal.direction,
                "price": signal.price,
                "size_fraction": signal.size_fraction,
                "question": signal.extra.get("question", ""),
                "timestamp": now,
            }

        return {
            "status": "not_implemented",
            "message": "Live Polymarket execution not yet wired",
            "signal_id": signal.signal_id,
        }
