"""Trading configuration loader and validator.

Loads config/trading.yaml and provides typed access to all trading parameters.
Pairs lists are parameterized — update the YAML to change tracked instruments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trading.yaml"


@dataclass
class RiskConfig:
    kelly_fraction: float
    kelly_fraction_graduated: float
    max_position_pct: float
    daily_drawdown_halt_pct: float
    daily_drawdown_review_pct: float
    max_portfolio_drawdown_pct: float
    auto_execute_threshold_usd: float


@dataclass
class RegimeConfig:
    risk_off_max: int
    neutral_max: int
    weights: dict[str, float]


@dataclass
class FeesConfig:
    maker_pct: float = 0.0
    taker_pct: float = 0.0
    prefer_limit_orders: bool = True
    open_close_pct: float = 0.0
    round_trip_pct: float = 0.0
    borrow_rate_hourly: bool = False


@dataclass
class VenueConfig:
    enabled: bool
    effort_pct: int
    paper_mode: bool
    pairs: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    fees: FeesConfig = field(default_factory=FeesConfig)
    max_open_positions: int = 5
    min_hold_hours: float = 0
    max_hold_hours: float = 0
    scan_interval_minutes: int = 5
    edge_threshold: float = 0.05
    confidence_min: float = 0.6
    leverage: dict[str, int] = field(default_factory=dict)
    tp_sl_required: bool = False
    phase: str = "paper_trading"
    liquidity_min_usd: float = 0
    max_new_positions_day: int = 0
    narrative_categories: dict[str, Any] = field(default_factory=dict)
    # Extra fields stored but not typed
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraduationConfig:
    min_trades: int
    positive_expectancy: bool
    significance_p: float
    geometric_return_positive: bool
    max_paper_drawdown_pct: float
    brier_target: float
    greed_guardrails_verified: bool
    chris_approval_required: bool


@dataclass
class KillCriteria:
    negative_expectancy_trades: int
    variance_drag_fail: bool
    consecutive_drawdown_halts: int
    drawdown_halt_window_days: int


@dataclass
class TradingConfig:
    risk: RiskConfig
    regime: RegimeConfig
    venues: dict[str, VenueConfig]
    graduation: GraduationConfig
    kill_criteria: KillCriteria

    def get_venue(self, name: str) -> VenueConfig:
        """Get venue config by name. Raises KeyError if not found."""
        return self.venues[name]

    def enabled_venues(self) -> dict[str, VenueConfig]:
        """Return only enabled venues."""
        return {k: v for k, v in self.venues.items() if v.enabled}

    def pairs_for_venue(self, name: str) -> list[str]:
        """Get the pairs list for a venue."""
        return self.venues[name].pairs


def _parse_fees(raw: dict[str, Any] | None) -> FeesConfig:
    if not raw:
        return FeesConfig()
    return FeesConfig(
        maker_pct=raw.get("maker_pct", 0.0),
        taker_pct=raw.get("taker_pct", 0.0),
        prefer_limit_orders=raw.get("prefer_limit_orders", True),
        open_close_pct=raw.get("open_close_pct", 0.0),
        round_trip_pct=raw.get("round_trip_pct", 0.0),
        borrow_rate_hourly=raw.get("borrow_rate_hourly", False),
    )


def _parse_venue(raw: dict[str, Any]) -> VenueConfig:
    known = {
        "enabled", "effort_pct", "paper_mode", "pairs", "strategies",
        "fees", "max_open_positions", "min_hold_hours", "max_hold_hours",
        "scan_interval_minutes", "edge_threshold", "confidence_min",
        "leverage", "tp_sl_required", "phase", "liquidity_min_usd",
        "max_new_positions_day", "narrative_categories",
    }
    extra = {k: v for k, v in raw.items() if k not in known}
    return VenueConfig(
        enabled=raw.get("enabled", False),
        effort_pct=raw.get("effort_pct", 0),
        paper_mode=raw.get("paper_mode", True),
        pairs=raw.get("pairs", []),
        strategies=raw.get("strategies", []),
        fees=_parse_fees(raw.get("fees")),
        max_open_positions=raw.get("max_open_positions", 5),
        min_hold_hours=raw.get("min_hold_hours", 0),
        max_hold_hours=raw.get("max_hold_hours", 0),
        scan_interval_minutes=raw.get("scan_interval_minutes", 5),
        edge_threshold=raw.get("edge_threshold", 0.05),
        confidence_min=raw.get("confidence_min", 0.6),
        leverage=raw.get("leverage", {}),
        tp_sl_required=raw.get("tp_sl_required", False),
        phase=raw.get("phase", "paper_trading"),
        liquidity_min_usd=raw.get("liquidity_min_usd", 0),
        max_new_positions_day=raw.get("max_new_positions_day", 0),
        narrative_categories=raw.get("narrative_categories", {}),
        extra=extra,
    )


def load_config(path: Path | None = None) -> TradingConfig:
    """Load and validate trading configuration from YAML."""
    config_path = path or CONFIG_PATH
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    risk = RiskConfig(
        kelly_fraction=raw["risk"]["kelly_fraction"],
        kelly_fraction_graduated=raw["risk"]["kelly_fraction_graduated"],
        max_position_pct=raw["risk"]["max_position_pct"],
        daily_drawdown_halt_pct=raw["risk"]["daily_drawdown_halt_pct"],
        daily_drawdown_review_pct=raw["risk"]["daily_drawdown_review_pct"],
        max_portfolio_drawdown_pct=raw["risk"]["max_portfolio_drawdown_pct"],
        auto_execute_threshold_usd=raw["risk"]["auto_execute_threshold_usd"],
    )

    regime = RegimeConfig(
        risk_off_max=raw["regime"]["risk_off_max"],
        neutral_max=raw["regime"]["neutral_max"],
        weights=raw["regime"]["weights"],
    )

    venues = {
        name: _parse_venue(venue_raw)
        for name, venue_raw in raw["venues"].items()
    }

    graduation = GraduationConfig(
        min_trades=raw["graduation"]["min_trades"],
        positive_expectancy=raw["graduation"]["positive_expectancy"],
        significance_p=raw["graduation"]["significance_p"],
        geometric_return_positive=raw["graduation"]["geometric_return_positive"],
        max_paper_drawdown_pct=raw["graduation"]["max_paper_drawdown_pct"],
        brier_target=raw["graduation"]["brier_target"],
        greed_guardrails_verified=raw["graduation"]["greed_guardrails_verified"],
        chris_approval_required=raw["graduation"]["chris_approval_required"],
    )

    kill = KillCriteria(
        negative_expectancy_trades=raw["kill_criteria"]["negative_expectancy_trades"],
        variance_drag_fail=raw["kill_criteria"]["variance_drag_fail"],
        consecutive_drawdown_halts=raw["kill_criteria"]["consecutive_drawdown_halts"],
        drawdown_halt_window_days=raw["kill_criteria"]["drawdown_halt_window_days"],
    )

    # Validate regime weights sum to ~1.0
    w_sum = sum(regime.weights.values())
    if abs(w_sum - 1.0) > 0.01:
        raise ValueError(f"Regime weights sum to {w_sum}, expected 1.0")

    return TradingConfig(
        risk=risk,
        regime=regime,
        venues=venues,
        graduation=graduation,
        kill_criteria=kill,
    )
