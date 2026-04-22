#!/usr/bin/env python3
"""
IG-88 Executor v1 — Bridge signals to Jupiter Perps.
====================================================
Reads signals from the 4H paper trader, validates risk, executes via Jupiter.

Modes:
  paper   — Read signals, simulate fills (default)
  signal  — Read signals, show what WOULD execute, dry-run
  live    — Execute trades via Jupiter Perps API (requires funded wallet)

Architecture:
  scanner (v9) → signal JSON → executor.py → Jupiter Perps → fill log

Usage:
  .venv/bin/python3 scripts/executor.py                    # paper mode (check signals)
  .venv/bin/python3 scripts/executor.py --mode signal      # dry-run
  .venv/bin/python3 scripts/executor.py --mode live        # live execution
  .venv/bin/python3 scripts/executor.py --mode monitor     # check positions/exits
"""
import json, sys, os, time, subprocess, tempfile, logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict

import requests
import pandas as pd
import numpy as np

# === PATHS ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
STATE_DIR = BASE_DIR / "data" / "paper_4h"
LIVE_DIR = BASE_DIR / "data" / "live"
LIVE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# === WALLET ===
WALLET_PATH = Path.home() / ".config" / "ig88" / "trading-wallet.json"
WALLET_PUBKEY = "Hbv4jXQnaxVMGzX6fhkmNyXRFux3azCF6en3dS9QcpeB"

# === JUPITER PERPS API ===
# Jupiter Perps v2 — create/manage perpetual positions
JUPITER_PERPS_API = "https://perps-api.jup.ag/v2"
JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"

# === SOLANA ===
SOL_RPC = "https://api.mainnet-beta.solana.com"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# === JUPITER PERPS MARKET IDS ===
# Jupiter Perps uses specific market identifiers
PERPS_MARKETS = {
    "SOLUSDT": "SOL",
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "AVAXUSDT": "AVAX",
    "LINKUSDT": "LINK",
    "NEARUSDT": "NEAR",
    "ARBUSDT": "ARB",
    "OPUSDT": "OP",
    "SUIUSDT": "SUI",
    "ATOMUSDT": "ATOM",
    "AAVEUSDT": "AAVE",
}

# === RISK CONFIG ===
RISK = {
    "max_position_usd": 5000.0,      # Max notional per position
    "max_total_exposure_usd": 25000,  # Max total notional
    "max_positions": 8,               # Max concurrent positions
    "slippage_bps": 100,              # 1% slippage tolerance
    "min_wallet_sol": 0.05,           # Min SOL for tx fees
}

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "executor.log"),
    ]
)
log = logging.getLogger("executor")


# === DATA TYPES ===
@dataclass
class Signal:
    pair: str
    side: str           # LONG or SHORT
    entry_price: float
    stop_loss: float
    size: float         # units
    position_usd: float # notional
    strategy: str
    signal_time: str
    id: str = ""

@dataclass
class LivePosition:
    signal_id: str
    pair: str
    side: str
    entry_price: float
    size: float
    position_usd: float
    stop_loss: float
    entry_time: str
    tx_hash: str = ""
    status: str = "open"  # open, closed, failed


# === WALLET CHECKS ===
def check_wallet_balance() -> Dict:
    """Check SOL and USDC balances."""
    result = {"sol": 0.0, "usdc": 0.0, "has_wallet": False}
    
    if not WALLET_PATH.exists():
        log.error(f"Wallet not found: {WALLET_PATH}")
        return result
    
    result["has_wallet"] = True
    
    # Check SOL balance
    try:
        cmd = ["solana", "balance", "--keypair", str(WALLET_PATH), "--url", SOL_RPC]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            result["sol"] = float(r.stdout.strip().split()[0])
    except Exception as e:
        log.warning(f"Failed to check SOL balance: {e}")
    
    # Check USDC balance via Jupiter
    try:
        quote = get_jupiter_quote(USDC_MINT, SOL_MINT, 1_000_000)  # dummy
        # TODO: Use token balance API instead
    except:
        pass
    
    return result


def get_jupiter_quote(input_mint: str, output_mint: str, amount: int, slippage_bps: int = 100) -> Optional[Dict]:
    """Get a swap quote from Jupiter."""
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
        "slippageBps": slippage_bps,
    }
    try:
        resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Quote failed: {e}")
        return None


def build_and_sign_tx(quote: Dict) -> Optional[str]:
    """Build swap tx, sign with wallet, send to Solana."""
    # Build transaction
    payload = {
        "quoteResponse": quote,
        "userPublicKey": WALLET_PUBKEY,
        "wrapUnwrapSOL": True,
    }
    
    try:
        resp = requests.post(JUPITER_SWAP_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        tx_base64 = data.get("swapTransaction")
    except Exception as e:
        log.error(f"Build swap failed: {e}")
        return None
    
    if not tx_base64:
        log.error("No swap transaction in response")
        return None
    
    # Write tx to temp file, sign, send
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".b64", delete=False) as f:
            f.write(tx_base64)
            tx_file = f.name
        
        # Decode base64 to binary
        raw_file = tx_file + ".raw"
        cmd_decode = ["base64", "-d", "-i", tx_file, "-o", raw_file]
        subprocess.run(cmd_decode, capture_output=True, timeout=10)
        
        # Sign and send
        cmd_send = [
            "solana", "send-tx", raw_file,
            "--keypair", str(WALLET_PATH),
            "--url", SOL_RPC,
            "--skip-preflight",
        ]
        result = subprocess.run(cmd_send, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            sig = result.stdout.strip()
            log.info(f"TX sent: {sig}")
            return sig
        else:
            log.error(f"TX failed: {result.stderr}")
            return None
    except Exception as e:
        log.error(f"Sign/send failed: {e}")
        return None
    finally:
        for f in [tx_file, raw_file]:
            if os.path.exists(f):
                os.unlink(f)


# === EXECUTION ===
def execute_signal(signal: Signal, mode: str = "paper") -> Dict:
    """Execute a signal — paper, signal (dry-run), or live."""
    result = {
        "signal_id": signal.id,
        "pair": signal.pair,
        "side": signal.side,
        "mode": mode,
        "status": "pending",
    }
    
    # Risk checks
    if signal.position_usd > RISK["max_position_usd"]:
        result["status"] = "rejected"
        result["reason"] = f"Position ${signal.position_usd} exceeds max ${RISK['max_position_usd']}"
        log.warning(f"REJECTED: {result['reason']}")
        return result
    
    if mode == "paper":
        result["status"] = "paper_filled"
        result["entry_price"] = signal.entry_price
        log.info(f"PAPER: {signal.side} {signal.pair} @ ${signal.entry_price}")
        return result
    
    if mode == "signal":
        result["status"] = "dry_run"
        result["entry_price"] = signal.entry_price
        result["size"] = signal.size
        log.info(f"DRY RUN: Would {signal.side} {signal.pair} ${signal.position_usd} @ ${signal.entry_price}")
        return result
    
    # === LIVE MODE ===
    # Check wallet
    balance = check_wallet_balance()
    if not balance["has_wallet"]:
        result["status"] = "failed"
        result["reason"] = "No wallet"
        return result
    
    if balance["sol"] < RISK["min_wallet_sol"]:
        result["status"] = "failed"
        result["reason"] = f"Insufficient SOL: {balance['sol']:.4f} < {RISK['min_wallet_sol']}"
        return result
    
    # Execute via Jupiter spot swap (buy/sell token)
    # For perps, this would use Jupiter Perps API
    # For now, use spot swap as proof of concept
    
    market = PERPS_MARKETS.get(signal.pair)
    if not market:
        result["status"] = "failed"
        result["reason"] = f"No market mapping for {signal.pair}"
        return result
    
    token_mint = get_token_mint(market)
    if not token_mint:
        result["status"] = "failed"
        result["reason"] = f"No token mint for {market}"
        return result
    
    # Calculate swap amount in lamports/smallest unit
    amount_usdc = int(signal.position_usd * 1_000_000)  # USDC has 6 decimals
    
    if signal.side == "LONG":
        # Buy token with USDC
        quote = get_jupiter_quote(USDC_MINT, token_mint, amount_usdc, RISK["slippage_bps"])
    else:
        # For SHORT via spot: sell token for USDC
        # (Proper short requires perps — this is a simplified version)
        quote = get_jupiter_quote(token_mint, USDC_MINT, amount_usdc, RISK["slippage_bps"])
    
    if not quote:
        result["status"] = "failed"
        result["reason"] = "No quote received"
        return result
    
    tx_sig = build_and_sign_tx(quote)
    if tx_sig:
        result["status"] = "live_filled"
        result["tx_hash"] = tx_sig
        log.info(f"LIVE FILLED: {signal.side} {signal.pair} tx={tx_sig}")
    else:
        result["status"] = "failed"
        result["reason"] = "Transaction failed"
    
    return result


def get_token_mint(symbol: str) -> Optional[str]:
    """Get Solana token mint address for a symbol."""
    mints = {
        "SOL": SOL_MINT,
        "ETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
        "AVAX": "FHfba3ov5P3RjAdLK8SfaTcQW1GDChmrg7m3F9pBLTJG",
        "LINK": "2wpTofQ8SkACrkZWrZDjXPitXfG3DLKj1bGF1J7H9XST",
        "NEAR": "BYPsjxa3YuZESQz1dKuBw1QSFCSYsmEUs1r6QLCHxMBK",
        "ARB": "9oVGLwFqfbMCzXuVVPpYhZGqL6wNKhXtuXfS9Yt3FHXx",
        "OP": "7o36gTRXsJ6s4k4mCDvFJ7hPHuH5UDk9WSiTcB7KvJEB",
        "SUI": "AFbX8oGjGpmVFywbVouvhQSRmiW2aR1mohfahi4Y2AdB",
        "ATOM": "ibc/C4CFF46FD6DE35CA4CF4CE031E643C8FDC9BA4B99AE598E9B0ED98FE3A2319F9",
        "AAVE": "3vAs4D1WE6No4RVD2njkT5fJ4g5okYzMVhVBLJSMg7Nn",
    }
    return mints.get(symbol)


# === SIGNAL LOADING ===
def load_pending_signals() -> List[Signal]:
    """Load unexecuted signals from the paper trader state."""
    state_file = STATE_DIR / "state.json"
    if not state_file.exists():
        return []
    
    state = json.loads(state_file.read_text())
    signals = []
    
    for pos in state.get("open_positions", []):
        # Skip positions that have already been executed
        if pos.get("executed"):
            continue
        
        signals.append(Signal(
            pair=pos["pair"],
            side=pos["side"],
            entry_price=pos["entry_price"],
            stop_loss=pos["stop_loss"],
            size=pos.get("size", 0),
            position_usd=pos.get("position_usd", 0),
            strategy=pos.get("strategy", "4H_ATR"),
            signal_time=pos.get("signal_time", ""),
            id=pos.get("id", ""),
        ))
    
    return signals


# === MONITORING ===
def monitor_positions():
    """Check open positions for exits."""
    # Reuse the paper trader's check_positions logic
    state_file = STATE_DIR / "state.json"
    if not state_file.exists():
        log.info("No state file found")
        return
    
    state = json.loads(state_file.read_text())
    positions = state.get("open_positions", [])
    
    if not positions:
        log.info("No open positions")
        return
    
    log.info(f"Monitoring {len(positions)} open positions")
    for pos in positions:
        log.info(f"  {pos['side']:>5s} {pos['pair']:<12s} Entry=${pos['entry_price']:.4f} Stop=${pos['stop_loss']:.4f}")
    
    # Delegate exit checking to paper trader's positions command
    import subprocess
    cmd = [
        str(BASE_DIR / ".venv" / "bin" / "python3"),
        str(BASE_DIR / "scripts" / "atr4h_paper_trader_v9.py"),
        "positions"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        log.warning(result.stderr)


# === MAIN ===
def main():
    mode = "paper"
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]
    
    log.info(f"Executor starting — mode={mode}")
    
    if mode == "monitor":
        monitor_positions()
        return
    
    # Load signals
    signals = load_pending_signals()
    
    if not signals:
        log.info("No pending signals")
        return
    
    log.info(f"Found {len(signals)} pending signals")
    
    # Check current exposure
    state_file = STATE_DIR / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    open_count = len(state.get("open_positions", []))
    
    if open_count >= RISK["max_positions"]:
        log.warning(f"Max positions reached ({open_count}/{RISK['max_positions']})")
        return
    
    # Execute signals
    for signal in signals:
        result = execute_signal(signal, mode=mode)
        log.info(f"Result: {json.dumps(result, indent=2)}")
        
        # Mark as executed in state
        for pos in state.get("open_positions", []):
            if pos.get("id") == signal.id:
                pos["executed"] = True
                pos["execution_result"] = result
                break
        
        # Rate limit between executions
        if mode == "live":
            time.sleep(2)
    
    # Save state
    state_file.write_text(json.dumps(state, indent=2, default=str))
    
    # Log to execution file
    exec_log = LIVE_DIR / f"executions_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    with open(exec_log, "a") as f:
        for signal in signals:
            f.write(json.dumps({
                "time": datetime.now(timezone.utc).isoformat(),
                "signal": asdict(signal),
                "mode": mode,
            }) + "\n")
    
    log.info("Executor complete")


if __name__ == "__main__":
    main()
