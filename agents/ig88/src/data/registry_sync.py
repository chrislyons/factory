"""
Registry Sync
=============
Keeps strategy_registry.json in sync with validation results.

When new validation results come in (from walk-forward, cross-symbol tests,
or live trading), this module updates the registry accordingly:
- New strategies from validation results get registered
- Existing strategies get updated metrics
- Strategies hitting kill criteria get killed automatically
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.registry import (
    StrategyRegistry, StrategyEntry, StrategyStatus,
    Direction, ValidationMetrics,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def sync_from_validation_results(
    registry: StrategyRegistry,
    results_path: Path | None = None,
) -> int:
    """Sync registry with walk-forward validation results.

    Looks for JSON files in data/ that contain validation results.
    Format expected: list of dicts with strategy info and metrics.

    Returns number of entries added/updated.
    """
    count = 0

    # Scan data directory for validation result files
    result_files = []
    if results_path and results_path.exists():
        result_files = [results_path]
    else:
        # Look for common validation result files
        patterns = [
            "atr_hardening.json",
            "aggressive_v3.json",
            "deep_dive_results.json",
            "combo_research_results.json",
            "cross_asset_results.json",
            "walk_forward_results.json",
            "validation_results.json",
        ]
        for p in patterns:
            path = DATA_DIR / p
            if path.exists():
                result_files.append(path)

    for path in result_files:
        try:
            count += _process_result_file(registry, path)
        except Exception as e:
            logger.warning(f"Failed to process {path}: {e}")

    return count


def _process_result_file(registry: StrategyRegistry, path: Path) -> int:
    """Process a single validation results file."""
    with open(path) as f:
        data = json.load(f)

    count = 0

    # Handle different result formats
    if isinstance(data, list):
        for item in data:
            if _process_result_item(registry, item):
                count += 1
    elif isinstance(data, dict):
        # Could be a nested dict with results
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and _process_result_item(registry, item):
                        count += 1
            elif isinstance(value, dict) and _looks_like_result(value):
                if _process_result_item(registry, value):
                    count += 1

    return count


def _looks_like_result(d: dict) -> bool:
    """Check if a dict looks like a validation result."""
    metric_keys = {"profit_factor", "win_rate", "pf", "wr", "expectancy", "sharpe"}
    return bool(set(d.keys()) & metric_keys)


def _process_result_item(registry: StrategyRegistry, item: dict) -> bool:
    """Process a single result item and add/update registry entry.

    Returns True if an entry was added or updated.
    """
    # Extract strategy identification
    strategy_type = item.get("strategy_type") or item.get("strategy") or item.get("type", "unknown")
    venue = item.get("venue", "unknown")
    symbol = item.get("symbol") or item.get("pair", "unknown")

    if symbol == "unknown" or venue == "unknown":
        return False

    # Generate strategy ID
    strategy_id = f"{strategy_type}_{venue}_{symbol}".lower().replace(" ", "_")

    # Extract metrics
    vm = _extract_metrics(item)

    # Determine status
    status = _determine_status(item, vm)

    # Check if entry exists
    existing = registry.get(strategy_id)
    if existing:
        # Update if new metrics are better
        if vm.profit_factor > existing.validation_metrics.profit_factor:
            existing.validation_metrics = vm
            existing.status = status
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    # Create new entry
    direction_str = item.get("direction", "long")
    direction = Direction(direction_str) if direction_str in ("long", "short", "both") else Direction.LONG

    entry = StrategyEntry(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        venue=venue,
        symbol=symbol,
        direction=direction,
        timeframe=item.get("timeframe", "4h"),
        params=item.get("params", {}),
        validation_metrics=vm,
        status=status,
        notes=f"Imported from {item.get('_source', 'validation')}",
    )

    registry.add(entry)
    return True


def _extract_metrics(item: dict) -> ValidationMetrics:
    """Extract validation metrics from a result item."""
    return ValidationMetrics(
        profit_factor=float(item.get("profit_factor", item.get("pf", 0)) or 0),
        win_rate=float(item.get("win_rate", item.get("wr", 0)) or 0),
        splits_passed=int(item.get("splits_passed", item.get("passing_splits", 0)) or 0),
        splits_total=int(item.get("splits_total", item.get("total_splits", 0)) or 0),
        cross_symbol_score=float(item.get("cross_symbol_score", item.get("cross_score", 0)) or 0),
        sharpe_ratio=float(item.get("sharpe_ratio", item.get("sharpe", 0)) or 0),
        max_drawdown_pct=float(item.get("max_drawdown_pct", item.get("max_dd", 0)) or 0),
        expectancy_pct=float(item.get("expectancy_pct", item.get("expectancy", 0)) or 0),
        total_trades=int(item.get("total_trades", item.get("trades", 0)) or 0),
        geometric_return=float(item.get("geometric_return", item.get("geo_return", 0)) or 0),
    )


def _determine_status(item: dict, vm: ValidationMetrics) -> StrategyStatus:
    """Determine strategy status from result metrics.

    Rules:
    - Explicit status in item takes precedence
    - Otherwise: PF > 1.0 + splits_passed > 60% -> VALIDATED
    - Otherwise: VALIDATED anyway if it has a PF (lower quality)
    """
    explicit = item.get("status")
    if explicit:
        try:
            return StrategyStatus(explicit)
        except ValueError:
            pass

    if vm.profit_factor > 1.0 and vm.splits_pass_rate >= 0.6:
        return StrategyStatus.VALIDATED

    return StrategyStatus.VALIDATED


def sync_kill_criteria(
    registry: StrategyRegistry,
    kill_config: dict[str, Any] | None = None,
) -> list[str]:
    """Check active strategies against kill criteria.

    Args:
        registry: The strategy registry
        kill_config: Kill criteria config dict. If None, uses defaults.

    Returns:
        List of strategy_ids that were killed.
    """
    if kill_config is None:
        kill_config = {
            "negative_expectancy_trades": 200,
            "variance_drag_fail": True,
            "max_drawdown_pct": 30.0,
            "min_profit_factor": 0.8,
        }

    killed = []
    min_trades = kill_config.get("negative_expectancy_trades", 200)
    max_dd = kill_config.get("max_drawdown_pct", 30.0)
    min_pf = kill_config.get("min_profit_factor", 0.8)

    for entry in registry.get_active():
        vm = entry.validation_metrics
        reason = None

        # Kill if negative expectancy after enough trades
        if vm.total_trades >= min_trades and vm.profit_factor < min_pf:
            reason = f"PF={vm.profit_factor:.2f} after {vm.total_trades} trades"

        # Kill if geometric return is negative (variance drag)
        if kill_config.get("variance_drag_fail") and vm.geometric_return < 0 and vm.total_trades >= 50:
            reason = f"Negative geometric return: {vm.geometric_return:.4f}"

        # Kill if max drawdown exceeded
        if vm.max_drawdown_pct > max_dd:
            reason = f"Max DD {vm.max_drawdown_pct:.1f}% > {max_dd}%"

        if reason:
            registry.kill(entry.strategy_id, reason)
            killed.append(entry.strategy_id)
            logger.info(f"Killed strategy {entry.strategy_id}: {reason}")

    return killed


def full_sync(registry: StrategyRegistry | None = None) -> StrategyRegistry:
    """Run a full synchronization cycle.

    1. Load validation results into registry
    2. Check kill criteria
    3. Save registry

    Returns the updated registry.
    """
    if registry is None:
        registry = StrategyRegistry()

    added = sync_from_validation_results(registry)
    killed = sync_kill_criteria(registry)
    registry.save()

    logger.info(f"Registry sync: {added} added/updated, {len(killed)} killed, {len(registry)} total")

    return registry


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    registry = full_sync()
    print(f"\nRegistry: {registry}")
    print(f"Venue summary: {registry.venue_summary()}")
