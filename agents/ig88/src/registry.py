"""
Strategy Registry
=================
Central registry for all validated strategies across all venues.
Each strategy is venue-agnostic at the registry level — the same ATR BO
strategy can run on any perps venue. Venue-specific details live in
the scanner implementations.

Data is persisted to data/strategy_registry.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "strategy_registry.json"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StrategyStatus(str, Enum):
    VALIDATED = "validated"    # Passed walk-forward, ready for paper
    PAPER = "paper"            # Currently paper trading
    LIVE = "live"              # Live with real capital
    KILLED = "killed"          # Stopped — negative expectancy or other failure


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    BOTH = "both"  # Strategy can go either direction


# ---------------------------------------------------------------------------
# Core Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationMetrics:
    """Metrics from walk-forward validation and cross-symbol testing."""
    profit_factor: float = 0.0          # Gross profit / gross loss
    win_rate: float = 0.0               # Fraction of winning trades
    splits_passed: int = 0              # Number of WF splits that passed
    splits_total: int = 0               # Total WF splits tested
    cross_symbol_score: float = 0.0     # 0-1 score from cross-symbol validation
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    expectancy_pct: float = 0.0         # Expected return per trade after friction
    total_trades: int = 0
    geometric_return: float = 0.0       # Log return accounting for variance drag

    @property
    def splits_pass_rate(self) -> float:
        if self.splits_total == 0:
            return 0.0
        return self.splits_passed / self.splits_total


@dataclass
class StrategyEntry:
    """A single strategy record in the registry."""
    strategy_id: str                    # Unique identifier: "{strategy_type}_{venue}_{symbol}"
    strategy_type: str                  # E.g., "atr_breakout", "mr_rsi_bb", "h3_ichimoku"
    venue: str                          # hyperliquid, kraken, jupiter, polymarket
    symbol: str                         # Venue-specific symbol (e.g., "SOL-PERP", "SOL/USDT")
    direction: Direction = Direction.LONG
    timeframe: str = "4h"              # Primary timeframe
    params: dict[str, Any] = field(default_factory=dict)
    validation_metrics: ValidationMetrics = field(default_factory=ValidationMetrics)
    status: StrategyStatus = StrategyStatus.VALIDATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""

    def quality_score(self) -> float:
        """Composite quality score for ranking (0-1). Higher is better."""
        vm = self.validation_metrics
        # Weighted composite: PF * 0.3 + WR * 0.2 + splits * 0.2 + cross * 0.15 + sharpe * 0.15
        pf_score = min(vm.profit_factor / 3.0, 1.0) if vm.profit_factor > 0 else 0.0
        wr_score = vm.win_rate
        splits_score = vm.splits_pass_rate
        cross_score = vm.cross_symbol_score
        sharpe_score = min(max(vm.sharpe_ratio, 0) / 2.0, 1.0)
        return (
            pf_score * 0.30
            + wr_score * 0.20
            + splits_score * 0.20
            + cross_score * 0.15
            + sharpe_score * 0.15
        )

    def is_allocatable(self) -> bool:
        """Check if this strategy is eligible for capital allocation."""
        return (
            self.status in (StrategyStatus.VALIDATED, StrategyStatus.PAPER, StrategyStatus.LIVE)
            and self.quality_score() > 0.3
            and self.validation_metrics.profit_factor > 1.0
            and self.validation_metrics.splits_pass_rate >= 0.6
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class StrategyRegistry:
    """In-memory + JSON-persisted strategy registry."""

    def __init__(self, path: Path | None = None):
        self.path = path or REGISTRY_PATH
        self.entries: dict[str, StrategyEntry] = {}
        self._load()

    # -- Persistence --

    def _load(self) -> None:
        """Load registry from JSON file."""
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                raw = json.load(f)
            for item in raw.get("strategies", []):
                entry = self._deserialize(item)
                self.entries[entry.strategy_id] = entry
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Failed to load registry from {self.path}: {e}")

    def save(self) -> None:
        """Persist current registry to JSON."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "strategies": [self._serialize(e) for e in self.entries.values()],
        }
        with open(self.path, "w") as f:
            json.dump(payload, f, indent=2)

    @staticmethod
    def _serialize(entry: StrategyEntry) -> dict:
        d = asdict(entry)
        d["direction"] = entry.direction.value
        d["status"] = entry.status.value
        d["validation_metrics"] = asdict(entry.validation_metrics)
        return d

    @staticmethod
    def _deserialize(data: dict) -> StrategyEntry:
        vm_data = data.get("validation_metrics", {})
        vm = ValidationMetrics(**vm_data)
        return StrategyEntry(
            strategy_id=data["strategy_id"],
            strategy_type=data["strategy_type"],
            venue=data["venue"],
            symbol=data["symbol"],
            direction=Direction(data.get("direction", "long")),
            timeframe=data.get("timeframe", "4h"),
            params=data.get("params", {}),
            validation_metrics=vm,
            status=StrategyStatus(data.get("status", "validated")),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            notes=data.get("notes", ""),
        )

    # -- CRUD --

    def add(self, entry: StrategyEntry) -> None:
        """Add or update a strategy entry."""
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        self.entries[entry.strategy_id] = entry

    def remove(self, strategy_id: str) -> bool:
        """Remove a strategy by ID. Returns True if found."""
        return self.entries.pop(strategy_id, None) is not None

    def get(self, strategy_id: str) -> Optional[StrategyEntry]:
        return self.entries.get(strategy_id)

    def kill(self, strategy_id: str, reason: str = "") -> bool:
        """Mark a strategy as killed."""
        entry = self.entries.get(strategy_id)
        if entry is None:
            return False
        entry.status = StrategyStatus.KILLED
        entry.notes = f"KILLED: {reason}" if reason else "KILLED"
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def promote(self, strategy_id: str, new_status: StrategyStatus) -> bool:
        """Promote a strategy to a new status."""
        entry = self.entries.get(strategy_id)
        if entry is None:
            return False
        entry.status = new_status
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    # -- Query Methods --

    def all_entries(self) -> list[StrategyEntry]:
        return list(self.entries.values())

    def get_by_venue(self, venue: str) -> list[StrategyEntry]:
        """Get all strategies for a given venue."""
        return [e for e in self.entries.values() if e.venue == venue]

    def get_by_status(self, status: StrategyStatus) -> list[StrategyEntry]:
        """Get all strategies with a given status."""
        return [e for e in self.entries.values() if e.status == status]

    def get_by_type(self, strategy_type: str) -> list[StrategyEntry]:
        """Get all strategies of a given type."""
        return [e for e in self.entries.values() if e.strategy_type == strategy_type]

    def get_by_symbol(self, symbol: str, venue: str | None = None) -> list[StrategyEntry]:
        """Get strategies for a symbol, optionally filtered by venue."""
        results = [e for e in self.entries.values() if e.symbol == symbol]
        if venue:
            results = [e for e in results if e.venue == venue]
        return results

    def get_top_n(self, n: int = 10, venue: str | None = None,
                  min_status: StrategyStatus | None = None) -> list[StrategyEntry]:
        """Get top N strategies by quality score, optionally filtered."""
        entries = list(self.entries.values())
        if venue:
            entries = [e for e in entries if e.venue == venue]
        if min_status:
            # Include strategies at or above this status level
            status_order = [StrategyStatus.VALIDATED, StrategyStatus.PAPER,
                           StrategyStatus.LIVE, StrategyStatus.KILLED]
            min_idx = status_order.index(min_status)
            entries = [e for e in entries if status_order.index(e.status) <= min_idx]
        entries.sort(key=lambda e: e.quality_score(), reverse=True)
        return entries[:n]

    def get_allocatable(self, venue: str | None = None) -> list[StrategyEntry]:
        """Get strategies eligible for capital allocation."""
        entries = [e for e in self.entries.values() if e.is_allocatable()]
        if venue:
            entries = [e for e in entries if e.venue == venue]
        entries.sort(key=lambda e: e.quality_score(), reverse=True)
        return entries

    def get_active(self) -> list[StrategyEntry]:
        """Get all strategies that are paper or live (actively trading)."""
        return [
            e for e in self.entries.values()
            if e.status in (StrategyStatus.PAPER, StrategyStatus.LIVE)
        ]

    # -- Stats --

    def venue_summary(self) -> dict[str, dict]:
        """Summary stats grouped by venue."""
        summary: dict[str, dict] = {}
        for e in self.entries.values():
            if e.venue not in summary:
                summary[e.venue] = {"total": 0, "validated": 0, "paper": 0, "live": 0, "killed": 0}
            summary[e.venue]["total"] += 1
            summary[e.venue][e.status.value] += 1
        return summary

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:
        return f"StrategyRegistry(entries={len(self.entries)}, path={self.path})"
