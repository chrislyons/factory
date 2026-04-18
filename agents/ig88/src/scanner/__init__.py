"""
Scanner Package
===============
Cross-venue scanner interface and implementations.
Each venue has a scanner that produces standardized Signal objects.
"""

from src.scanner.base import VenueScanner, Signal, RegimeState, PositionInfo
from src.scanner.kraken import KrakenScanner
from src.scanner.hyperliquid import HyperliquidScanner
from src.scanner.jupiter import JupiterScanner
from src.scanner.polymarket import PolymarketScanner

__all__ = [
    "VenueScanner",
    "Signal",
    "RegimeState",
    "PositionInfo",
    "KrakenScanner",
    "HyperliquidScanner",
    "JupiterScanner",
    "PolymarketScanner",
]
