"""
Cross-Venue Orchestrator
========================
The brain that ties everything together. Runs all venue scanners in parallel,
ranks signals across ALL venues, allocates capital, and reports.

NO venue-specific logic lives here — it treats all scanners uniformly.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from src.registry import StrategyRegistry, StrategyStatus
from src.scanner.base import VenueScanner, Signal, SignalType, RegimeState, PositionInfo
from src.scanner.kraken import KrakenScanner
from src.scanner.hyperliquid import HyperliquidScanner
from src.scanner.jupiter import JupiterScanner
from src.scanner.polymarket import PolymarketScanner

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SCANNER_CLASSES = {
    "kraken": KrakenScanner,
    "hyperliquid": HyperliquidScanner,
    "jupiter": JupiterScanner,
    "polymarket": PolymarketScanner,
}


# ---------------------------------------------------------------------------
# Data Types
# ---------------------------------------------------------------------------

@dataclass
class VenueExposure:
    """Current exposure on a single venue."""
    venue: str
    open_positions: int
    notional_usd: float
    daily_pnl_pct: float = 0.0
    max_positions: int = 5
    limit_notional_usd: float = 0.0

    @property
    def position_utilization(self) -> float:
        if self.max_positions == 0:
            return 0.0
        return self.open_positions / self.max_positions

    @property
    def capital_utilization(self) -> float:
        if self.limit_notional_usd == 0:
            return 0.0
        return self.notional_usd / self.limit_notional_usd


@dataclass
class Allocation:
    """A signal that has been allocated capital."""
    signal: Signal
    allocated_fraction: float   # Fraction of total capital
    allocated_usd: float = 0.0
    reason: str = ""
    rank: int = 0


@dataclass
class ScanReport:
    """Full report from an orchestrator scan cycle."""
    timestamp: str
    signals_total: int
    signals_by_venue: dict[str, int]
    top_signals: list[Signal]
    allocations: list[Allocation]
    venue_exposures: dict[str, VenueExposure]
    portfolio_heat: dict[str, float]  # venue -> heat (0-1)
    regime_states: dict[str, str]
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 70,
            f"SCAN REPORT — {self.timestamp}",
            "=" * 70,
            "",
            f"Signals: {self.signals_total} total",
        ]
        for venue, count in self.signals_by_venue.items():
            lines.append(f"  {venue}: {count}")

        lines.append("")
        lines.append(f"Top Opportunities ({len(self.top_signals)}):")
        for i, sig in enumerate(self.top_signals[:10], 1):
            lines.append(
                f"  {i}. {sig.venue:12} {sig.symbol:15} {sig.direction:5} "
                f"score={sig.score:.2f} conv={sig.conviction:.2f} "
                f"combined={sig.combined_score:.3f} [{sig.strategy_type}]"
            )

        lines.append("")
        lines.append(f"Allocations ({len(self.allocations)}):")
        for alloc in self.allocations:
            lines.append(
                f"  #{alloc.rank} {alloc.signal.venue:12} {alloc.signal.symbol:15} "
                f"{alloc.allocated_fraction*100:.1f}% (${alloc.allocated_usd:.0f}) "
                f"— {alloc.reason}"
            )

        lines.append("")
        lines.append("Portfolio Heat:")
        for venue, heat in self.portfolio_heat.items():
            bar = "#" * int(heat * 20) + "-" * (20 - int(heat * 20))
            lines.append(f"  {venue:12} [{bar}] {heat*100:.0f}%")

        lines.append("")
        lines.append("Regime States:")
        for venue, regime in self.regime_states.items():
            lines.append(f"  {venue:12} {regime}")

        lines.append("")
        lines.append(f"Scan time: {self.elapsed_seconds:.2f}s")
        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class CrossVenueOrchestrator:
    """Runs all venue scanners, ranks signals, allocates capital."""

    def __init__(
        self,
        total_capital_usd: float = 10000,
        config_path: Path | None = None,
        registry: StrategyRegistry | None = None,
    ):
        self.total_capital_usd = total_capital_usd
        self.config_path = config_path or CONFIG_DIR / "venues.yaml"
        self.registry = registry or StrategyRegistry()
        self.scanners: dict[str, VenueScanner] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load venue configs and instantiate scanners."""
        with open(self.config_path) as f:
            raw = yaml.safe_load(f)

        for venue_name, venue_config in raw.items():
            if venue_name in SCANNER_CLASSES and venue_config.get("enabled", False):
                scanner_cls = SCANNER_CLASSES[venue_name]
                self.scanners[venue_name] = scanner_cls(venue_config)
                logger.info(f"Loaded scanner: {venue_name}")

    def scan_all(self, parallel: bool = True) -> ScanReport:
        """Run all scanners and return a full report.

        Args:
            parallel: Run scanners in parallel using ThreadPoolExecutor.

        Returns:
            ScanReport with ranked signals, allocations, and heat map.
        """
        import time
        start = time.time()

        all_signals: list[Signal] = []
        venue_signals: dict[str, list[Signal]] = {}
        regime_states: dict[str, str] = {}

        if parallel and len(self.scanners) > 1:
            with ThreadPoolExecutor(max_workers=len(self.scanners)) as pool:
                futures = {
                    pool.submit(scanner.scan): name
                    for name, scanner in self.scanners.items()
                }
                for future in as_completed(futures):
                    venue_name = futures[future]
                    try:
                        signals = future.result(timeout=30)
                        venue_signals[venue_name] = signals
                        all_signals.extend(signals)
                    except Exception as e:
                        logger.error(f"Scanner {venue_name} failed: {e}")
                        venue_signals[venue_name] = []

                # Get regimes (sequential, cheap)
                for name, scanner in self.scanners.items():
                    try:
                        regime_states[name] = scanner.get_regime().regime
                    except Exception:
                        regime_states[name] = "UNKNOWN"
        else:
            for name, scanner in self.scanners.items():
                try:
                    signals = scanner.scan()
                    venue_signals[name] = signals
                    all_signals.extend(signals)
                    regime_states[name] = scanner.get_regime().regime
                except Exception as e:
                    logger.error(f"Scanner {name} failed: {e}")
                    venue_signals[name] = []
                    regime_states[name] = "UNKNOWN"

        # Rank by combined score (score * conviction)
        all_signals.sort(key=lambda s: s.combined_score, reverse=True)

        # Match signals to registry strategies
        for sig in all_signals:
            self._match_registry(sig)

        # Get current exposures
        exposures = self._get_exposures()

        # Allocate capital
        allocations = self._allocate(all_signals, exposures)

        # Compute portfolio heat
        heat = self._compute_heat(exposures)

        elapsed = time.time() - start

        report = ScanReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            signals_total=len(all_signals),
            signals_by_venue={k: len(v) for k, v in venue_signals.items()},
            top_signals=all_signals[:20],
            allocations=allocations,
            venue_exposures=exposures,
            portfolio_heat=heat,
            regime_states=regime_states,
            elapsed_seconds=elapsed,
        )

        return report

    def _match_registry(self, signal: Signal) -> None:
        """Try to match a signal to a registry strategy."""
        # Search by venue + symbol + strategy type
        for entry in self.registry.get_by_venue(signal.venue):
            if (
                entry.symbol == signal.symbol
                and entry.strategy_type == signal.strategy_type
                and entry.status != StrategyStatus.KILLED
            ):
                signal.strategy_id = entry.strategy_id
                # Boost conviction if strategy is well-validated
                quality = entry.quality_score()
                signal.conviction = min(1.0, signal.conviction * (0.5 + quality * 0.5))
                return

    def _get_exposures(self) -> dict[str, VenueExposure]:
        """Get current exposure for each venue."""
        exposures = {}
        for name, scanner in self.scanners.items():
            positions = scanner.get_positions()
            notional = sum(abs(p.size * p.current_price) for p in positions)
            limit = scanner.risk_limits.get("max_position_notional_usd", 0)
            max_pos = scanner.max_positions()

            exposures[name] = VenueExposure(
                venue=name,
                open_positions=len(positions),
                notional_usd=notional,
                max_positions=max_pos,
                limit_notional_usd=limit * max_pos if limit > 0 else 0,
            )
        return exposures

    def _allocate(
        self,
        signals: list[Signal],
        exposures: dict[str, VenueExposure],
    ) -> list[Allocation]:
        """Allocate capital to top signals based on quality and exposure limits.

        Rules:
        - Max 30% of capital to any single venue
        - Max 10% to any single position
        - Reduce allocation if venue is >70% utilized
        - Skip venues in RISK_OFF regime
        """
        allocations: list[Allocation] = []
        venue_budget: dict[str, float] = {}
        max_venue_pct = 0.30
        max_position_pct = 0.10

        # Initialize budgets
        for name in self.scanners:
            venue_budget[name] = self.total_capital_usd * max_venue_pct

        rank = 0
        for signal in signals:
            rank += 1
            venue = signal.venue

            # Check venue budget
            if venue_budget.get(venue, 0) <= 0:
                continue

            # Check venue exposure
            exposure = exposures.get(venue)
            if exposure and exposure.position_utilization >= 1.0:
                continue

            # Skip if venue is in risk-off
            regime = self.scanners[venue].get_regime()
            if regime.regime == "RISK_OFF":
                continue

            # Size based on conviction and available budget
            base_alloc = min(
                signal.size_fraction * self.total_capital_usd,
                max_position_pct * self.total_capital_usd,
                venue_budget[venue],
            )

            # Reduce if venue is hot
            if exposure and exposure.position_utilization > 0.7:
                base_alloc *= 0.5

            # Scale by combined score
            final_alloc = base_alloc * min(1.0, signal.combined_score * 2)

            if final_alloc < 10:  # Skip tiny allocations
                continue

            reason = f"score={signal.score:.2f} conv={signal.conviction:.2f}"
            if signal.strategy_id:
                reason += f" [{signal.strategy_id}]"

            allocations.append(Allocation(
                signal=signal,
                allocated_fraction=final_alloc / self.total_capital_usd,
                allocated_usd=final_alloc,
                reason=reason,
                rank=rank,
            ))

            venue_budget[venue] -= final_alloc

        return allocations

    def _compute_heat(self, exposures: dict[str, VenueExposure]) -> dict[str, float]:
        """Compute portfolio heat (0-1) for each venue.

        Heat = max(position_utilization, capital_utilization)
        """
        heat = {}
        for name, exp in exposures.items():
            heat[name] = max(exp.position_utilization, exp.capital_utilization)
        return heat

    def get_top_opportunities(self, n: int = 10) -> list[Signal]:
        """Quick scan returning just the top N opportunities."""
        report = self.scan_all(parallel=True)
        return report.top_signals[:n]

    def execute_allocation(self, allocation: Allocation) -> dict[str, Any]:
        """Execute a single allocation."""
        scanner = self.scanners.get(allocation.signal.venue)
        if scanner is None:
            return {"status": "error", "message": f"No scanner for {allocation.signal.venue}"}

        return scanner.execute(allocation.signal)

    def execute_all(self, report: ScanReport) -> list[dict[str, Any]]:
        """Execute all allocations from a scan report."""
        results = []
        for alloc in report.allocations:
            result = self.execute_allocation(alloc)
            result["allocation"] = {
                "rank": alloc.rank,
                "fraction": alloc.allocated_fraction,
                "usd": alloc.allocated_usd,
            }
            results.append(result)
        return results

    def save_report(self, report: ScanReport, path: Path | None = None) -> Path:
        """Save scan report to JSON."""
        out_path = path or DATA_DIR / "latest_scan_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "timestamp": report.timestamp,
            "signals_total": report.signals_total,
            "signals_by_venue": report.signals_by_venue,
            "top_signals": [
                {
                    "signal_id": s.signal_id,
                    "venue": s.venue,
                    "symbol": s.symbol,
                    "direction": s.direction,
                    "score": s.score,
                    "conviction": s.conviction,
                    "combined_score": s.combined_score,
                    "strategy_type": s.strategy_type,
                    "strategy_id": s.strategy_id,
                    "price": s.price,
                    "stop_pct": s.stop_pct,
                    "target_pct": s.target_pct,
                }
                for s in report.top_signals[:20]
            ],
            "allocations": [
                {
                    "rank": a.rank,
                    "signal_id": a.signal.signal_id,
                    "venue": a.signal.venue,
                    "symbol": a.signal.symbol,
                    "direction": a.signal.direction,
                    "allocated_fraction": a.allocated_fraction,
                    "allocated_usd": a.allocated_usd,
                    "reason": a.reason,
                }
                for a in report.allocations
            ],
            "portfolio_heat": report.portfolio_heat,
            "regime_states": report.regime_states,
            "elapsed_seconds": report.elapsed_seconds,
        }

        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

        return out_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_scan(
    total_capital_usd: float = 10000,
    parallel: bool = True,
    verbose: bool = True,
) -> ScanReport:
    """Run a full cross-venue scan and return the report."""
    orchestrator = CrossVenueOrchestrator(total_capital_usd=total_capital_usd)
    report = orchestrator.scan_all(parallel=parallel)

    if verbose:
        print(report.summary())

    # Save report
    orchestrator.save_report(report)

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = run_scan()
