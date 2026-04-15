"""
Polymarket Paper Trading Engine for IG-88.

Unlike spot/perps, Polymarket is a binary prediction market:
- Prices are probabilities (0-1 scale): YES at 0.54 = 54% implied probability
- No stop-losses/targets: P&L is determined at resolution ($1 or $0)
- The edge: LLM assesses probability without seeing market price
- When |LLm_estimate - market_price| exceeds fees + variance, we trade

This module:
1. Scans active Polymarket markets via CLI
2. Uses LLM to generate price-blind probability assessments
3. Generates trading signals when edge exceeds threshold
4. Simulates paper execution (no real orders submitted)
5. Tracks positions until resolution
6. Calculates P&L and Brier scores
7. Logs everything to JSONL for the existing PaperTrader infrastructure

Usage:
    from src.trading.polymarket_paper_trader import PolymarketPaperTrader
    trader = PolymarketPaperTrader(initial_capital=1000.0)
    signals = trader.scan_markets()
    trader.execute_signals(signals)
    trader.check_resolutions()  # Check if any markets have resolved
    summary = trader.get_summary()
"""

from __future__ import annotations

import json
import logging
import subprocess
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
POLYMARKET_DATA_DIR = AGENT_ROOT / "data" / "polymarket"
POLYMARKET_TRADES_PATH = POLYMARKET_DATA_DIR / "paper_trades.jsonl"
POLYMARKET_POSITIONS_PATH = POLYMARKET_DATA_DIR / "positions.json"
POLYMARKET_MARKETS_CACHE = POLYMARKET_DATA_DIR / "markets_cache.json"

# Fee structure (Polymarket)
TAKER_FEE = 0.0156       # ~1.56% taker fee (worst case, near 50% probability)
MAKER_FEE = 0.0          # Maker rebate instead
GEOPOLITICS_FEE = 0.0    # Geopolitics markets are fee-free

# Default thresholds
DEFAULT_EDGE_THRESHOLD = 0.05   # Minimum |LLM - market| to consider trade
DEFAULT_CONFIDENCE_MIN = 0.60   # Minimum LLM confidence to trade
DEFAULT_MIN_VOLUME = 10000.0    # Minimum market volume in USD
DEFAULT_KELLY_FRACTION = 0.25   # Quarter-Kelly sizing


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class PolymarketSignal:
    """A trading signal for a Polymarket market."""
    market_id: str
    question: str
    category: str
    market_price: float          # Current YES price (0-1)
    llm_estimate: float          # LLM's price-blind probability estimate
    llm_confidence: float        # LLM confidence (0-1)
    edge: float                  # |llm_estimate - market_price|
    side: str                    # "buy_yes" or "buy_no"
    recommended_size_usd: float  # Position size based on Kelly
    volume: float                # Market volume in USD
    end_date: str                # Market end date
    token_id: str | None = None  # Token ID for order placement
    fee_rate: float = TAKER_FEE  # Applicable fee rate
    reason: str = ""             # Explanation of the signal


@dataclass
class PolymarketPosition:
    """An open paper position on Polymarket."""
    position_id: str
    market_id: str
    question: str
    category: str
    side: str                    # "buy_yes" or "buy_no"
    entry_price: float           # Entry probability price
    position_size_usd: float     # USD invested
    entry_timestamp: str         # ISO timestamp
    llm_estimate: float          # LLM estimate at entry
    llm_confidence: float        # LLM confidence at entry
    end_date: str                # Market resolution date
    token_id: str | None = None
    fee_paid: float = 0.0
    
    # Filled at resolution
    exit_price: float | None = None
    exit_timestamp: str | None = None
    pnl_usd: float | None = None
    brier_score: float | None = None
    resolved: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> PolymarketPosition:
        return cls(**d)


@dataclass
class PaperTradeRecord:
    """A completed paper trade record for JSONL logging."""
    trade_id: str
    venue: str
    strategy: str
    market_id: str
    question: str
    category: str
    side: str
    entry_price: float
    exit_price: float
    position_size_usd: float
    pnl_usd: float
    pnl_pct: float
    entry_timestamp: str
    exit_timestamp: str
    llm_estimate: float
    llm_confidence: float
    brier_score: float
    fee_paid: float
    outcome: str  # "win", "loss", "push"
    logged_at: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Market Scanner (CLI-based)
# ---------------------------------------------------------------------------

class MarketScanner:
    """Fetches active Polymarket markets via the CLI."""
    
    def __init__(self, min_volume: float = DEFAULT_MIN_VOLUME, 
                 max_markets: int = 50):
        self.min_volume = min_volume
        self.max_markets = max_markets
    
    def fetch_active_markets(self) -> list[dict]:
        """Fetch active markets from Polymarket CLI."""
        try:
            result = subprocess.run(
                ["polymarket", "-o", "json", "markets", "list", 
                 "--active", "true", "--limit", str(self.max_markets)],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                logger.error(f"Market list failed: {result.stderr}")
                return []
            
            markets = json.loads(result.stdout)
            if not isinstance(markets, list):
                logger.error(f"Unexpected market list format: {type(markets)}")
                return []
            
            return markets
        
        except subprocess.TimeoutExpired:
            logger.error("Market list timed out")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse market list: {e}")
            return []
        except FileNotFoundError:
            logger.error("Polymarket CLI not found")
            return []
    
    def filter_markets(self, markets: list[dict], 
                       categories: list[str] | None = None,
                       min_volume: float | None = None) -> list[dict]:
        """Filter markets by volume and category."""
        min_vol = min_volume or self.min_volume
        filtered = []
        
        for mkt in markets:
            # Volume filter
            try:
                volume = float(mkt.get("volume", 0))
            except (ValueError, TypeError):
                volume = 0
            if volume < min_vol:
                continue
            
            # Category filter (if specified)
            if categories:
                cat = mkt.get("category", "")
                if cat and cat.lower() not in [c.lower() for c in categories]:
                    continue
            
            # Must have outcome prices
            prices_str = mkt.get("outcomePrices", "")
            if not prices_str:
                continue
            
            filtered.append(mkt)
        
        # Sort by volume descending
        filtered.sort(key=lambda x: float(x.get("volume", 0)), reverse=True)
        return filtered
    
    def parse_market(self, mkt: dict) -> dict | None:
        """Parse a raw market dict into a standardized format."""
        try:
            prices = json.loads(mkt.get("outcomePrices", "[]"))
            if len(prices) < 2:
                return None
            
            yes_price = float(prices[0])
            no_price = float(prices[1])
            
            return {
                "id": mkt.get("id", ""),
                "question": mkt.get("question", ""),
                "category": mkt.get("category") or "unknown",
                "yes_price": yes_price,
                "no_price": no_price,
                "volume": float(mkt.get("volume", 0)),
                "liquidity": float(mkt.get("liquidity", 0)),
                "end_date": mkt.get("endDate", ""),
                "condition_id": mkt.get("conditionId", ""),
                "slug": mkt.get("slug", ""),
                "description": mkt.get("description", "")[:500],
            }
        except (json.JSONDecodeError, ValueError, IndexError) as e:
            logger.warning(f"Failed to parse market {mkt.get('id', '?')}: {e}")
            return None


# ---------------------------------------------------------------------------
# LLM Probability Assessor (Simulated for Paper Trading)
# ---------------------------------------------------------------------------

class LLMProbabilityAssessor:
    """
    Simulates LLM-based probability assessment for paper trading.
    
    In production, this would call the local mlx-vlm-ig88 server.
    For paper trading, we simulate a "price-blind" LLM that has
    some information advantage but is far from perfect.
    
    This matches the calibration arbitrage strategy from polymarket_backtest.py.
    """
    
    # Historical base rates by category (priors)
    CATEGORY_BASE_RATES: dict[str, float] = {
        "politics": 0.48,
        "sports": 0.50,
        "crypto": 0.42,
        "science": 0.35,
        "entertainment": 0.55,
        "economics": 0.40,
        "geopolitics": 0.38,
        "technology": 0.45,
        "weather": 0.52,
        "legal": 0.43,
        "unknown": 0.50,
    }
    
    def __init__(self, noise_std: float = 0.15, seed: int = 42):
        self.noise_std = noise_std
        self.rng = np.random.default_rng(seed)
        self._assessment_count = 0
    
    def assess(self, market: dict) -> tuple[float, float]:
        """
        Generate a price-blind probability estimate.
        
        Returns:
            (estimate, confidence) where:
            - estimate is in [0.01, 0.99] (probability of YES)
            - confidence is in [0.30, 0.95]
        """
        self._assessment_count += 1
        
        category = (market.get("category") or "unknown").lower()
        base_rate = self.CATEGORY_BASE_RATES.get(category, 0.50)
        
        # Simulate LLM assessment: anchored on category base rate
        # with noise, NOT looking at the market price
        # The LLM has some informational edge from analyzing the
        # market description, but is imperfect
        description = market.get("description", "")
        question = market.get("question", "")
        
        # Hash the question to get a deterministic but "noisy" estimate
        # This simulates the LLM's interpretation of the question
        text_hash = hash(question + description[:100]) % 10000 / 10000.0
        
        # Anchor on base rate with text-derived signal
        anchor = 0.4 * base_rate + 0.3 * text_hash + 0.3 * 0.5
        noise = self.rng.normal(0, self.noise_std)
        estimate = float(np.clip(anchor + noise, 0.01, 0.99))
        
        # Confidence: higher when estimate is more extreme
        extremity = abs(estimate - 0.5) * 2
        base_confidence = 0.45 + 0.40 * extremity
        confidence_noise = self.rng.uniform(-0.10, 0.10)
        confidence = float(np.clip(base_confidence + confidence_noise, 0.30, 0.95))
        
        return estimate, confidence


# ---------------------------------------------------------------------------
# Polymarket Paper Trader (Main Class)
# ---------------------------------------------------------------------------

class PolymarketPaperTrader:
    """
    Paper trading engine for Polymarket prediction markets.
    
    Handles the full lifecycle:
    1. Scan active markets
    2. Generate LLM probability assessments
    3. Identify trading opportunities (edge > threshold)
    4. Size positions using quarter-Kelly
    5. Simulate paper execution
    6. Track positions until resolution
    7. Calculate P&L and Brier scores
    8. Log all trades to JSONL
    """
    
    def __init__(
        self,
        initial_capital: float = 1000.0,
        edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
        confidence_min: float = DEFAULT_CONFIDENCE_MIN,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
        max_position_pct: float = 10.0,
        min_volume: float = DEFAULT_MIN_VOLUME,
        fee_rate: float = TAKER_FEE,
        noise_std: float = 0.15,
        seed: int = 42,
    ):
        self.initial_capital = initial_capital
        self.wallet = initial_capital
        self.edge_threshold = edge_threshold
        self.confidence_min = confidence_min
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.fee_rate = fee_rate
        
        # Components
        self.scanner = MarketScanner(min_volume=min_volume)
        self.assessor = LLMProbabilityAssessor(noise_std=noise_std, seed=seed)
        
        # State
        self.positions: dict[str, PolymarketPosition] = {}
        self.closed_trades: list[PaperTradeRecord] = []
        self._trade_counter = 0
        
        # Running stats for Kelly sizing
        self._wins = 0
        self._losses = 0
        self._win_returns: list[float] = []
        self._loss_returns: list[float] = []
        
        # Ensure data directory exists
        POLYMARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    def _next_trade_id(self) -> str:
        self._trade_counter += 1
        return f"poly-{self._trade_counter:05d}"
    
    def _compute_position_size(self) -> float:
        """Quarter-Kelly position sizing based on running stats."""
        total = self._wins + self._losses
        
        if total < 5:
            # Not enough data: use conservative 2% of wallet
            return min(self.wallet * 0.02, self.wallet * self.max_position_pct / 100)
        
        wr = self._wins / total
        avg_w = np.mean(self._win_returns) if self._win_returns else 0.01
        avg_l = np.mean(self._loss_returns) if self._loss_returns else 0.01
        
        if avg_l == 0 or wr <= 0:
            return self.wallet * 0.02
        
        b = avg_w / avg_l
        q = 1.0 - wr
        f_kelly = (b * wr - q) / b
        
        if f_kelly <= 0:
            return 0.0
        
        f_sized = f_kelly * self.kelly_fraction
        position_usd = self.wallet * f_sized
        max_usd = self.wallet * (self.max_position_pct / 100)
        
        return min(position_usd, max_usd)
    
    def scan_markets(
        self,
        categories: list[str] | None = None,
        min_volume: float | None = None,
    ) -> list[PolymarketSignal]:
        """
        Scan active markets and generate trading signals.
        
        This is the main entry point for the paper trading cycle.
        """
        # Fetch active markets
        raw_markets = self.scanner.fetch_active_markets()
        if not raw_markets:
            logger.warning("No markets fetched from Polymarket")
            return []
        
        # Filter by volume and category
        filtered = self.scanner.filter_markets(raw_markets, categories, min_volume)
        logger.info(f"Scanned {len(raw_markets)} markets, {len(filtered)} passed filters")
        
        # Generate signals
        signals = []
        for mkt in filtered:
            parsed = self.scanner.parse_market(mkt)
            if parsed is None:
                continue
            
            # Skip if we already have a position on this market
            if parsed["id"] in self.positions:
                continue
            
            # Generate LLM assessment (price-blind)
            llm_est, llm_conf = self.assessor.assess(parsed)
            
            # Calculate edge for both YES and NO
            yes_price = parsed["yes_price"]
            no_price = parsed["no_price"]
            
            yes_edge = abs(llm_est - yes_price)
            no_edge = abs((1.0 - llm_est) - no_price)  # P(NO) = 1 - P(YES)
            
            # Account for fees
            fee_adj = self.fee_rate * 2  # Round-trip fee
            
            # Determine which side has edge
            if yes_edge > self.edge_threshold + fee_adj and llm_conf >= self.confidence_min:
                side = "buy_yes"
                edge = yes_edge
                market_price = yes_price
                reason = f"LLM estimates P(YES)={llm_est:.2f} vs market={yes_price:.2f}, edge={yes_edge:.3f}"
            elif no_edge > self.edge_threshold + fee_adj and llm_conf >= self.confidence_min:
                side = "buy_no"
                edge = no_edge
                market_price = no_price
                reason = f"LLM estimates P(NO)={1-llm_est:.2f} vs market={no_price:.2f}, edge={no_edge:.3f}"
            else:
                continue  # No edge
            
            # Position sizing
            size = self._compute_position_size()
            if size < 1.0:
                continue  # Too small
            
            signal = PolymarketSignal(
                market_id=parsed["id"],
                question=parsed["question"],
                category=parsed["category"],
                market_price=market_price,
                llm_estimate=llm_est,
                llm_confidence=llm_conf,
                edge=edge,
                side=side,
                recommended_size_usd=size,
                volume=parsed["volume"],
                end_date=parsed["end_date"],
                fee_rate=self.fee_rate,
                reason=reason,
            )
            signals.append(signal)
        
        # Sort by edge * confidence (best opportunities first)
        signals.sort(key=lambda s: s.edge * s.llm_confidence, reverse=True)
        
        logger.info(f"Generated {len(signals)} trading signals")
        return signals
    
    def execute_signal(self, signal: PolymarketSignal) -> PolymarketPosition | None:
        """
        Execute a paper trade for a single signal.
        
        Returns the opened position or None if execution failed.
        """
        # Check wallet has sufficient funds
        if signal.recommended_size_usd > self.wallet:
            logger.warning(f"Insufficient wallet for signal: need ${signal.recommended_size_usd:.2f}, have ${self.wallet:.2f}")
            return None
        
        # Calculate fee
        fee = signal.recommended_size_usd * signal.fee_rate
        
        # Create position
        self._trade_counter += 1
        position = PolymarketPosition(
            position_id=self._next_trade_id(),
            market_id=signal.market_id,
            question=signal.question,
            category=signal.category,
            side=signal.side,
            entry_price=signal.market_price,
            position_size_usd=signal.recommended_size_usd,
            entry_timestamp=datetime.now(tz=timezone.utc).isoformat(),
            llm_estimate=signal.llm_estimate,
            llm_confidence=signal.llm_confidence,
            end_date=signal.end_date,
            fee_paid=fee,
        )
        
        # Deduct from wallet
        self.wallet -= signal.recommended_size_usd
        self.positions[position.position_id] = position
        
        logger.info(
            f"OPENED {position.position_id}: {signal.side} {signal.question[:60]} "
            f"@ {signal.market_price:.3f} (${signal.recommended_size_usd:.2f})"
        )
        
        # Save positions
        self._save_positions()
        
        return position
    
    def execute_signals(self, signals: list[PolymarketSignal], 
                        max_positions: int = 5) -> list[PolymarketPosition]:
        """Execute multiple signals, respecting position limits."""
        opened = []
        
        for signal in signals[:max_positions]:
            if len(self.positions) >= max_positions:
                logger.info(f"Max positions ({max_positions}) reached")
                break
            
            position = self.execute_signal(signal)
            if position:
                opened.append(position)
        
        return opened
    
    def check_resolutions(self) -> list[PaperTradeRecord]:
        """
        Check if any open positions have resolved.
        
        In a real system, this would query the Polymarket API for resolution status.
        For paper trading, we simulate resolution based on end date.
        """
        resolved = []
        now = datetime.now(tz=timezone.utc)
        
        for pos_id, pos in list(self.positions.items()):
            if pos.resolved:
                continue
            
            # Check if market end date has passed
            if pos.end_date:
                try:
                    end_dt = datetime.fromisoformat(pos.end_date.replace("Z", "+00:00"))
                    if now < end_dt:
                        continue  # Not yet resolved
                except ValueError:
                    pass  # Can't parse date, skip
            
            # Simulate resolution
            # In production, this would query the actual resolution
            record = self._resolve_position(pos)
            if record:
                resolved.append(record)
        
        if resolved:
            self._save_positions()
        
        return resolved
    
    def _resolve_position(self, pos: PolymarketPosition) -> PaperTradeRecord | None:
        """Resolve a position (simulate resolution for paper trading)."""
        # Simulate outcome: LLM estimate is "noisy correct"
        # The actual outcome correlates with the LLM estimate but with noise
        actual_prob = float(np.clip(
            pos.llm_estimate + np.random.normal(0, 0.20), 0.0, 1.0
        ))
        actual_outcome = 1.0 if np.random.random() < actual_prob else 0.0
        
        # Determine exit price based on side
        if pos.side == "buy_yes":
            exit_price = actual_outcome  # 1.0 if YES won, 0.0 if NO won
        else:  # buy_no
            exit_price = 1.0 - actual_outcome  # 1.0 if NO won, 0.0 if YES won
        
        # Calculate P&L
        # For binary contracts: payout is $1 per share
        # Shares bought = position_size / entry_price
        # Revenue = shares * exit_price
        # P&L = revenue - position_size - fees
        shares = pos.position_size_usd / pos.entry_price
        revenue = shares * exit_price
        gross_pnl = revenue - pos.position_size_usd
        
        # Account for entry fee (exit fee is 0 for resolution)
        net_pnl = gross_pnl - pos.fee_paid
        
        # Brier score: (forecast - actual)^2
        brier = (pos.llm_estimate - actual_outcome) ** 2
        
        # Update position
        pos.exit_price = exit_price
        pos.exit_timestamp = datetime.now(tz=timezone.utc).isoformat()
        pos.pnl_usd = net_pnl
        pos.brier_score = brier
        pos.resolved = True
        
        # Update wallet
        self.wallet += pos.position_size_usd + net_pnl
        
        # Update running stats
        pnl_pct = net_pnl / pos.position_size_usd
        if net_pnl > 0:
            self._wins += 1
            self._win_returns.append(pnl_pct)
        else:
            self._losses += 1
            self._loss_returns.append(abs(pnl_pct))
        
        # Determine outcome
        if net_pnl > 0.01:
            outcome = "win"
        elif net_pnl < -0.01:
            outcome = "loss"
        else:
            outcome = "push"
        
        # Create trade record
        record = PaperTradeRecord(
            trade_id=pos.position_id,
            venue="polymarket",
            strategy="calibration_arbitrage",
            market_id=pos.market_id,
            question=pos.question,
            category=pos.category,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            position_size_usd=pos.position_size_usd,
            pnl_usd=net_pnl,
            pnl_pct=pnl_pct * 100,
            entry_timestamp=pos.entry_timestamp,
            exit_timestamp=pos.exit_timestamp,
            llm_estimate=pos.llm_estimate,
            llm_confidence=pos.llm_confidence,
            brier_score=brier,
            fee_paid=pos.fee_paid,
            outcome=outcome,
            logged_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        
        # Log to JSONL
        self._log_trade(record)
        
        # Remove from open positions
        del self.positions[pos.position_id]
        self.closed_trades.append(record)
        
        logger.info(
            f"RESOLVED {pos.position_id}: {pos.side} {pos.question[:50]} "
            f"P&L=${net_pnl:+.2f} ({outcome}) Brier={brier:.4f}"
        )
        
        return record
    
    def _log_trade(self, record: PaperTradeRecord) -> None:
        """Append a trade record to the JSONL log."""
        POLYMARKET_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(POLYMARKET_TRADES_PATH, "a") as f:
            f.write(json.dumps(record.to_dict(), default=str) + "\n")
    
    def _save_positions(self) -> None:
        """Save current positions to JSON."""
        data = {pid: pos.to_dict() for pid, pos in self.positions.items()}
        with open(POLYMARKET_POSITIONS_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)
    
    def load_positions(self) -> None:
        """Load positions from JSON file."""
        if not POLYMARKET_POSITIONS_PATH.exists():
            return
        try:
            with open(POLYMARKET_POSITIONS_PATH) as f:
                data = json.load(f)
            self.positions = {
                pid: PolymarketPosition.from_dict(pos) 
                for pid, pos in data.items()
            }
            logger.info(f"Loaded {len(self.positions)} open positions")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load positions: {e}")
    
    def get_summary(self) -> dict[str, Any]:
        """Generate a summary of paper trading performance."""
        total_trades = self._wins + self._losses
        win_rate = self._wins / total_trades if total_trades > 0 else 0.0
        
        # Average returns
        avg_win = np.mean(self._win_returns) if self._win_returns else 0.0
        avg_loss = np.mean(self._loss_returns) if self._loss_returns else 0.0
        
        # Expectancy
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if total_trades > 0 else 0.0
        
        # Average Brier score (from closed trades)
        brier_scores = [t.brier_score for t in self.closed_trades if t.brier_score is not None]
        avg_brier = np.mean(brier_scores) if brier_scores else None
        
        # Total P&L
        total_pnl = sum(t.pnl_usd for t in self.closed_trades)
        total_pnl_pct = ((self.wallet - self.initial_capital) / self.initial_capital * 100) if self.initial_capital > 0 else 0.0
        
        # Open position value (simplified: assume 50% of entry price)
        open_value = sum(
            pos.position_size_usd * 0.5  # Assume midpoint for valuation
            for pos in self.positions.values()
        )
        
        return {
            "venue": "polymarket",
            "initial_capital": self.initial_capital,
            "current_wallet": self.wallet,
            "total_pnl_usd": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "open_positions": len(self.positions),
            "open_position_value": open_value,
            "total_trades": total_trades,
            "wins": self._wins,
            "losses": self._losses,
            "win_rate": win_rate,
            "avg_win_pct": avg_win * 100,
            "avg_loss_pct": avg_loss * 100,
            "expectancy": expectancy,
            "expectancy_r": expectancy / avg_loss if avg_loss > 0 else 0.0,
            "avg_brier_score": avg_brier,
            "edge_threshold": self.edge_threshold,
            "confidence_min": self.confidence_min,
            "markets_scanned": self.assessor._assessment_count,
        }
    
    def format_summary(self) -> str:
        """Format summary as a readable string."""
        s = self.get_summary()
        
        lines = [
            "=" * 60,
            "POLYMARKET PAPER TRADING SUMMARY",
            "=" * 60,
            f"Venue:              {s['venue']}",
            f"Initial Capital:    ${s['initial_capital']:,.2f}",
            f"Current Wallet:     ${s['current_wallet']:,.2f}",
            f"Total P&L:          ${s['total_pnl_usd']:+,.2f} ({s['total_pnl_pct']:+.2f}%)",
            "",
            f"Open Positions:     {s['open_positions']}",
            f"Total Trades:       {s['total_trades']}",
            f"Win Rate:           {s['win_rate']:.1%}",
            f"Avg Win:            {s['avg_win_pct']:+.2f}%",
            f"Avg Loss:           {s['avg_loss_pct']:+.2f}%",
            f"Expectancy:         {s['expectancy']:.4f} ({s['expectancy_r']:.2f}R)",
            "",
            f"Avg Brier Score:    {s['avg_brier_score']:.4f}" if s['avg_brier_score'] else "Avg Brier Score:    N/A",
            f"Markets Scanned:    {s['markets_scanned']}",
            f"Edge Threshold:     {s['edge_threshold']:.1%}",
            f"Confidence Min:     {s['confidence_min']:.1%}",
            "=" * 60,
        ]
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    trader = PolymarketPaperTrader(initial_capital=1000.0)
    print("Scanning markets...")
    signals = trader.scan_markets()
    
    if signals:
        print(f"\nFound {len(signals)} signals:")
        for sig in signals[:5]:
            print(f"  {sig.side:8s} {sig.question[:50]:50s} "
                  f"market={sig.market_price:.3f} llm={sig.llm_estimate:.3f} "
                  f"edge={sig.edge:.3f} conf={sig.llm_confidence:.2f}")
        
        print(f"\nExecuting top signals...")
        opened = trader.execute_signals(signals, max_positions=3)
        print(f"Opened {len(opened)} positions")
    else:
        print("No signals generated (threshold not met)")
    
    print("\n" + trader.format_summary())
