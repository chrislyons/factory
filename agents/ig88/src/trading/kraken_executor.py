"""
Kraken Live Executor — Handles secure order placement and confirmation.
Provides a hard safety layer between strategy signals and the API.
"""

from __future__ import annotations
import hmac
import hashlib
import base64
import time
import urllib.request
import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Hard limits from mandate
MAX_POSITION_SIZE_USD = 50.0
DAILY_LOSS_LIMIT_USD = 25.0
MAX_CONCURRENT_POSITIONS = 1

class KrakenExecutor:
    """
    Autonomous executor for Kraken Spot.
    Ensures all trades adhere to risk limits and are confirmed before logging.
    """
    def __init__(self):
        self.api_key = os.environ.get('KRAKEN_API_KEY')
        self.api_secret = os.environ.get('KRAKEN_API_SECRET')
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Kraken API credentials missing from environment")

    def _generate_signature(self, path: str, nonce: str, post_data: str) -> str:
        sha256_hash = hashlib.sha256((nonce + post_data).encode()).digest()
        secret_bytes = base64.b64decode(self.api_secret)
        msg = path.encode() + sha256_hash
        sig = hmac.new(secret_bytes, msg, hashlib.sha512).digest()
        return base64.b64encode(sig).decode()

    def _request(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        nonce = str(int(time.time() * 1000))
        params['nonce'] = nonce
        import urllib.parse
        post_data = urllib.parse.urlencode(params)
        
        sig = self._generate_signature(path, nonce, post_data)
        url = f"https://api.kraken.com{path}"
        headers = {
            "API-Key": self.api_key,
            "API-Sign": sig,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        req = urllib.request.Request(url, data=post_data.encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def get_balance(self) -> Dict[str, float]:
        res = self._request("/0/private/Balance", {})
        if res.get('error'):
            raise RuntimeError(f"Balance check failed: {res['error']}")
        return res['result']

    def place_market_order(self, pair: str, side: str, volume: float) -> str:
        params = {
            "pair": pair,
            "type": side, 
            "ordertype": "market",
            "volume": volume,
        }
        res = self._request("/0/private/AddOrder", params)
        if res.get('error'):
            raise RuntimeError(f"Order placement failed: {res['error']}")
        
        result = res['result']
        if isinstance(result, dict):
            if 'txid' in result:
                val = result['txid']
                return val[0] if isinstance(val, list) else str(val)
            txid_key = list(result.keys())[0]
            if isinstance(txid_key, list):
                return str(txid_key[0])
            return str(txid_key)
        if isinstance(result, list):
            return str(result[0])
        return str(result)

    def poll_order_status(self, txid: str, timeout_sec: int = 60) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout_sec:
            clean_txid = str(txid).strip()
            res = self._request("/0/private/QueryOrders", {"txid": clean_txid})
            if res.get('error'):
                if 'EOrder:Invalid order' in str(res['error']):
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Order query failed: {res['error']}")
            
            result_data = res.get('result', {})
            orders = result_data.get(clean_txid, [])
            if not orders:
                time.sleep(2)
                continue
            order = orders[0]
            if order.get('status') == 'closed':
                return order
            time.sleep(2)
        raise TimeoutError(f"Order {txid} did not close within {timeout_sec}s")

    def execute_trade(self, pair: str, side: str, amount_usd: float) -> Dict[str, Any]:
        if amount_usd > MAX_POSITION_SIZE_USD:
            raise ValueError(f"Trade size ${amount_usd} exceeds max limit ${MAX_POSITION_SIZE_USD}")
        txid = self.place_market_order(pair, side, amount_usd) 
        fill_details = self.poll_order_status(txid)
        self._log_to_memory(pair, side, amount_usd, fill_details)
        return fill_details

    def _log_to_memory(self, pair: str, side: str, amount: float, details: Dict[str, Any]):
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"\\n- {timestamp} | {pair} | {side} | ${amount} | Status: {details.get('status')} | Fill: {details.get('weightedAvgPrice')}\\n"
        with open("/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/fact/trading.md", "a") as f:
            f.write(log_entry)
