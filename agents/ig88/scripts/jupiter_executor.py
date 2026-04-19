#!/usr/bin/env python3
"""
IG-88 Jupiter Perps Executor — Autonomous Trading Engine
========================================================
Signal generation + Position management + Execution framework.

Modes:
  dry-run   Paper trading with real market data (default)
  signal    Generate signals only, no execution
  live      Execute trades via Jupiter (requires funded wallet)

Architecture:
  1. Data layer: Fetch OHLCV from Binance (free, reliable)
  2. Signal layer: ATR Breakout LONG/SHORT with regime filter
  3. Position layer: Track open positions, stops, trailing
  4. Execution layer: Jupiter Swap API for spot / Ultra for perps
  5. Risk layer: Kelly sizing, max exposure, health monitoring

Usage:
  python3 scripts/jupiter_executor.py                    # dry-run backtest
  python3 scripts/jupiter_executor.py --mode signal      # generate signals
  python3 scripts/jupiter_executor.py --mode live        # execute trades
  python3 scripts/jupiter_executor.py --mode monitor     # monitor positions
"""

import os
import sys
import json
import time
import logging
import hashlib
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple
from enum import Enum

import requests
import pandas as pd
import numpy as np

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data"
STATE_DIR = DATA_DIR / "jupiter_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Wallet
WALLET_PATH = Path.home() / ".config" / "ig88" / "trading-wallet.json"
WALLET_PUBKEY = "Hbv4jXQnaxVMGzX6fhkmNyXRFux3azCF6en3dS9QcpeB"

# Jupiter API
JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"

# Token mints
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Asset token mints (for spot swaps — perps use different mechanism)
TOKEN_MINTS = {
    "SOL": SOL_MINT,
    "ETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
    "AVAX": "FHfba3ov5P3RjAdLK8SfaTcQW1GDChmrg7m3F9pBLTJG",
    "LINK": "2wpTofQ8SkACrkZWrZDjXPitXfG3DLKj1bGF1J7H9XST",
    "NEAR": "BYPsjxa3YuZESQz1dKuBw1QSFCSYsmEUs1r6QLCHxMBK",
    "FIL": "EZtioaBz7nMNMj7W2Gx2FKaGyDxgaLcTnaH2EN2rpump",
    "SUI": "AFbX8oGjGpmVFywbVouvhQSRmiW2aR1mohfahi4Y2AdB",
    "WLD": "2cJgF5qQoDqg6WwCfSxfcA3XZ3QL6JBhGZRmqtV4KKzT",
}

# Validated strategy parameters (from registry v5)
LONG_CONFIG = {
    "assets": ["ETH", "AVAX", "SOL", "LINK", "NEAR", "FIL", "SUI", "WLD"],
    "lookback": 20,
    "atr_period": 10,
    "atr_mult": 1.5,
    "trail_pct": 0.01,  # IG88077: 1.0% optimal
    "hold_hours": 96,
    "regime_filter": "SMA100",
}

SHORT_CONFIG = {
    "assets": ["ETH", "LINK", "AVAX", "SOL", "SUI"],
    "lookback": 10,
    "atr_period": 10,
    "atr_mult": 2.5,
    "trail_pct": 0.025,
    "hold_hours": 48,
}

# Risk limits
RISK = {
    "max_leverage": 2,
    "max_position_pct": 0.15,  # 15% of portfolio per asset
    "max_total_exposure": 0.90,  # 90% max (10% reserve)
    "friction_rt": 0.0014,  # Jupiter perps round-trip
    "min_signal_confidence": 0.6,
}

# === DATA TYPES ===
class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"

@dataclass
class Signal:
    asset: str
    direction: Direction
    entry_price: float
    stop_price: float
    atr: float
    timestamp: datetime
    confidence: float = 1.0
    regime_ok: bool = True

@dataclass
class Position:
    asset: str
    direction: Direction
    entry_price: float
    entry_time: datetime
    size_usd: float
    stop_price: float
    highest_close: float
    bars_held: int = 0
    leverage: float = 1.0
    tx_hash: str = ""

@dataclass
class Trade:
    asset: str
    direction: Direction
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    size_usd: float
    pnl_pct: float
    pnl_usd: float
    exit_reason: str
    tx_hash_entry: str = ""
    tx_hash_exit: str = ""


class DataLayer:
    """Fetch OHLCV data from Binance API (free, no key needed)."""
    
    @staticmethod
    def fetch_ohlcv(symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
        """Fetch OHLCV data from Binance."""
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
        
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logging.error(f"Failed to fetch {symbol}: {e}")
            return pd.DataFrame()
        
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        
        df.set_index("time", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]
    
    @staticmethod
    def fetch_multiple(assets: List[str], interval: str = "1h", limit: int = 500) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple assets."""
        result = {}
        for asset in assets:
            df = DataLayer.fetch_ohlcv(asset, interval, limit)
            if not df.empty:
                result[asset] = df
            time.sleep(0.1)  # Rate limit
        return result


class SignalEngine:
    """ATR Breakout signal generation with regime filtering."""
    
    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 10) -> np.ndarray:
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            )
        )
        tr = np.concatenate([[0], tr])
        return pd.Series(tr, index=df.index).rolling(period).mean().values
    
    @staticmethod
    def check_regime(df: pd.DataFrame, sma_period: int = 100) -> np.ndarray:
        """Check if price is above SMA (bull regime)."""
        sma = df["close"].rolling(sma_period).mean().values
        return df["close"].values > sma
    
    @classmethod
    def generate_signals(
        cls,
        df: pd.DataFrame,
        asset: str,
        config: Dict,
        direction: Direction,
    ) -> List[Signal]:
        """Generate ATR Breakout signals."""
        lookback = config["lookback"]
        atr_period = config["atr_period"]
        atr_mult = config["atr_mult"]
        
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        
        atr = cls.compute_atr(df, atr_period)
        
        if direction == Direction.LONG:
            channel = pd.Series(high).rolling(lookback).max().shift(1).values
            regime = cls.check_regime(df, 100) if config.get("regime_filter") else np.ones(len(df), dtype=bool)
        else:
            channel = pd.Series(low).rolling(lookback).min().shift(1).values
            regime = np.ones(len(df), dtype=bool)
        
        signals = []
        for i in range(max(lookback, atr_period) + 1, len(df)):
            if np.isnan(atr[i]) or np.isnan(channel[i]):
                continue
            
            current_close = close[i]
            current_atr = atr[i]
            
            if direction == Direction.LONG:
                if current_close > channel[i] and regime[i]:
                    stop = current_close - (atr_mult * current_atr)
                    signals.append(Signal(
                        asset=asset,
                        direction=Direction.LONG,
                        entry_price=current_close,
                        stop_price=stop,
                        atr=current_atr,
                        timestamp=df.index[i],
                    ))
            else:
                if current_close < channel[i]:
                    # SHORT entry: close below (low_channel - atr*atr_mult)
                    entry_threshold = channel[i] - current_atr * atr_mult
                    if current_close < entry_threshold:
                        stop = current_close + (atr_mult * current_atr)
                        signals.append(Signal(
                            asset=asset,
                            direction=Direction.SHORT,
                            entry_price=current_close,
                            stop_price=stop,
                            atr=current_atr,
                            timestamp=df.index[i],
                        ))
        
        return signals
    
    @classmethod
    def get_latest_signal(
        cls,
        df: pd.DataFrame,
        asset: str,
        config: Dict,
        direction: Direction,
    ) -> Optional[Signal]:
        """Check if there is a signal on the latest bar."""
        signals = cls.generate_signals(df.tail(10), asset, config, direction)
        if signals:
            last = signals[-1]
            # Only return signal if it's on the most recent bar
            if last.timestamp == df.index[-1]:
                return last
        return None


class PositionManager:
    """Track and manage open positions."""
    
    def __init__(self, state_file: Path = STATE_DIR / "positions.json"):
        self.state_file = state_file
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.portfolio_value = 1000.0  # Starting value in USD
        self.load_state()
    
    def load_state(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.portfolio_value = data.get("portfolio_value", 1000.0)
                trades_data = data.get("trades", [])
                self.trades = [Trade(**t) for t in trades_data]
            except Exception as e:
                logging.warning(f"Failed to load state: {e}")
    
    def save_state(self):
        data = {
            "portfolio_value": self.portfolio_value,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "trades": [asdict(t) for t in self.trades[-500:]],  # Keep last 500
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state_file.write_text(json.dumps(data, indent=2, default=str))
    
    def open_position(self, signal: Signal, size_usd: float, leverage: float = 1.0) -> Position:
        pos = Position(
            asset=signal.asset,
            direction=signal.direction,
            entry_price=signal.entry_price,
            entry_time=signal.timestamp,
            size_usd=size_usd,
            stop_price=signal.stop_price,
            highest_close=signal.entry_price,
            leverage=leverage,
        )
        self.positions[signal.asset] = pos
        self.save_state()
        return pos
    
    def check_exits(self, prices: Dict[str, float], config: Dict) -> List[Trade]:
        """Check all positions for exit conditions."""
        exits = []
        for asset, pos in list(self.positions.items()):
            if asset not in prices:
                continue
            
            current_price = prices[asset]
            pos.bars_held += 1
            
            if pos.direction == Direction.LONG:
                pos.highest_close = max(pos.highest_close, current_price)
                trail_stop = pos.highest_close * (1 - config.get("trail_pct", 0.01))
                effective_stop = max(pos.stop_price, trail_stop)
                
                exit_triggered = False
                exit_reason = ""
                
                if current_price <= effective_stop:
                    exit_price = effective_stop
                    exit_triggered = True
                    exit_reason = "stop"
                elif pos.bars_held >= config.get("hold_hours", 96):
                    exit_price = current_price
                    exit_triggered = True
                    exit_reason = "time"
                
                if exit_triggered:
                    pnl_pct = (exit_price / pos.entry_price) - 1 - RISK["friction_rt"]
                    pnl_usd = pos.size_usd * pnl_pct * pos.leverage
                    trade = Trade(
                        asset=asset, direction=pos.direction,
                        entry_price=pos.entry_price, exit_price=exit_price,
                        entry_time=pos.entry_time, exit_time=datetime.now(timezone.utc),
                        size_usd=pos.size_usd, pnl_pct=pnl_pct, pnl_usd=pnl_usd,
                        exit_reason=exit_reason,
                    )
                    exits.append(trade)
                    self.trades.append(trade)
                    self.portfolio_value += pnl_usd
                    del self.positions[asset]
            
            elif pos.direction == Direction.SHORT:
                trail_stop = current_price * (1 + config.get("trail_pct", 0.025))
                effective_stop = min(pos.stop_price, trail_stop)
                
                exit_triggered = False
                exit_reason = ""
                
                if current_price >= effective_stop:
                    exit_price = effective_stop
                    exit_triggered = True
                    exit_reason = "stop"
                elif pos.bars_held >= config.get("hold_hours", 48):
                    exit_price = current_price
                    exit_triggered = True
                    exit_reason = "time"
                
                if exit_triggered:
                    pnl_pct = (pos.entry_price / exit_price) - 1 - RISK["friction_rt"]
                    pnl_usd = pos.size_usd * pnl_pct * pos.leverage
                    trade = Trade(
                        asset=asset, direction=pos.direction,
                        entry_price=pos.entry_price, exit_price=exit_price,
                        entry_time=pos.entry_time, exit_time=datetime.now(timezone.utc),
                        size_usd=pos.size_usd, pnl_pct=pnl_pct, pnl_usd=pnl_usd,
                        exit_reason=exit_reason,
                    )
                    exits.append(trade)
                    self.trades.append(trade)
                    self.portfolio_value += pnl_usd
                    del self.positions[asset]
        
        if exits:
            self.save_state()
        return exits


class JupiterExecutor:
    """Execute swaps via Jupiter API."""
    
    @staticmethod
    def get_quote(
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        slippage_bps: int = 50,
    ) -> Optional[Dict]:
        """Get a swap quote from Jupiter."""
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_lamports),
            "slippageBps": slippage_bps,
        }
        
        try:
            resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logging.error(f"Quote failed: {e}")
            return None
    
    @staticmethod
    def get_price_usd(asset: str) -> float:
        """Get current price in USD via Jupiter quote."""
        if asset == "SOL":
            quote = JupiterExecutor.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)  # 1 SOL
        else:
            mint = TOKEN_MINTS.get(asset)
            if not mint:
                return 0.0
            # Get how much USDC for 1 unit of token
            quote = JupiterExecutor.get_quote(mint, USDC_MINT, 1_000_000)  # 1 token (6 decimals)
        
        if quote:
            out = int(quote.get("outAmount", 0))
            if asset == "SOL":
                return out / 1_000_000  # USDC has 6 decimals
            else:
                return out / 1_000_000  # Adjust per token decimals
        return 0.0
    
    @staticmethod
    def build_swap_tx(quote: Dict) -> Optional[str]:
        """Build a swap transaction (returns serialized tx)."""
        payload = {
            "quoteResponse": quote,
            "userPublicKey": WALLET_PUBKEY,
            "wrapUnwrapSOL": True,
        }
        
        try:
            resp = requests.post(JUPITER_SWAP_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("swapTransaction")
        except Exception as e:
            logging.error(f"Build swap failed: {e}")
            return None
    
    @staticmethod
    def sign_and_send(tx_base64: str) -> Optional[str]:
        """Sign transaction with wallet and send to Solana."""
        import tempfile
        
        # Write serialized tx to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(tx_base64)
            tx_file = f.name
        
        try:
            # Decode, sign, and send using solana-cli
            # First decode the base64 transaction
            raw_tx_file = tx_file + ".raw"
            
            # Use solana-cli to sign and send
            cmd = [
                "solana", "send-tx", raw_tx_file,
                "--keypair", str(WALLET_PATH),
                "--url", "https://api.mainnet-beta.solana.com",
                "--skip-preflight",
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                tx_sig = result.stdout.strip()
                logging.info(f"TX sent: {tx_sig}")
                return tx_sig
            else:
                logging.error(f"TX failed: {result.stderr}")
                return None
        finally:
            os.unlink(tx_file)


class RiskManager:
    """Portfolio-level risk management."""
    
    @staticmethod
    def calculate_position_size(
        portfolio_value: float,
        open_positions: Dict[str, Position],
        signal: Signal,
    ) -> float:
        """Calculate position size using equal-weight with Kelly overlay."""
        n_assets = len(LONG_CONFIG["assets"])
        base_weight = 1.0 / n_assets
        
        # Check total exposure
        current_exposure = sum(p.size_usd for p in open_positions.values())
        max_allowed = portfolio_value * RISK["max_total_exposure"]
        
        if current_exposure >= max_allowed:
            return 0.0  # No room
        
        # Calculate available allocation
        available = min(
            portfolio_value * RISK["max_position_pct"],  # Per-asset cap
            max_allowed - current_exposure,  # Remaining exposure budget
            portfolio_value * base_weight,  # Equal-weight target
        )
        
        return max(available, 0.0)
    
    @staticmethod
    def check_health(positions: Dict[str, Position], prices: Dict[str, float]) -> Dict:
        """Check portfolio health metrics."""
        total_exposure = sum(p.size_usd for p in positions.values())
        unrealized_pnl = 0.0
        
        for asset, pos in positions.items():
            if asset not in prices:
                continue
            price = prices[asset]
            if pos.direction == Direction.LONG:
                pnl_pct = (price / pos.entry_price) - 1
            else:
                pnl_pct = (pos.entry_price / price) - 1
            unrealized_pnl += pos.size_usd * pnl_pct * pos.leverage
        
        return {
            "total_positions": len(positions),
            "total_exposure_usd": total_exposure,
            "unrealized_pnl_usd": unrealized_pnl,
            "long_count": sum(1 for p in positions.values() if p.direction == Direction.LONG),
            "short_count": sum(1 for p in positions.values() if p.direction == Direction.SHORT),
        }


def run_scan(mode: str = "signal"):
    """Main scan loop — fetch data, generate signals, manage positions."""
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "jupiter_executor.log"),
        ],
    )
    
    pm = PositionManager()
    
    logging.info(f"=== IG-88 Jupiter Executor — Mode: {mode} ===")
    logging.info(f"Portfolio: ${pm.portfolio_value:.2f}")
    logging.info(f"Open positions: {len(pm.positions)}")
    
    # 1. Fetch market data
    all_assets = list(set(LONG_CONFIG["assets"] + SHORT_CONFIG["assets"]))
    logging.info(f"Fetching data for {len(all_assets)} assets...")
    data = DataLayer.fetch_multiple(all_assets, interval="1h", limit=200)
    logging.info(f"Fetched data for {len(data)} assets")
    
    # 2. Get current prices
    prices = {}
    for asset in all_assets:
        if asset in data:
            prices[asset] = data[asset]["close"].iloc[-1]
    
    # 3. Check exits on existing positions
    exits = []
    for asset in list(pm.positions.keys()):
        pos = pm.positions[asset]
        config = LONG_CONFIG if pos.direction == Direction.LONG else SHORT_CONFIG
        asset_exits = pm.check_exits({asset: prices.get(asset, 0)}, config)
        exits.extend(asset_exits)
    
    if exits:
        for t in exits:
            logging.info(f"EXIT {t.direction.value} {t.asset}: {t.exit_reason} | PnL: {t.pnl_pct*100:.2f}% (${t.pnl_usd:.2f})")
    
    # 4. Generate new signals
    new_signals = []
    
    for asset in LONG_CONFIG["assets"]:
        if asset in data and asset not in pm.positions:
            signal = SignalEngine.get_latest_signal(
                data[asset], asset, LONG_CONFIG, Direction.LONG
            )
            if signal:
                new_signals.append(signal)
    
    for asset in SHORT_CONFIG["assets"]:
        if asset in data and asset not in pm.positions:
            signal = SignalEngine.get_latest_signal(
                data[asset], asset, SHORT_CONFIG, Direction.SHORT
            )
            if signal:
                new_signals.append(signal)
    
    # 5. Open positions for signals
    for signal in new_signals:
        size = RiskManager.calculate_position_size(
            pm.portfolio_value, pm.positions, signal
        )
        
        if size <= 0:
            logging.info(f"SIGNAL {signal.direction.value} {signal.asset} @ ${signal.entry_price:.4f} — no room (exposure limit)")
            continue
        
        leverage = RISK["max_leverage"]
        
        if mode == "live":
            # Execute via Jupiter
            logging.info(f"EXECUTING {signal.direction.value} {signal.asset} @ ${signal.entry_price:.4f} size=${size:.2f}")
            # TODO: Implement actual Jupiter execution
            # For now, fall through to paper trading
            pos = pm.open_position(signal, size, leverage)
            logging.info(f"OPENED (paper fallback) {signal.direction.value} {signal.asset} @ ${signal.entry_price:.4f} size=${size:.2f}")
        else:
            pos = pm.open_position(signal, size, leverage)
            logging.info(f"OPENED {signal.direction.value} {signal.asset} @ ${signal.entry_price:.4f} size=${size:.2f} stop=${signal.stop_price:.4f}")
    
    # 6. Print summary
    health = RiskManager.check_health(pm.positions, prices)
    logging.info(f"Portfolio: ${pm.portfolio_value:.2f} | Positions: {health['total_positions']} | Exposure: ${health['total_exposure_usd']:.2f}")
    
    if pm.trades:
        wins = [t for t in pm.trades if t.pnl_usd > 0]
        losses = [t for t in pm.trades if t.pnl_usd <= 0]
        total_profit = sum(t.pnl_usd for t in wins)
        total_loss = abs(sum(t.pnl_usd for t in losses)) if losses else 0.001
        pf = total_profit / total_loss
        logging.info(f"Trades: {len(pm.trades)} | Wins: {len(wins)} ({len(wins)/len(pm.trades)*100:.0f}%) | PF: {pf:.2f}")
    
    return {
        "portfolio_value": pm.portfolio_value,
        "positions": len(pm.positions),
        "new_signals": len(new_signals),
        "exits": len(exits),
        "health": health,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IG-88 Jupiter Perps Executor")
    parser.add_argument("--mode", choices=["signal", "live", "monitor", "backtest"], default="signal")
    parser.add_argument("--interval", type=int, default=3600, help="Scan interval in seconds")
    args = parser.parse_args()
    
    if args.mode == "monitor":
        while True:
            try:
                result = run_scan("signal")
                logging.info(f"Sleeping {args.interval}s...")
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Scan error: {e}")
                time.sleep(60)
    else:
        run_scan(args.mode)
