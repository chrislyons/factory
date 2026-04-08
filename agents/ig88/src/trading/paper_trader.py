"""Paper trading execution engine for IG-88.

Logs trades without submitting to real venues. Tracks positions, P&L,
stops, targets, and generates daily summaries for Matrix posting.

Usage:
    from src.trading.paper_trader import PaperTrader
    from src.trading.config import load_config

    cfg = load_config()
    trader = PaperTrader(cfg)
    trader.open_position(venue, pair, side, entry_price, size_usd, ...)
    trader.check_stops_and_targets(venue, pair, current_price)
    summary = trader.daily_summary()
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.quant.backtest_engine import (
    BacktestEngine,
    BacktestStats,
    ExitReason,
    Trade,
    TradeOutcome,
)
from src.quant.regime import RegimeAssessment, RegimeState, regime_allows_venue
from src.trading.config import TradingConfig, VenueConfig

logger = logging.getLogger(__name__)

# Default path for the paper trades log (relative to ig88 agent root)
_AGENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRADES_PATH = _AGENT_ROOT / "data" / "paper_trades.jsonl"


# ---------------------------------------------------------------------------
# Variance Drag Calculator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VarianceDragResult:
    """Output of variance drag analysis."""
    arithmetic_return: float
    geometric_return: float
    variance_drag: float
    passes: bool  # geometric_return > 0


def compute_variance_drag(per_trade_returns: list[float]) -> VarianceDragResult:
    """Compute variance drag from a list of per-trade returns.

    geometric_return = arithmetic_return - (sigma^2 / 2)

    Args:
        per_trade_returns: List of fractional returns (e.g. 0.05 = 5%).

    Returns:
        VarianceDragResult with arithmetic, geometric, drag, and pass/fail.
    """
    if len(per_trade_returns) < 2:
        arith = float(np.mean(per_trade_returns)) if per_trade_returns else 0.0
        return VarianceDragResult(
            arithmetic_return=arith,
            geometric_return=arith,
            variance_drag=0.0,
            passes=arith > 0,
        )

    arr = np.array(per_trade_returns, dtype=np.float64)
    arith = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=0))  # population std (matches backtest_engine)
    drag = (sigma ** 2) / 2.0
    geo = arith - drag

    return VarianceDragResult(
        arithmetic_return=arith,
        geometric_return=geo,
        variance_drag=drag,
        passes=geo > 0,
    )


# ---------------------------------------------------------------------------
# Trade Logger
# ---------------------------------------------------------------------------

class TradeLogger:
    """Appends trade records to a JSONL file and formats Graphiti episodes."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_TRADES_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_trade(self, trade: Trade) -> None:
        """Append a single trade record as a JSON line."""
        record = trade.to_dict()
        record["logged_at"] = datetime.now(tz=timezone.utc).isoformat()
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        logger.info("Logged trade %s to %s", trade.trade_id, self.path)

    def read_trades(self) -> list[dict[str, Any]]:
        """Read all trade records from the JSONL file."""
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def graphiti_episode(self, trade: Trade) -> dict[str, Any]:
        """Format a trade as a Graphiti episode dict for memory storage.

        This produces a structured episode that can be stored via
        mcp__graphiti__add_memory(content=json.dumps(episode), group_id="trading").
        """
        outcome_str = trade.outcome.value if trade.outcome else "open"
        pnl_str = f"${trade.pnl_usd:+.2f}" if trade.pnl_usd is not None else "open"

        content_parts = [
            f"Paper trade {trade.trade_id}: {trade.side} {trade.pair} on {trade.venue}",
            f"Entry: ${trade.entry_price:.6f} | Size: ${trade.position_size_usd:.2f}",
            f"Strategy: {trade.strategy} | Regime: {trade.regime_state.value}",
        ]
        if trade.exit_price is not None:
            content_parts.append(
                f"Exit: ${trade.exit_price:.6f} | P&L: {pnl_str} | Outcome: {outcome_str}"
            )
            if trade.exit_reason:
                content_parts.append(f"Exit reason: {trade.exit_reason.value}")
            if trade.r_multiple is not None:
                content_parts.append(f"R-multiple: {trade.r_multiple:+.2f}R")

        return {
            "name": f"paper_trade_{trade.trade_id}",
            "group_id": "trading",
            "content": " | ".join(content_parts),
            "source": "paper_trader",
            "source_description": "IG-88 paper trading engine",
            "metadata": {
                "trade_id": trade.trade_id,
                "venue": trade.venue,
                "pair": trade.pair,
                "outcome": outcome_str,
                "pnl_usd": trade.pnl_usd,
            },
        }


# ---------------------------------------------------------------------------
# Position Tracker
# ---------------------------------------------------------------------------

class PositionTracker:
    """In-memory tracker for open positions, daily P&L, and trade counts."""

    def __init__(self):
        self.open_positions: list[Trade] = []
        self._closed_today: list[Trade] = []
        self._opened_today: list[Trade] = []
        self._trade_count_today: dict[str, int] = {}  # venue -> count
        self._day: str = self._today_str()

    @staticmethod
    def _today_str() -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    def _maybe_roll_day(self) -> None:
        """Reset daily counters if the UTC day has changed."""
        today = self._today_str()
        if today != self._day:
            self._closed_today.clear()
            self._opened_today.clear()
            self._trade_count_today.clear()
            self._day = today

    def add_position(self, trade: Trade) -> None:
        """Add a newly opened position."""
        self._maybe_roll_day()
        self.open_positions.append(trade)
        self._opened_today.append(trade)
        venue = trade.venue
        self._trade_count_today[venue] = self._trade_count_today.get(venue, 0) + 1

    def remove_position(self, trade_id: str) -> Trade | None:
        """Remove a position by trade_id. Returns the Trade or None."""
        self._maybe_roll_day()
        for i, t in enumerate(self.open_positions):
            if t.trade_id == trade_id:
                removed = self.open_positions.pop(i)
                self._closed_today.append(removed)
                return removed
        return None

    def get_position(self, trade_id: str) -> Trade | None:
        """Look up an open position by trade_id."""
        for t in self.open_positions:
            if t.trade_id == trade_id:
                return t
        return None

    def positions_for_venue(self, venue: str) -> list[Trade]:
        """Return all open positions for a given venue."""
        return [t for t in self.open_positions if t.venue == venue]

    def positions_for_pair(self, venue: str, pair: str) -> list[Trade]:
        """Return open positions for a specific venue+pair."""
        return [t for t in self.open_positions if t.venue == venue and t.pair == pair]

    def open_count(self, venue: str) -> int:
        """Number of open positions on a venue."""
        return len(self.positions_for_venue(venue))

    def trades_today(self, venue: str) -> int:
        """Number of trades opened today on a venue."""
        self._maybe_roll_day()
        return self._trade_count_today.get(venue, 0)

    def unrealized_pnl(self, trade: Trade, current_price: float) -> float:
        """Compute unrealized P&L in USD for a single position."""
        if trade.side in ("long", "buy_yes"):
            raw_pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        elif trade.side in ("short", "sell_yes", "buy_no", "sell_no"):
            raw_pnl_pct = (trade.entry_price - current_price) / trade.entry_price
        else:
            raw_pnl_pct = (current_price - trade.entry_price) / trade.entry_price

        leveraged_pnl_pct = raw_pnl_pct * trade.leverage
        return leveraged_pnl_pct * trade.position_size_usd

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Compute total unrealized P&L across all open positions.

        Args:
            prices: Mapping of "{venue}:{pair}" -> current_price.
        """
        total = 0.0
        for t in self.open_positions:
            key = f"{t.venue}:{t.pair}"
            if key in prices:
                total += self.unrealized_pnl(t, prices[key])
        return total

    def realized_pnl_today(self) -> float:
        """Sum of realized P&L from trades closed today."""
        self._maybe_roll_day()
        return sum(
            t.pnl_usd for t in self._closed_today if t.pnl_usd is not None
        )

    def daily_drawdown_pct(self, portfolio_value: float) -> float:
        """Today's realized drawdown as a percentage of portfolio value.

        Returns a positive number representing loss (0.05 = 5% drawdown).
        """
        if portfolio_value <= 0:
            return 0.0
        realized = self.realized_pnl_today()
        if realized >= 0:
            return 0.0
        return abs(realized) / portfolio_value

    def is_drawdown_halt(
        self, portfolio_value: float, halt_pct: float
    ) -> bool:
        """Check if daily drawdown has breached the halt threshold."""
        return self.daily_drawdown_pct(portfolio_value) >= halt_pct

    @property
    def closed_today(self) -> list[Trade]:
        self._maybe_roll_day()
        return list(self._closed_today)

    @property
    def opened_today(self) -> list[Trade]:
        self._maybe_roll_day()
        return list(self._opened_today)


# ---------------------------------------------------------------------------
# Daily Summary
# ---------------------------------------------------------------------------

@dataclass
class DailySummary:
    """End-of-day paper trading summary, formatted for Matrix posting."""
    date: str
    trades_opened: int
    trades_closed: int
    realized_pnl_usd: float
    open_positions: list[dict[str, Any]]
    total_unrealized_pnl_usd: float
    win_rate: float
    expectancy: float
    expectancy_r: float
    total_trades_all_time: int
    regime_state: str
    regime_score: float
    variance_drag: VarianceDragResult | None
    portfolio_value_usd: float
    daily_drawdown_pct: float

    def to_markdown(self) -> str:
        """Render the summary as a markdown string for Matrix."""
        lines = [
            f"## Paper Trading Summary - {self.date}",
            "",
            "### Activity",
            f"- Trades opened today: **{self.trades_opened}**",
            f"- Trades closed today: **{self.trades_closed}**",
            f"- Realized P&L today: **${self.realized_pnl_usd:+.2f}**",
            f"- Daily drawdown: **{self.daily_drawdown_pct:.2%}**",
            f"- Portfolio value: **${self.portfolio_value_usd:,.2f}**",
            "",
            "### Regime",
            f"- State: **{self.regime_state}**",
            f"- Score: **{self.regime_score:.1f}/10**",
            "",
        ]

        # Open positions table
        if self.open_positions:
            lines.append("### Open Positions")
            lines.append("")
            lines.append("| Venue | Pair | Side | Entry | Unrealized P&L |")
            lines.append("|-------|------|------|-------|---------------|")
            for pos in self.open_positions:
                lines.append(
                    f"| {pos['venue']} | {pos['pair']} | {pos['side']} "
                    f"| ${pos['entry_price']:.6f} | ${pos['unrealized_pnl']:+.2f} |"
                )
            lines.append(f"\n**Total unrealized: ${self.total_unrealized_pnl_usd:+.2f}**")
            lines.append("")
        else:
            lines.append("### Open Positions")
            lines.append("_No open positions._")
            lines.append("")

        # Running statistics
        lines.append("### Running Statistics")
        lines.append(f"- Total trades (all time): **{self.total_trades_all_time}**")
        lines.append(f"- Win rate: **{self.win_rate:.1%}**")
        lines.append(
            f"- Expectancy: **{self.expectancy:.4f}** per trade "
            f"(**{self.expectancy_r:.2f}R**)"
        )

        if self.variance_drag is not None:
            vd = self.variance_drag
            status = "PASS" if vd.passes else "FAIL"
            lines.append(f"- Arithmetic return: **{vd.arithmetic_return:.6f}**")
            lines.append(f"- Geometric return: **{vd.geometric_return:.6f}** ({status})")
            lines.append(f"- Variance drag: **{vd.variance_drag:.6f}**")

        lines.append("")
        lines.append("---")
        lines.append("_Generated by IG-88 paper trading engine._")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Paper Trader (main class)
# ---------------------------------------------------------------------------

class PaperTrader:
    """Paper trading execution engine.

    Manages positions, enforces guardrails, checks stops/targets,
    and produces daily summaries. No real orders are ever submitted.
    """

    def __init__(
        self,
        config: TradingConfig,
        portfolio_value: float = 10_000.0,
        trades_path: Path | None = None,
    ):
        self.config = config
        self.portfolio_value = portfolio_value
        self.tracker = PositionTracker()
        self.trade_logger = TradeLogger(path=trades_path)
        self.engine = BacktestEngine(initial_capital=portfolio_value)
        self._regime: RegimeAssessment | None = None

    # -- Regime --

    def set_regime(self, assessment: RegimeAssessment) -> None:
        """Update the current regime assessment."""
        self._regime = assessment

    @property
    def regime(self) -> RegimeAssessment | None:
        return self._regime

    # -- Guardrail Checks --

    def _check_regime_gate(self, venue: str) -> tuple[bool, str]:
        """Check if the regime allows opening positions on this venue."""
        if self._regime is None:
            return False, "No regime assessment available; defaulting to RISK_OFF"
        if not regime_allows_venue(self._regime, venue):
            return (
                False,
                f"Regime {self._regime.state.value} (score={self._regime.score:.1f}) "
                f"does not allow new positions on {venue}",
            )
        return True, ""

    def _check_position_limits(self, venue: str) -> tuple[bool, str]:
        """Check if the venue has room for another position."""
        vcfg = self.config.get_venue(venue)
        current = self.tracker.open_count(venue)
        if current >= vcfg.max_open_positions:
            return (
                False,
                f"Max open positions ({vcfg.max_open_positions}) reached on {venue} "
                f"(currently {current})",
            )
        # Daily new-position limit
        if vcfg.max_new_positions_day > 0:
            today_count = self.tracker.trades_today(venue)
            if today_count >= vcfg.max_new_positions_day:
                return (
                    False,
                    f"Max new positions per day ({vcfg.max_new_positions_day}) reached "
                    f"on {venue} (today: {today_count})",
                )
        return True, ""

    def _check_drawdown_halt(self) -> tuple[bool, str]:
        """Check if daily drawdown halt has been triggered."""
        halt_pct = self.config.risk.daily_drawdown_halt_pct / 100.0
        if self.tracker.is_drawdown_halt(self.portfolio_value, halt_pct):
            dd = self.tracker.daily_drawdown_pct(self.portfolio_value)
            return (
                False,
                f"Daily drawdown halt triggered: {dd:.2%} >= {halt_pct:.2%} threshold",
            )
        return True, ""

    def _check_jupiter_perps_guardrails(
        self,
        venue_cfg: VenueConfig,
        leverage: float,
        stop_level: float | None,
        target_level: float | None,
        entry_price: float,
        expected_move_pct: float | None,
    ) -> tuple[bool, str]:
        """Jupiter Perps specific guardrails."""
        # Leverage cap
        max_lev = venue_cfg.leverage.get("max", 5)
        if leverage > max_lev:
            return False, f"Leverage {leverage}x exceeds max {max_lev}x for jupiter_perps"

        # TP/SL required
        if venue_cfg.tp_sl_required:
            if stop_level is None:
                return False, "Stop-loss required for jupiter_perps"
            if target_level is None:
                return False, "Take-profit required for jupiter_perps"

        # Minimum expected move check (edge_threshold from config)
        if expected_move_pct is not None:
            min_edge = venue_cfg.edge_threshold
            if abs(expected_move_pct) < min_edge:
                return (
                    False,
                    f"Expected move {expected_move_pct:.2%} below minimum "
                    f"edge threshold {min_edge:.2%} for jupiter_perps",
                )

        return True, ""

    # -- Open Position --

    def open_position(
        self,
        venue: str,
        pair: str,
        side: str,
        entry_price: float,
        position_size_usd: float,
        strategy: str,
        stop_level: float | None = None,
        target_level: float | None = None,
        leverage: float = 1.0,
        expected_move_pct: float | None = None,
        llm_estimate: float | None = None,
        market_price: float | None = None,
        narrative_category: str | None = None,
        notes: str = "",
    ) -> tuple[Trade | None, str]:
        """Open a paper position.

        Returns (Trade, "") on success or (None, reason) on rejection.
        """
        # Regime gate
        ok, reason = self._check_regime_gate(venue)
        if not ok:
            logger.warning("Position rejected (regime): %s", reason)
            return None, reason

        # Drawdown halt
        ok, reason = self._check_drawdown_halt()
        if not ok:
            logger.warning("Position rejected (drawdown): %s", reason)
            return None, reason

        # Position limits
        ok, reason = self._check_position_limits(venue)
        if not ok:
            logger.warning("Position rejected (limits): %s", reason)
            return None, reason

        # Venue config
        vcfg = self.config.get_venue(venue)

        # Jupiter Perps specific
        if venue == "jupiter_perps":
            ok, reason = self._check_jupiter_perps_guardrails(
                vcfg, leverage, stop_level, target_level,
                entry_price, expected_move_pct,
            )
            if not ok:
                logger.warning("Position rejected (jupiter_perps): %s", reason)
                return None, reason

        # Build trade
        trade_id = f"paper_{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=timezone.utc)
        regime_state = self._regime.state if self._regime else RegimeState.RISK_OFF

        trade = Trade(
            trade_id=trade_id,
            venue=venue,
            strategy=strategy,
            pair=pair,
            entry_timestamp=now,
            entry_price=entry_price,
            position_size_usd=position_size_usd,
            regime_state=regime_state,
            side=side,
            leverage=leverage,
            stop_level=stop_level,
            target_level=target_level,
            llm_estimate=llm_estimate,
            market_price=market_price,
            narrative_category=narrative_category,
            notes=notes,
        )

        self.tracker.add_position(trade)
        self.engine.add_trade(trade)
        self.trade_logger.log_trade(trade)

        logger.info(
            "Opened paper %s %s on %s @ $%.6f (size=$%.2f, lev=%.1fx) [%s]",
            side, pair, venue, entry_price, position_size_usd, leverage, trade_id,
        )
        return trade, ""

    # -- Close Position --

    def close_position(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: ExitReason,
        fees: float = 0.0,
        borrow_fees: float = 0.0,
    ) -> tuple[Trade | None, str]:
        """Close a paper position.

        Returns (Trade, "") on success or (None, reason) on failure.
        """
        trade = self.tracker.get_position(trade_id)
        if trade is None:
            return None, f"No open position with trade_id={trade_id}"

        now = datetime.now(tz=timezone.utc)
        trade.close(
            exit_price=exit_price,
            exit_timestamp=now,
            exit_reason=exit_reason,
            fees=fees,
            borrow_fees=borrow_fees,
        )

        self.tracker.remove_position(trade_id)
        self.trade_logger.log_trade(trade)

        # Update portfolio value with realized P&L
        if trade.pnl_usd is not None:
            self.portfolio_value += trade.pnl_usd

        logger.info(
            "Closed paper %s %s on %s @ $%.6f -> P&L: $%+.2f (%s) [%s]",
            trade.side, trade.pair, trade.venue, exit_price,
            trade.pnl_usd or 0.0, exit_reason.value, trade_id,
        )
        return trade, ""

    # -- Stop/Target Checking --

    def check_stops_and_targets(
        self,
        venue: str,
        pair: str,
        current_price: float,
    ) -> list[Trade]:
        """Check all open positions for a venue+pair against current price.

        Closes positions that hit their stop or target. Also enforces
        Jupiter Perps borrow fee auto-close and min hold time.

        Call this on every price update.

        Returns list of trades that were closed.
        """
        closed: list[Trade] = []
        positions = self.tracker.positions_for_pair(venue, pair)
        now = datetime.now(tz=timezone.utc)

        for trade in list(positions):  # copy — we mutate during iteration
            # Min hold time check
            vcfg = self.config.get_venue(venue)
            if vcfg.min_hold_hours > 0:
                elapsed = (now - trade.entry_timestamp).total_seconds() / 3600.0
                if elapsed < vcfg.min_hold_hours:
                    continue  # Too early to close

            hit_stop = False
            hit_target = False

            if trade.side in ("long", "buy_yes"):
                if trade.stop_level is not None and current_price <= trade.stop_level:
                    hit_stop = True
                if trade.target_level is not None and current_price >= trade.target_level:
                    hit_target = True
            elif trade.side in ("short", "sell_yes", "buy_no", "sell_no"):
                if trade.stop_level is not None and current_price >= trade.stop_level:
                    hit_stop = True
                if trade.target_level is not None and current_price <= trade.target_level:
                    hit_target = True

            # Jupiter Perps: borrow fee auto-close
            # If cumulative borrow fees exceed a threshold (5% of position),
            # auto-close to prevent fee bleed.
            borrow_fee_close = False
            borrow_fees_accrued = 0.0
            if venue == "jupiter_perps" and vcfg.fees.borrow_rate_hourly:
                elapsed_hours = (now - trade.entry_timestamp).total_seconds() / 3600.0
                # Estimate borrow fees: hourly rate * position * leverage * hours
                hourly_rate = vcfg.fees.taker_pct / 100.0  # reuse taker as borrow proxy
                if hourly_rate <= 0:
                    hourly_rate = 0.001  # default 0.1% per hour
                borrow_fees_accrued = (
                    hourly_rate * trade.position_size_usd * trade.leverage * elapsed_hours
                )
                # Auto-close if borrow fees exceed 5% of position
                if borrow_fees_accrued > trade.position_size_usd * 0.05:
                    borrow_fee_close = True

            # Determine exit
            exit_reason: ExitReason | None = None
            fees = self._estimate_close_fees(trade)

            if hit_stop:
                exit_reason = ExitReason.STOP_HIT
            elif hit_target:
                exit_reason = ExitReason.TARGET_HIT
            elif borrow_fee_close:
                exit_reason = ExitReason.BORROW_FEE

            if exit_reason is not None:
                result, _ = self.close_position(
                    trade_id=trade.trade_id,
                    exit_price=current_price,
                    exit_reason=exit_reason,
                    fees=fees,
                    borrow_fees=borrow_fees_accrued if venue == "jupiter_perps" else 0.0,
                )
                if result is not None:
                    closed.append(result)

        return closed

    def check_regime_exits(self) -> list[Trade]:
        """Close all positions on venues that no longer allow trading
        under the current regime. Call after updating the regime."""
        if self._regime is None:
            return []

        closed: list[Trade] = []
        for trade in list(self.tracker.open_positions):
            if not regime_allows_venue(self._regime, trade.venue):
                fees = self._estimate_close_fees(trade)
                # Use entry price as exit (conservative -- in real life we'd
                # use current market price, but we don't have it here)
                result, _ = self.close_position(
                    trade_id=trade.trade_id,
                    exit_price=trade.entry_price,
                    exit_reason=ExitReason.REGIME_EXIT,
                    fees=fees,
                )
                if result is not None:
                    closed.append(result)
                    logger.warning(
                        "Regime exit: closed %s %s on %s (regime=%s)",
                        trade.side, trade.pair, trade.venue,
                        self._regime.state.value,
                    )
        return closed

    def _estimate_close_fees(self, trade: Trade) -> float:
        """Estimate closing fees for a trade based on venue config."""
        try:
            vcfg = self.config.get_venue(trade.venue)
        except KeyError:
            return 0.0

        # Use taker fee for market close, or round-trip if defined
        if vcfg.fees.round_trip_pct > 0:
            # round_trip covers open + close; halve it for close only
            return (vcfg.fees.round_trip_pct / 100.0) * trade.position_size_usd / 2.0
        if vcfg.fees.taker_pct > 0:
            return (vcfg.fees.taker_pct / 100.0) * trade.position_size_usd
        if vcfg.fees.open_close_pct > 0:
            return (vcfg.fees.open_close_pct / 100.0) * trade.position_size_usd
        return 0.0

    # -- Daily Summary --

    def daily_summary(
        self,
        prices: dict[str, float] | None = None,
    ) -> DailySummary:
        """Generate a daily summary of paper trading activity.

        Args:
            prices: Current prices as "{venue}:{pair}" -> price.
                Used for unrealized P&L. Positions without a price
                entry are shown with $0 unrealized.
        """
        prices = prices or {}

        # Compute running stats from all closed trades
        closed = self.engine.closed_trades()
        stats: BacktestStats | None = None
        if closed:
            stats = self.engine.compute_stats()

        # Open positions with unrealized P&L
        open_pos_info: list[dict[str, Any]] = []
        total_unrealized = 0.0
        for t in self.tracker.open_positions:
            key = f"{t.venue}:{t.pair}"
            cp = prices.get(key, t.entry_price)
            upnl = self.tracker.unrealized_pnl(t, cp)
            total_unrealized += upnl
            open_pos_info.append({
                "trade_id": t.trade_id,
                "venue": t.venue,
                "pair": t.pair,
                "side": t.side,
                "entry_price": t.entry_price,
                "current_price": cp,
                "unrealized_pnl": upnl,
                "leverage": t.leverage,
                "stop_level": t.stop_level,
                "target_level": t.target_level,
            })

        # Variance drag
        returns = [t.pnl_pct for t in closed if t.pnl_pct is not None]
        vd = compute_variance_drag(returns) if returns else None

        regime_state = self._regime.state.value if self._regime else "UNKNOWN"
        regime_score = self._regime.score if self._regime else 0.0

        dd_pct = self.tracker.daily_drawdown_pct(self.portfolio_value)

        return DailySummary(
            date=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            trades_opened=len(self.tracker.opened_today),
            trades_closed=len(self.tracker.closed_today),
            realized_pnl_usd=self.tracker.realized_pnl_today(),
            open_positions=open_pos_info,
            total_unrealized_pnl_usd=total_unrealized,
            win_rate=stats.win_rate if stats else 0.0,
            expectancy=stats.expectancy_per_trade if stats else 0.0,
            expectancy_r=stats.expectancy_r if stats else 0.0,
            total_trades_all_time=stats.n_trades if stats else 0,
            regime_state=regime_state,
            regime_score=regime_score,
            variance_drag=vd,
            portfolio_value_usd=self.portfolio_value,
            daily_drawdown_pct=dd_pct,
        )


# ---------------------------------------------------------------------------
# __main__ demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Build a minimal TradingConfig in memory (no YAML file needed for demo)
    from src.trading.config import (
        FeesConfig,
        GraduationConfig,
        KillCriteria,
        RegimeConfig,
        RiskConfig,
        TradingConfig,
        VenueConfig,
    )

    risk = RiskConfig(
        kelly_fraction=0.25,
        kelly_fraction_graduated=0.5,
        max_position_pct=10.0,
        daily_drawdown_halt_pct=3.0,
        daily_drawdown_review_pct=1.5,
        max_portfolio_drawdown_pct=15.0,
        auto_execute_threshold_usd=500.0,
    )
    regime_cfg = RegimeConfig(
        risk_off_max=3,
        neutral_max=6,
        weights={
            "btc_trend": 0.25,
            "total_mcap_trend": 0.10,
            "fear_greed_index": 0.15,
            "funding_rates": 0.15,
            "stablecoin_flows": 0.10,
            "btc_dominance_delta": 0.10,
            "volatility_regime": 0.15,
        },
    )
    kraken_fees = FeesConfig(maker_pct=0.16, taker_pct=0.26)
    jupiter_fees = FeesConfig(
        open_close_pct=0.06, taker_pct=0.1, borrow_rate_hourly=True,
    )
    venues = {
        "kraken_spot": VenueConfig(
            enabled=True, effort_pct=30, paper_mode=True,
            pairs=["SOL/USD", "BTC/USD"],
            strategies=["momentum"],
            fees=kraken_fees,
            max_open_positions=3,
            min_hold_hours=0.5,
            max_new_positions_day=5,
        ),
        "jupiter_perps": VenueConfig(
            enabled=True, effort_pct=25, paper_mode=True,
            pairs=["SOL-PERP", "BTC-PERP"],
            strategies=["trend_following"],
            fees=jupiter_fees,
            max_open_positions=2,
            leverage={"default": 3, "max": 5},
            tp_sl_required=True,
            edge_threshold=0.03,
        ),
    }
    graduation = GraduationConfig(
        min_trades=100, positive_expectancy=True, significance_p=0.05,
        geometric_return_positive=True, max_paper_drawdown_pct=15.0,
        brier_target=0.25, greed_guardrails_verified=True,
        chris_approval_required=True,
    )
    kill = KillCriteria(
        negative_expectancy_trades=50, variance_drag_fail=True,
        consecutive_drawdown_halts=3, drawdown_halt_window_days=7,
    )
    cfg = TradingConfig(
        risk=risk, regime=regime_cfg, venues=venues,
        graduation=graduation, kill_criteria=kill,
    )

    # Use a temp file for the demo JSONL
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    trades_path = Path(tmp.name)

    trader = PaperTrader(cfg, portfolio_value=10_000.0, trades_path=trades_path)

    # Set regime to RISK_ON so trades are allowed
    from src.quant.regime import RegimeAssessment, RegimeSignal, RegimeState

    regime = RegimeAssessment(
        state=RegimeState.RISK_ON,
        score=7.5,
        signals=[
            RegimeSignal(name="btc_trend", value=5.2, score=7.6, weight=0.25),
            RegimeSignal(name="fear_greed_index", value=68.0, score=6.8, weight=0.15),
        ],
        timestamp=datetime.now(tz=timezone.utc),
        confidence=0.85,
    )
    trader.set_regime(regime)

    # --- Demo trades ---

    print("\n=== Opening Positions ===\n")

    # 1. Kraken SOL/USD long
    t1, msg = trader.open_position(
        venue="kraken_spot", pair="SOL/USD", side="long",
        entry_price=145.20, position_size_usd=500.0,
        strategy="momentum", stop_level=138.0, target_level=160.0,
        notes="Demo: SOL momentum breakout",
    )
    if t1:
        print(f"Opened: {t1.trade_id} | {t1.side} {t1.pair} @ ${t1.entry_price}")
    else:
        print(f"Rejected: {msg}")

    # 2. Jupiter SOL-PERP long with leverage
    t2, msg = trader.open_position(
        venue="jupiter_perps", pair="SOL-PERP", side="long",
        entry_price=145.00, position_size_usd=300.0,
        strategy="trend_following", stop_level=140.0, target_level=155.0,
        leverage=3.0, expected_move_pct=0.07,
        notes="Demo: SOL perp trend follow",
    )
    if t2:
        print(f"Opened: {t2.trade_id} | {t2.side} {t2.pair} @ ${t2.entry_price} (3x)")
    else:
        print(f"Rejected: {msg}")

    # 3. Try opening a jupiter position with too much leverage (should be rejected)
    t3, msg = trader.open_position(
        venue="jupiter_perps", pair="BTC-PERP", side="long",
        entry_price=68000.0, position_size_usd=200.0,
        strategy="trend_following", stop_level=66000.0, target_level=72000.0,
        leverage=10.0, expected_move_pct=0.06,
        notes="Demo: should be rejected - leverage too high",
    )
    if t3:
        print(f"Opened: {t3.trade_id}")
    else:
        print(f"Rejected (expected): {msg}")

    # --- Price updates: check stops and targets ---

    print("\n=== Price Updates ===\n")

    # SOL pumps to target on Kraken
    closed = trader.check_stops_and_targets("kraken_spot", "SOL/USD", 161.50)
    for c in closed:
        print(
            f"Closed (target): {c.trade_id} | {c.pair} | "
            f"P&L: ${c.pnl_usd:+.2f} | R: {c.r_multiple:+.2f}"
        )

    # SOL-PERP hits stop
    closed = trader.check_stops_and_targets("jupiter_perps", "SOL-PERP", 139.50)
    for c in closed:
        print(
            f"Closed (stop): {c.trade_id} | {c.pair} | "
            f"P&L: ${c.pnl_usd:+.2f} | R: {c.r_multiple:+.2f}"
        )

    # --- Variance Drag ---

    print("\n=== Variance Drag ===\n")
    sample_returns = [0.03, -0.01, 0.05, -0.02, 0.04, -0.03, 0.02, 0.01]
    vd = compute_variance_drag(sample_returns)
    print(f"Arithmetic: {vd.arithmetic_return:.6f}")
    print(f"Geometric:  {vd.geometric_return:.6f}")
    print(f"Drag:       {vd.variance_drag:.6f}")
    print(f"Passes:     {vd.passes}")

    # --- Daily Summary ---

    print("\n=== Daily Summary ===\n")
    prices = {
        "kraken_spot:SOL/USD": 161.50,
        "jupiter_perps:SOL-PERP": 139.50,
    }
    summary = trader.daily_summary(prices=prices)
    print(summary.to_markdown())

    # --- Trade log ---

    print(f"\n=== Trade Log ({trades_path}) ===\n")
    records = trader.trade_logger.read_trades()
    for r in records:
        status = r.get("outcome", "?")
        pnl = r.get("pnl_usd")
        pnl_str = f"${pnl:+.2f}" if pnl is not None else "open"
        print(f"  {r['trade_id']} | {r['venue']}:{r['pair']} | {status} | {pnl_str}")

    # Cleanup temp file
    trades_path.unlink(missing_ok=True)

    print("\nDone.")
