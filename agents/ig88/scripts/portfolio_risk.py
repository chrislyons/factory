#!/usr/bin/env python3
"""
Portfolio Risk Manager for IG-88 ATR Breakout System.
Computes portfolio-level metrics, drawdown tracking, and leverage scaling.

Key functions:
1. Portfolio-level Value at Risk (VaR)
2. Drawdown-based leverage scaling (reduce when underwater)
3. Correlation-adjusted position sizing
4. Risk budget enforcement
"""

import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
STATE_DIR = BASE_DIR / "data" / "risk_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


# === CORRELATION MATRIX (from backtest) ===
# Pre-computed from 2yr daily returns (pearson r)
CORR_MATRIX = {
    "ETH":  {"ETH": 1.00, "AVAX": 0.82, "LINK": 0.78, "NEAR": 0.75, "SOL": 0.80, "SUI": 0.72, "FIL": 0.68, "RNDR": 0.65, "WLD": 0.62},
    "AVAX": {"ETH": 0.82, "AVAX": 1.00, "LINK": 0.76, "NEAR": 0.80, "SOL": 0.83, "SUI": 0.78, "FIL": 0.70, "RNDR": 0.67, "WLD": 0.64},
    "LINK": {"ETH": 0.78, "AVAX": 0.76, "LINK": 1.00, "NEAR": 0.73, "SOL": 0.75, "SUI": 0.70, "FIL": 0.66, "RNDR": 0.63, "WLD": 0.60},
    "NEAR": {"ETH": 0.75, "AVAX": 0.80, "LINK": 0.73, "NEAR": 1.00, "SOL": 0.78, "SUI": 0.82, "FIL": 0.72, "RNDR": 0.68, "WLD": 0.65},
    "SOL":  {"ETH": 0.80, "AVAX": 0.83, "LINK": 0.75, "NEAR": 0.78, "SOL": 1.00, "SUI": 0.80, "FIL": 0.71, "RNDR": 0.66, "WLD": 0.63},
    "SUI":  {"ETH": 0.72, "AVAX": 0.78, "LINK": 0.70, "NEAR": 0.82, "SOL": 0.80, "SUI": 1.00, "FIL": 0.74, "RNDR": 0.69, "WLD": 0.66},
    "FIL":  {"ETH": 0.68, "AVAX": 0.70, "LINK": 0.66, "NEAR": 0.72, "SOL": 0.71, "SUI": 0.74, "FIL": 1.00, "RNDR": 0.62, "WLD": 0.58},
    "RNDR": {"ETH": 0.65, "AVAX": 0.67, "LINK": 0.63, "NEAR": 0.68, "SOL": 0.66, "SUI": 0.69, "FIL": 0.62, "RNDR": 1.00, "WLD": 0.70},
    "WLD":  {"ETH": 0.62, "AVAX": 0.64, "LINK": 0.60, "NEAR": 0.65, "SOL": 0.63, "SUI": 0.66, "FIL": 0.58, "RNDR": 0.70, "WLD": 1.00},
}

ASSETS = ["ETH", "AVAX", "LINK", "NEAR", "SOL", "SUI", "FIL", "RNDR", "WLD"]


def compute_portfolio_var(positions: dict, confidence: float = 0.95) -> dict:
    """
    Compute portfolio-level VaR considering correlations.
    
    positions: {asset: {"size_usd": float, "atr": float, "direction": str}}
    Returns: {"portfolio_var_pct": float, "component_var": dict}
    """
    if not positions:
        return {"portfolio_var_pct": 0, "component_var": {}}

    # Build weight vector and individual VaR
    weights = {}
    individual_vars = {}
    total_exposure = sum(abs(p["size_usd"]) for p in positions.values())

    if total_exposure == 0:
        return {"portfolio_var_pct": 0, "component_var": {}}

    for asset, pos in positions.items():
        w = abs(pos["size_usd"]) / total_exposure
        weights[asset] = w
        # 95% VaR ≈ 1.645 * ATR as daily loss estimate
        atr_pct = pos["atr"] / pos.get("price", 1)
        individual_vars[asset] = 1.645 * atr_pct

    # Portfolio VaR = sqrt(w' * Cov * w)
    # Simplified: use correlation-adjusted variance
    portfolio_var_sq = 0
    for a1 in weights:
        for a2 in weights:
            corr = CORR_MATRIX.get(a1, {}).get(a2, 0.5)
            portfolio_var_sq += weights[a1] * weights[a2] * individual_vars[a1] * individual_vars[a2] * corr

    portfolio_var = np.sqrt(portfolio_var_sq)

    return {
        "portfolio_var_pct": portfolio_var * 100,
        "individual_vars": {k: v * 100 for k, v in individual_vars.items()},
        "weights": weights,
        "total_exposure_usd": total_exposure,
    }


def compute_leverage_scaling(current_dd_pct: float, 
                              initial_leverage: float = 2.0) -> float:
    """
    Scale leverage based on current drawdown.
    Reduces leverage as drawdown increases to protect capital.
    
    Formula: leverage = initial * max(0.5, 1 - dd/max_dd)
    Where max_dd = 50% (our accepted risk ceiling)
    """
    MAX_DD = 0.50  # 50% max accepted drawdown

    if current_dd_pct >= MAX_DD:
        return 0.0  # Kill switch — stop trading

    scaling = max(0.5, 1 - (current_dd_pct / MAX_DD))
    return round(initial_leverage * scaling, 2)


def compute_position_size_kelly(asset: str, portfolio_value: float, 
                                  leverage: float, win_rate: float = 0.40,
                                  avg_win: float = 0.035, avg_loss: float = 0.015) -> float:
    """
    Kelly-criterion position sizing with correlation adjustment.
    
    Kelly fraction = (bp - q) / b
    where b = avg_win/avg_loss, p = win_rate, q = 1-win_rate
    
    Then adjust for correlation: reduce allocation for highly correlated assets.
    """
    b = avg_win / avg_loss  # odds ratio
    kelly = (b * win_rate - (1 - win_rate)) / b
    kelly = max(0, kelly)  # No negative Kelly

    # Half-Kelly for safety
    kelly_half = kelly * 0.5

    # Correlation adjustment: average correlation with other assets in portfolio
    avg_corr = 0
    corr_count = 0
    for other in ASSETS:
        if other != asset and other in CORR_MATRIX.get(asset, {}):
            avg_corr += CORR_MATRIX[asset][other]
            corr_count += 1
    
    if corr_count > 0:
        avg_corr /= corr_count
        # High correlation → reduce allocation
        corr_adj = 1 - (avg_corr * 0.3)  # At avg_corr=0.75 → 0.775x
    else:
        corr_adj = 1.0

    # Final size
    position_pct = kelly_half * leverage * corr_adj
    position_pct = min(position_pct, 0.15)  # Cap at 15%

    return round(portfolio_value * position_pct, 2)


def risk_report(portfolio_value: float, positions: dict, 
                peak_value: float = None) -> dict:
    """
    Generate comprehensive risk report.
    
    positions: {asset: {"size_usd": float, "atr": float, "direction": str, "price": float}}
    """
    if peak_value is None:
        peak_value = portfolio_value

    current_dd = (peak_value - portfolio_value) / peak_value if peak_value > 0 else 0
    leverage = compute_leverage_scaling(current_dd)

    var_result = compute_portfolio_var(positions)

    # Total exposure check
    total_exposure = sum(abs(p.get("size_usd", 0)) for p in positions.values())
    exposure_ratio = total_exposure / portfolio_value if portfolio_value > 0 else 0

    # Position concentration
    max_position = max((abs(p.get("size_usd", 0)) for p in positions.values()), default=0)
    concentration = max_position / portfolio_value if portfolio_value > 0 else 0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio_value": portfolio_value,
        "peak_value": peak_value,
        "current_drawdown_pct": round(current_dd * 100, 2),
        "allowed_leverage": leverage,
        "portfolio_var_pct": var_result["portfolio_var_pct"],
        "total_exposure_usd": total_exposure,
        "exposure_ratio": round(exposure_ratio * 100, 1),
        "max_position_usd": max_position,
        "concentration_pct": round(concentration * 100, 1),
        "num_positions": len(positions),
        "risk_flags": [],
    }

    # Risk flags
    if current_dd > 0.30:
        report["risk_flags"].append("DRAWDOWN_WARNING: >30% DD, leverage reduced")
    if current_dd > 0.45:
        report["risk_flags"].append("DRAWDOWN_CRITICAL: approaching 50% kill switch")
    if exposure_ratio > 1.0:
        report["risk_flags"].append("OVER_EXPOSED: total exposure >100% of portfolio")
    if concentration > 0.20:
        report["risk_flags"].append("CONCENTRATION: single position >20% of portfolio")
    if var_result["portfolio_var_pct"] > 10:
        report["risk_flags"].append("HIGH_VAR: portfolio daily VaR >10%")

    return report


def save_risk_report(report: dict):
    """Save risk report to disk."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = STATE_DIR / f"risk_report_{date_str}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)


# === DEMO ===
if __name__ == "__main__":
    # Example: $10K portfolio, 3 open positions
    demo_positions = {
        "ETH": {"size_usd": 1500, "atr": 15.57, "direction": "LONG", "price": 2359},
        "SOL": {"size_usd": 1200, "atr": 0.62, "direction": "LONG", "price": 85.45},
        "AVAX": {"size_usd": 1000, "atr": 0.084, "direction": "SHORT", "price": 9.51},
    }

    portfolio_value = 10000
    peak_value = 12000  # Down from peak

    report = risk_report(portfolio_value, demo_positions, peak_value)

    print("=== Portfolio Risk Report ===")
    print(f"Portfolio: ${report['portfolio_value']:,.0f}")
    print(f"Peak: ${report['peak_value']:,.0f}")
    print(f"Drawdown: {report['current_drawdown_pct']:.1f}%")
    print(f"Allowed leverage: {report['allowed_leverage']}x")
    print(f"Portfolio VaR (95%): {report['portfolio_var_pct']:.2f}%")
    print(f"Total exposure: ${report['total_exposure_usd']:,.0f} ({report['exposure_ratio']:.0f}%)")
    print(f"Max position: ${report['max_position_usd']:,.0f} ({report['concentration_pct']:.0f}%)")
    print(f"Positions: {report['num_positions']}")
    if report['risk_flags']:
        print(f"\nRISK FLAGS:")
        for flag in report['risk_flags']:
            print(f"  ⚠️  {flag}")
    else:
        print(f"\n✓ No risk flags")

    # Kelly sizing examples
    print("\n=== Kelly Position Sizing (correlation-adjusted) ===")
    for asset in ["ETH", "SOL", "FIL", "SUI"]:
        size = compute_position_size_kelly(asset, portfolio_value, report['allowed_leverage'])
        pct = size / portfolio_value * 100
        print(f"  {asset:5s}: ${size:,.0f} ({pct:.1f}%)")

    save_risk_report(report)
