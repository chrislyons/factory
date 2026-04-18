"""
Autonomous Scan Loop
====================
Runs the CrossVenueOrchestrator scan every 4 hours.
Saves reports to data/scans/YYYY-MM-DD_HH.json.
Tracks signals found, signals executed, and P&L changes.

Usage:
  python scripts/scan_loop.py              # Run as persistent process (default)
  python scripts/scan_loop.py --once       # Run a single scan and exit
  python scripts/scan_loop.py --interval 2 # Scan every 2 hours instead of 4

Can also be scheduled via cron:
  0 */4 * * * cd /Users/nesbitt/dev/factory/agents/ig88 && .venv/bin/python3 scripts/scan_loop.py --once
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.orchestrator import CrossVenueOrchestrator, ScanReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scan_loop")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SCANS_DIR = DATA_DIR / "scans"
TRACKER_FILE = DATA_DIR / "scan_loop_tracker.json"

# Graceful shutdown
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

def load_tracker() -> dict:
    """Load scan loop tracking state."""
    if TRACKER_FILE.exists():
        try:
            with open(TRACKER_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return {
        "total_scans": 0,
        "total_signals_found": 0,
        "total_signals_executed": 0,
        "last_scan": None,
        "last_report_path": None,
        "pnl_history": [],
    }


def save_tracker(tracker: dict) -> None:
    """Persist tracking state."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker, f, indent=2)


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------

def save_scan_report(report: ScanReport, tracker: dict) -> Path:
    """Save a scan report to the dated scans directory."""
    SCANS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    filename = f"{now.strftime('%Y-%m-%d_%H')}.json"
    out_path = SCANS_DIR / filename

    # Build full report data
    report_data = {
        "timestamp": report.timestamp,
        "signals_total": report.signals_total,
        "signals_by_venue": report.signals_by_venue,
        "top_signals": [
            {
                "signal_id": s.signal_id,
                "venue": s.venue,
                "symbol": s.symbol,
                "direction": s.direction,
                "score": round(s.score, 4),
                "conviction": round(s.conviction, 4),
                "combined_score": round(s.combined_score, 4),
                "strategy_type": s.strategy_type,
                "strategy_id": s.strategy_id,
                "price": s.price,
                "stop_pct": s.stop_pct,
                "target_pct": s.target_pct,
                "regime": s.regime,
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
                "allocated_fraction": round(a.allocated_fraction, 4),
                "allocated_usd": round(a.allocated_usd, 2),
                "reason": a.reason,
            }
            for a in report.allocations
        ],
        "portfolio_heat": report.portfolio_heat,
        "regime_states": report.regime_states,
        "elapsed_seconds": round(report.elapsed_seconds, 3),
        "scan_number": tracker["total_scans"] + 1,
    }

    with open(out_path, "w") as f:
        json.dump(report_data, f, indent=2)

    return out_path


# ---------------------------------------------------------------------------
# Single scan
# ---------------------------------------------------------------------------

def run_single_scan(
    total_capital_usd: float = 10000,
    tracker: dict | None = None,
) -> ScanReport:
    """Execute one scan cycle and update the tracker."""
    if tracker is None:
        tracker = load_tracker()

    logger.info(f"Starting scan #{tracker['total_scans'] + 1}...")

    orchestrator = CrossVenueOrchestrator(total_capital_usd=total_capital_usd)
    report = orchestrator.scan_all(parallel=True)

    # Save report
    report_path = save_scan_report(report, tracker)
    logger.info(f"Report saved to {report_path}")

    # Update tracker
    tracker["total_scans"] += 1
    tracker["total_signals_found"] += report.signals_total
    tracker["last_scan"] = report.timestamp
    tracker["last_report_path"] = str(report_path)

    # Track allocation count
    alloc_count = len(report.allocations)
    tracker["total_signals_executed"] += alloc_count

    # Track P&L snapshot (notional heat as proxy)
    pnl_snapshot = {
        "timestamp": report.timestamp,
        "signals": report.signals_total,
        "allocations": alloc_count,
        "portfolio_heat": report.portfolio_heat,
    }
    tracker["pnl_history"].append(pnl_snapshot)

    # Keep last 500 P&L snapshots
    if len(tracker["pnl_history"]) > 500:
        tracker["pnl_history"] = tracker["pnl_history"][-500:]

    save_tracker(tracker)

    # Log summary
    logger.info(
        f"Scan complete: {report.signals_total} signals, "
        f"{alloc_count} allocations, {report.elapsed_seconds:.2f}s"
    )
    for venue, count in report.signals_by_venue.items():
        regime = report.regime_states.get(venue, "?")
        heat = report.portfolio_heat.get(venue, 0)
        logger.info(
            f"  {venue}: {count} signals, regime={regime}, heat={heat*100:.0f}%"
        )

    if report.top_signals:
        logger.info("Top opportunities:")
        for i, sig in enumerate(report.top_signals[:5], 1):
            logger.info(
                f"  {i}. {sig.venue}:{sig.symbol} {sig.direction} "
                f"score={sig.score:.2f} combined={sig.combined_score:.3f}"
            )

    return report


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(
    interval_hours: float = 4.0,
    total_capital_usd: float = 10000,
) -> None:
    """Run scans in a loop every interval_hours."""
    interval_seconds = interval_hours * 3600
    tracker = load_tracker()

    logger.info(f"=== IG-88 Autonomous Scan Loop ===")
    logger.info(f"Interval: {interval_hours} hours")
    logger.info(f"Capital: ${total_capital_usd:,.0f}")
    logger.info(f"Scans dir: {SCANS_DIR}")
    logger.info(f"Previous scans: {tracker['total_scans']}")
    logger.info("Press Ctrl+C to stop.")
    logger.info("")

    while not _shutdown:
        try:
            run_single_scan(total_capital_usd, tracker)
        except Exception as e:
            logger.error(f"Scan failed: {e}", exc_info=True)

        if _shutdown:
            break

        # Sleep in small increments to allow graceful shutdown
        next_scan = time.time() + interval_seconds
        logger.info(
            f"Next scan at {datetime.fromtimestamp(next_scan, tz=timezone.utc).strftime('%H:%M:%S UTC')}"
        )
        while time.time() < next_scan and not _shutdown:
            time.sleep(min(60, next_scan - time.time()))

    logger.info("Scan loop stopped.")
    logger.info(f"Session summary: {tracker['total_scans']} total scans, "
                f"{tracker['total_signals_found']} signals found")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="IG-88 Autonomous Scan Loop")
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single scan and exit (for cron scheduling)",
    )
    parser.add_argument(
        "--interval", type=float, default=4.0,
        help="Hours between scans (default: 4)",
    )
    parser.add_argument(
        "--capital", type=float, default=10000,
        help="Total capital in USD (default: 10000)",
    )
    args = parser.parse_args()

    if args.once:
        tracker = load_tracker()
        report = run_single_scan(args.capital, tracker)
        print(report.summary())
    else:
        run_loop(args.interval, args.capital)


if __name__ == "__main__":
    main()
