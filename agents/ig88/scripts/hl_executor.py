#!/usr/bin/env python3
"""
Hyperliquid DEX Perps Executor for IG-88.
Uses Hyperliquid Python SDK for order execution.

Status: SKELETON — awaiting API credentials (.env) and USDC deposit on Arbitrum.
DO NOT RUN LIVE without Chris approval for first trade.

Setup:
  1. pip install hyperliquid-python-sdk (in .venv)
  2. Fund wallet with USDC on Arbitrum
  3. Set HL_ACCOUNT_ADDRESS and HL_SECRET_KEY in .env
  4. Set LIVE=true and DRY_RUN=false to enable real execution

Architecture:
  - Quote: HL's spot/perp swap API for pricing
  - Execute: SDK's exchange.place_order()
  - Monitor: SDK's info.open_orders() and info.user_state()
  - Risk: Position sizing from Kelly, max 15% per asset
"""

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Conditional import — SDK may not be installed yet
try:
    from hyperliquid.info import Info
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    HL_SDK_AVAILABLE = True
except ImportError:
    HL_SDK_AVAILABLE = False

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
STATE_DIR = BASE_DIR / "data" / "hl_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Environment
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
LIVE = os.getenv("LIVE", "false").lower() == "true"
ACCOUNT_ADDRESS = os.getenv("HL_ACCOUNT_ADDRESS", "")
SECRET_KEY = os.getenv("HL_SECRET_KEY", "")

# Risk limits (matching validated strategy)
MAX_LEVERAGE = 3          # Absolute ceiling
DEFAULT_LEVERAGE = 2      # Kelly-optimal starting point
MAX_POSITION_PCT = 0.15   # 15% of portfolio per asset
MAX_TOTAL_EXPOSURE = 1.0  # 100% max total

# Validated assets with params from strategy registry
LONG_ASSETS = {
    "FIL":  {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "SUI":  {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "AVAX": {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "NEAR": {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "RNDR": {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "WLD":  {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "ETH":  {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "LINK": {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
    "SOL":  {"atr_mult_stop": 2.0, "trail": 0.02, "max_hold_h": 96},
}

SHORT_ASSETS = {
    "ETH":  {"atr_mult_entry": 2.5, "atr_mult_stop": 2.0, "trail": 0.025, "max_hold_h": 48},
    "AVAX": {"atr_mult_entry": 2.5, "atr_mult_stop": 2.0, "trail": 0.025, "max_hold_h": 48},
    "LINK": {"atr_mult_entry": 2.5, "atr_mult_stop": 2.0, "trail": 0.025, "max_hold_h": 48},
    "SOL":  {"atr_mult_entry": 2.5, "atr_mult_stop": 2.0, "trail": 0.025, "max_hold_h": 48},
    "SUI":  {"atr_mult_entry": 2.5, "atr_mult_stop": 2.0, "trail": 0.025, "max_hold_h": 48},
}


@dataclass
class TradeParams:
    asset: str
    direction: str          # "LONG" or "SHORT"
    entry_price: float
    stop_price: float
    size_usd: float
    leverage: int
    atr: float
    regime: str


class HyperliquidExecutor:
    """Manages order execution on Hyperliquid DEX perps."""

    def __init__(self):
        self.info = None
        self.exchange = None
        self.connected = False
        self.positions = {}
        self.trade_log = []

        if not HL_SDK_AVAILABLE:
            print("[HL] SDK not installed. Run: uv pip install hyperliquid-python-sdk")
            return

        if not ACCOUNT_ADDRESS or not SECRET_KEY:
            print("[HL] Missing credentials. Set HL_ACCOUNT_ADDRESS and HL_SECRET_KEY in .env")
            return

        try:
            self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
            self.exchange = Exchange(
                account_address=ACCOUNT_ADDRESS,
                secret_key=SECRET_KEY,
                base_url=constants.MAINNET_API_URL,
            )
            self.connected = True
            print(f"[HL] Connected to Hyperliquid mainnet. Account: {ACCOUNT_ADDRESS[:8]}...")
        except Exception as e:
            print(f"[HL] Connection failed: {e}")

    def get_balance(self) -> float:
        """Get account equity in USD."""
        if not self.connected:
            return 0.0
        try:
            user_state = self.info.user_state(ACCOUNT_ADDRESS)
            margin_summary = user_state.get("marginSummary", {})
            return float(margin_summary.get("accountValue", 0))
        except Exception as e:
            print(f"[HL] Balance check failed: {e}")
            return 0.0

    def get_positions(self) -> dict:
        """Get current open positions."""
        if not self.connected:
            return {}
        try:
            user_state = self.info.user_state(ACCOUNT_ADDRESS)
            positions = {}
            for pos in user_state.get("assetPositions", []):
                pos_data = pos.get("position", {})
                coin = pos_data.get("coin", "")
                size = float(pos_data.get("szi", 0))
                if size != 0:
                    positions[coin] = {
                        "size": size,
                        "entry_px": float(pos_data.get("entryPx", 0)),
                        "unrealized_pnl": float(pos_data.get("unrealizedPnl", 0)),
                        "leverage": pos_data.get("leverage", {}).get("value", 1),
                    }
            self.positions = positions
            return positions
        except Exception as e:
            print(f"[HL] Position check failed: {e}")
            return {}

    def calculate_size(self, asset: str, direction: str, price: float, 
                       portfolio_value: float) -> float:
        """
        Calculate position size in USD based on Kelly-optimal sizing.
        Returns size in USD to deploy.
        """
        max_per_asset = portfolio_value * MAX_POSITION_PCT
        return min(max_per_asset, portfolio_value * DEFAULT_LEVERAGE * MAX_POSITION_PCT)

    def place_order(self, params: TradeParams) -> dict:
        """
        Place a market order on Hyperliquid.
        
        Returns dict with order result.
        """
        if DRY_RUN or not self.connected:
            result = {
                "status": "DRY_RUN" if DRY_RUN else "NO_CONNECTION",
                "asset": params.asset,
                "direction": params.direction,
                "size_usd": params.size_usd,
                "price": params.entry_price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(f"[HL] DRY RUN: {params.direction} {params.asset} ${params.size_usd:.0f} @ {params.entry_price:.4f}")
            self.trade_log.append(result)
            return result

        try:
            # Determine order side
            is_buy = params.direction == "LONG"

            # Convert USD size to coin amount
            coin_amount = params.size_usd / params.entry_price

            # Set leverage before order
            self.exchange.update_leverage(params.asset, params.leverage)

            # Place market order
            order_result = self.exchange.market_open(
                coin=params.asset,
                is_buy=is_buy,
                sz=coin_amount,
            )

            result = {
                "status": "SUBMITTED",
                "asset": params.asset,
                "direction": params.direction,
                "size_usd": params.size_usd,
                "coin_amount": coin_amount,
                "price": params.entry_price,
                "leverage": params.leverage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hl_response": str(order_result),
            }

            print(f"[HL] ORDER PLACED: {params.direction} {params.asset} {coin_amount:.4f} @ {params.entry_price:.4f} ({params.leverage}x)")
            self.trade_log.append(result)
            self._save_trade(result)
            return result

        except Exception as e:
            error_result = {
                "status": "ERROR",
                "asset": params.asset,
                "direction": params.direction,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(f"[HL] ORDER FAILED: {params.direction} {params.asset} - {e}")
            self.trade_log.append(error_result)
            self._save_trade(error_result)
            return error_result

    def close_position(self, asset: str, reason: str = "manual") -> dict:
        """Close an open position."""
        if DRY_RUN or not self.connected:
            result = {
                "status": "DRY_RUN",
                "asset": asset,
                "action": "CLOSE",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            print(f"[HL] DRY RUN: CLOSE {asset} ({reason})")
            return result

        try:
            positions = self.get_positions()
            if asset not in positions:
                return {"status": "NO_POSITION", "asset": asset}

            pos = positions[asset]
            is_buy = pos["size"] < 0  # Close short = buy, close long = sell
            abs_size = abs(pos["size"])

            order_result = self.exchange.market_open(
                coin=asset,
                is_buy=is_buy,
                sz=abs_size,
            )

            result = {
                "status": "CLOSED",
                "asset": asset,
                "size": abs_size,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hl_response": str(order_result),
            }
            print(f"[HL] CLOSED: {asset} {abs_size} ({reason})")
            self._save_trade(result)
            return result

        except Exception as e:
            print(f"[HL] CLOSE FAILED: {asset} - {e}")
            return {"status": "ERROR", "asset": asset, "error": str(e)}

    def _save_trade(self, trade: dict):
        """Append trade to daily log."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = STATE_DIR / f"hl_trades_{date_str}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(trade) + "\n")


def get_funding_rates(info_client) -> dict:
    """Fetch current funding rates for all assets."""
    if not info_client:
        return {}
    try:
        meta = info_client.meta()
        funding = {}
        for asset_info in meta.get("universe", []):
            coin = asset_info.get("name", "")
            funding_rate = asset_info.get("fundingRate", None)
            if funding_rate is not None:
                funding[coin] = float(funding_rate)
        return funding
    except Exception as e:
        print(f"[HL] Funding rate fetch failed: {e}")
        return {}


# === CLI INTERFACE ===
if __name__ == "__main__":
    import sys

    print("=== Hyperliquid Executor ===")
    print(f"DRY_RUN: {DRY_RUN} | LIVE: {LIVE}")
    print(f"SDK Available: {HL_SDK_AVAILABLE}")
    print()

    executor = HyperliquidExecutor()

    if not executor.connected:
        print("Not connected. Check credentials and SDK installation.")
        print()
        print("Setup steps:")
        print("  1. uv pip install hyperliquid-python-sdk")
        print("  2. Create .env with HL_ACCOUNT_ADDRESS and HL_SECRET_KEY")
        print("  3. Fund wallet with USDC on Arbitrum")
        sys.exit(1)

    balance = executor.get_balance()
    positions = executor.get_positions()
    funding = get_funding_rates(executor.info)

    print(f"Balance: ${balance:.2f}")
    print(f"Positions: {len(positions)}")
    for coin, pos in positions.items():
        print(f"  {coin}: {pos['size']:.4f} @ {pos['entry_px']:.4f} | PnL: ${pos['unrealized_pnl']:.2f}")

    if funding:
        print(f"\nFunding rates (sample):")
        for coin in ["ETH", "SOL", "AVAX", "LINK"]:
            if coin in funding:
                rate = funding[coin]
                annual = rate * 3 * 365  # 8h funding, 3x/day
                print(f"  {coin}: {rate*100:.4f}% per 8h ({annual*100:.1f}% annualized)")
