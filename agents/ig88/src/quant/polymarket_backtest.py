"""Polymarket prediction-market backtesting strategies.

Two strategies that exploit systematic mispricings in prediction markets:

1. CalibrationArbitrageBacktester — favourite-longshot bias exploitation.
   LLM probability assessment is price-blinded; the model never sees the
   current market price.  When |llm_estimate - market_price| exceeds the
   edge threshold and confidence is high enough, take the trade.

2. BaseRateAuditBacktester — base-rate mispricing exploitation.
   When a market's price diverges significantly from the historical base
   rate for that category of event, take the trade.

Both strategies use quarter-Kelly sizing, track Brier scores per trade,
and output BacktestStats via the shared engine.

Dependencies:
    backtest_engine — BacktestEngine, Trade, BacktestStats, ExitReason, TradeOutcome
    regime          — RegimeState
    config          — load_config (for risk / venue / graduation params)

Only stdlib + numpy.  No scipy, no pandas.
"""

from src.quant.base_backtester import BaseVenueBacktester, BacktestConfig
from src.quant.backtest_engine import (
    BacktestEngine,
    BacktestStats,
    ExitReason,
    Trade,
    TradeOutcome,
)
from src.quant.regime import RegimeState
from src.trading.config import load_config


# ---------------------------------------------------------------------------
# Shared data structures
# ---------------------------------------------------------------------------

@dataclass
class PolymarketMarket:
    """A single resolved prediction-market event."""
    question: str
    outcomes: list[str]             # e.g. ["Yes", "No"]
    market_price: float             # Price at entry (0-1 probability scale)
    actual_outcome: float           # 1.0 = YES resolved, 0.0 = NO resolved
    category: str                   # e.g. "politics", "sports", "crypto"
    resolution_timestamp: datetime
    volume: float                   # Total market volume in USD
    historical_base_rate: float | None = None  # Base rate for this category


# ---------------------------------------------------------------------------
# Brier score and calibration utilities
# ---------------------------------------------------------------------------

def brier_score(forecast: float, outcome: float) -> float:
    """Brier score: BS = (forecast - outcome)^2.  Lower is better."""
    return (forecast - outcome) ** 2


def calibration_curve(
    forecasts: list[float],
    outcomes: list[float],
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute binned calibration: group by predicted probability, compare
    to observed resolution rate.

    Returns dict with:
        bins          — list of (bin_lo, bin_hi) tuples
        bin_counts    — number of forecasts in each bin
        mean_forecast — average forecast in each bin
        mean_outcome  — average actual outcome in each bin  (= observed freq)
        calibration_error — mean absolute (mean_forecast - mean_outcome)
    """
    fa = np.array(forecasts, dtype=np.float64)
    oa = np.array(outcomes, dtype=np.float64)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[tuple[float, float]] = []
    bin_counts: list[int] = []
    mean_forecast: list[float] = []
    mean_outcome: list[float] = []

    for i in range(n_bins):
        lo, hi = float(bin_edges[i]), float(bin_edges[i + 1])
        if i == n_bins - 1:
            mask = (fa >= lo) & (fa <= hi)
        else:
            mask = (fa >= lo) & (fa < hi)

        bins.append((lo, hi))
        count = int(mask.sum())
        bin_counts.append(count)

        if count > 0:
            mean_forecast.append(float(fa[mask].mean()))
            mean_outcome.append(float(oa[mask].mean()))
        else:
            mean_forecast.append((lo + hi) / 2)
            mean_outcome.append(0.0)

    # Mean absolute calibration error (only over populated bins)
    populated = [(mf, mo) for mf, mo, c in zip(mean_forecast, mean_outcome, bin_counts) if c > 0]
    if populated:
        cal_error = float(np.mean([abs(mf - mo) for mf, mo in populated]))
    else:
        cal_error = 1.0

    return {
        "bins": bins,
        "bin_counts": bin_counts,
        "mean_forecast": mean_forecast,
        "mean_outcome": mean_outcome,
        "calibration_error": cal_error,
    }


def format_calibration_table(cal: dict[str, Any]) -> str:
    """Human-readable calibration table."""
    lines = [
        "Calibration Curve:",
        f"{'Bin':>12s}  {'Count':>6s}  {'Forecast':>9s}  {'Observed':>9s}  {'Gap':>7s}",
        "-" * 52,
    ]
    for (lo, hi), count, mf, mo in zip(
        cal["bins"], cal["bin_counts"], cal["mean_forecast"], cal["mean_outcome"]
    ):
        gap = abs(mf - mo)
        lines.append(
            f"  [{lo:.2f},{hi:.2f})  {count:6d}  {mf:9.4f}  {mo:9.4f}  {gap:7.4f}"
        )
    lines.append(f"Mean calibration error: {cal['calibration_error']:.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Synthetic market generation
# ---------------------------------------------------------------------------

CATEGORIES = [
    "politics",
    "sports",
    "crypto",
    "science",
    "entertainment",
    "economics",
    "geopolitics",
    "technology",
    "weather",
    "legal",
]

# Historical base rates by category — rough priors for how often YES resolves.
# These are illustrative; real base rates would come from resolved market data.
CATEGORY_BASE_RATES: dict[str, float] = {
    "politics":      0.48,
    "sports":        0.50,
    "crypto":        0.42,
    "science":       0.35,
    "entertainment": 0.55,
    "economics":     0.40,
    "geopolitics":   0.38,
    "technology":    0.45,
    "weather":       0.52,
    "legal":         0.43,
}

_QUESTION_TEMPLATES: dict[str, list[str]] = {
    "politics": [
        "Will {candidate} win the {year} {office} election?",
        "Will {country} hold elections before {date}?",
        "Will {party} retain majority in {body}?",
    ],
    "sports": [
        "Will {team} win the {year} {league} championship?",
        "Will {player} score {n}+ goals this season?",
        "Will {team_a} beat {team_b} on {date}?",
    ],
    "crypto": [
        "Will {token} exceed ${price} by {date}?",
        "Will {protocol} TVL exceed ${tvl}B by {date}?",
        "Will {token} be listed on {exchange} by {date}?",
    ],
    "science": [
        "Will {agency} confirm {discovery} by {date}?",
        "Will a {type} vaccine reach Phase 3 by {date}?",
        "Will {country} launch a crewed mission by {date}?",
    ],
    "entertainment": [
        "Will {movie} gross over ${amount}M worldwide?",
        "Will {show} be renewed for season {n}?",
        "Will {artist} release an album in {year}?",
    ],
    "economics": [
        "Will the Fed cut rates before {date}?",
        "Will US GDP growth exceed {pct}% in Q{q} {year}?",
        "Will {country} enter recession by {date}?",
    ],
    "geopolitics": [
        "Will {country_a} and {country_b} reach agreement by {date}?",
        "Will sanctions on {country} be lifted by {date}?",
        "Will {org} expand membership by {date}?",
    ],
    "technology": [
        "Will {company} ship {product} by {date}?",
        "Will {model} achieve {benchmark} by {date}?",
        "Will a major AI lab release {type} model by {date}?",
    ],
    "weather": [
        "Will {region} experience a Category {n}+ hurricane in {year}?",
        "Will average temperature in {city} exceed {temp}F in {month}?",
        "Will {event} cause ${amount}B+ in damage in {year}?",
    ],
    "legal": [
        "Will {case} be decided by {date}?",
        "Will {company} settle {lawsuit} by {date}?",
        "Will {regulation} be enacted by {date}?",
    ],
}


def generate_synthetic_markets(
    n: int = 250,
    seed: int = 42,
) -> list[PolymarketMarket]:
    """Generate n synthetic resolved prediction markets for backtesting.

    Design choices:
      - Price distribution is NOT uniform: deliberately over-represents
        tails (<0.15 and >0.85) to test favourite-longshot bias.
      - Resolution is correlated with price but with realistic noise —
        markets priced at 0.70 resolve YES roughly 70% of the time, with
        some category-specific skew.
      - Volume follows a log-normal so a few high-volume markets dominate.
    """
    rng = np.random.default_rng(seed)
    markets: list[PolymarketMarket] = []

    base_time = datetime(2025, 1, 1)

    for i in range(n):
        category = CATEGORIES[i % len(CATEGORIES)]
        base_rate = CATEGORY_BASE_RATES[category]

        # Price distribution: mixture of uniform-ish center and heavier tails
        u = rng.random()
        if u < 0.20:
            # Low tail — overrepresent <15% prices
            price = rng.uniform(0.03, 0.15)
        elif u < 0.40:
            # High tail — overrepresent >85% prices
            price = rng.uniform(0.85, 0.97)
        else:
            # Mid range
            price = rng.uniform(0.10, 0.90)

        # Resolution: mostly follows price, but with favourite-longshot bias
        # Markets priced <15% resolve YES LESS often than implied (bias toward NO)
        # Markets priced >85% resolve YES MORE often than implied (bias toward YES)
        if price < 0.15:
            # Favourite-longshot: actual YES rate is ~60-80% of implied
            effective_prob = price * rng.uniform(0.50, 0.85)
        elif price > 0.85:
            # Favourite-longshot: actual YES rate is higher than implied
            # Push toward 1.0 — the favourite underpriced
            effective_prob = price + (1.0 - price) * rng.uniform(0.20, 0.60)
        else:
            # Mid-range: add category noise around the market price
            noise = rng.normal(0, 0.08)
            effective_prob = np.clip(price + noise, 0.01, 0.99)

        actual_outcome = 1.0 if rng.random() < effective_prob else 0.0

        # Volume: log-normal, median ~$50k, some outliers to $5M+
        volume = float(rng.lognormal(mean=10.8, sigma=1.2))

        # Generate a plausible question string
        templates = _QUESTION_TEMPLATES.get(category, ["Will event {i} happen?"])
        question = rng.choice(templates).format(
            candidate="Candidate", year="2025", office="presidential",
            country="Country", date="2025-12-31", party="Party", body="Senate",
            team="Team", player="Player", league="League", n=i % 10 + 1,
            team_a="Team A", team_b="Team B", token="TOKEN", price=i * 100 + 1000,
            protocol="Protocol", tvl=i % 5 + 1, exchange="Exchange",
            agency="Agency", discovery="discovery", type="novel",
            movie="Movie", show="Show", amount=i * 50 + 100, artist="Artist",
            pct=i % 4 + 1, q=i % 4 + 1, country_a="Country A",
            country_b="Country B", org="Organization", company="Company",
            product="Product", model="Model", benchmark="benchmark",
            region="Atlantic", city="Phoenix", temp=110, month="July",
            event="Hurricane", case="Case", lawsuit="lawsuit",
            regulation="regulation", i=i,
        )

        resolution_ts = base_time + timedelta(
            days=int(rng.uniform(1, 365)),
            hours=int(rng.uniform(0, 24)),
        )

        markets.append(PolymarketMarket(
            question=question,
            outcomes=["Yes", "No"],
            market_price=float(np.clip(price, 0.01, 0.99)),
            actual_outcome=actual_outcome,
            category=category,
            resolution_timestamp=resolution_ts,
            volume=volume,
            historical_base_rate=base_rate,
        ))

    return markets


# ---------------------------------------------------------------------------
# LLM probability simulation (for backtesting only)
# ---------------------------------------------------------------------------

def simulate_llm_estimate(
    actual_outcome: float,
    category: str,
    rng: np.random.Generator,
    noise_std: float = 0.15,
) -> tuple[float, float]:
    """Simulate a calibrated-ish LLM probability estimate.

    The LLM is price-blinded — it does NOT see the market price.
    For backtesting we simulate this by anchoring on the actual outcome
    with substantial noise, producing an estimate that is better than
    random but far from perfect.

    Returns:
        (estimate, confidence) where estimate is in [0.01, 0.99]
        and confidence is in [0.3, 0.95].
    """
    # Anchor on outcome but add heavy noise to simulate imperfect knowledge
    base = actual_outcome  # 0.0 or 1.0
    # Pull toward category base rate for realism
    category_rate = CATEGORY_BASE_RATES.get(category, 0.5)
    anchor = 0.55 * base + 0.25 * category_rate + 0.20 * 0.5
    noise = rng.normal(0, noise_std)
    estimate = float(np.clip(anchor + noise, 0.01, 0.99))

    # Confidence: higher when estimate is more extreme (model is "sure")
    extremity = abs(estimate - 0.5) * 2  # 0 at 0.5, 1 at extremes
    base_confidence = 0.45 + 0.40 * extremity
    confidence_noise = rng.uniform(-0.10, 0.10)
    confidence = float(np.clip(base_confidence + confidence_noise, 0.30, 0.95))

    return estimate, confidence


# ---------------------------------------------------------------------------
# Strategy 1: Calibration Arbitrage
# ---------------------------------------------------------------------------

class CalibrationArbitrageBacktester(BaseVenueBacktester):
    \"\"\"Exploit favourite-longshot bias via price-blinded LLM assessment.

    Entry logic:
      1. LLM produces probability estimate WITHOUT seeing market price.
      2. If |llm_estimate - market_price| > edge_threshold: potential trade.
      3. If LLM confidence >= confidence_min: take the trade.
      4. Side: buy YES if llm_estimate > market_price, buy NO otherwise.

    Sizing: quarter-Kelly based on running win/loss stats.

    Tracking: Brier score per trade, calibration curve over all trades.
    \"\"\"

    def __init__(
        self,
        edge_threshold: float = 0.05,
        confidence_min: float = 0.60,
        kelly_fraction: float = 0.25,
        max_position_pct: float = 10.0,
        initial_capital: float = 10_000.0,
        noise_std: float = 0.15,
        seed: int = 42,
    ):
        config = BacktestConfig(
            initial_capital=initial_capital, 
            kelly_fraction=kelly_fraction, 
            max_position_pct=max_position_pct
        )
        super().__init__(config)
        self.edge_threshold = edge_threshold
        self.confidence_min = confidence_min
        self.noise_std = noise_std
        self.rng = np.random.default_rng(seed)

        self.engine = BacktestEngine(initial_capital=initial_capital)
        self.forecasts: list[float] = []
        self.actuals: list[float] = []
        self.brier_scores: list[float] = []

    def _kelly_position_size(self, wallet_usd: float) -> float:
        """Compute quarter-Kelly position size from running stats."""
        if self._wins + self._losses < 5:
            # Not enough data — use minimum fixed size
            return min(wallet_usd * 0.02, wallet_usd * self.max_position_pct / 100)

        total = self._wins + self._losses
        wr = self._wins / total
        avg_w = float(np.mean(self._win_returns)) if self._win_returns else 0.0
        avg_l = float(np.mean(np.abs(self._loss_returns))) if self._loss_returns else 0.01

        if avg_l == 0 or wr <= 0:
            return 0.0

        b = avg_w / avg_l
        q = 1.0 - wr
        f_kelly = (b * wr - q) / b

        if f_kelly <= 0:
            return 0.0

        f_sized = f_kelly * self.kelly_fraction
        position_usd = wallet_usd * f_sized
        max_usd = wallet_usd * (self.max_position_pct / 100)
        return min(position_usd, max_usd)

    def run(self, markets: list[PolymarketMarket]) -> BacktestStats:
        """Run the calibration arbitrage backtest over resolved markets."""
        wallet = self.initial_capital
        trade_count = 0

        for mkt in markets:
            # Step 1: simulate price-blinded LLM estimate
            llm_est, confidence = simulate_llm_estimate(
                actual_outcome=mkt.actual_outcome,
                category=mkt.category,
                rng=self.rng,
                noise_std=self.noise_std,
            )

            # Step 2: compute edge
            edge = llm_est - mkt.market_price
            abs_edge = abs(edge)

            if abs_edge < self.edge_threshold:
                continue
            if confidence < self.confidence_min:
                continue

            # Step 3: determine side
            if edge > 0:
                side = "buy_yes"
                entry_price = mkt.market_price
            else:
                side = "buy_no"
                entry_price = 1.0 - mkt.market_price

            # Step 4: position sizing (quarter-Kelly)
            position_usd = self._kelly_position_size(wallet)
            if position_usd < 1.0:
                continue  # Too small to trade

            # Step 5: create and resolve trade
            trade_id = f"cal_arb_{trade_count:04d}"
            entry_ts = mkt.resolution_timestamp - timedelta(
                hours=self.rng.uniform(1, 72)
            )

            trade = Trade(
                trade_id=trade_id,
                venue="polymarket",
                strategy="calibration_arbitrage",
                pair=mkt.question[:80],
                entry_timestamp=entry_ts,
                entry_price=entry_price,
                position_size_usd=position_usd,
                regime_state=RegimeState.NEUTRAL,  # Polymarket runs all regimes
                side=side,
                leverage=1.0,
                llm_estimate=llm_est,
                market_price=mkt.market_price,
            )

            # Resolution: determine exit price
            if side == "buy_yes":
                exit_price = mkt.actual_outcome  # 1.0 if YES, 0.0 if NO
            else:
                exit_price = 1.0 - mkt.actual_outcome  # 1.0 if NO, 0.0 if YES

            # Brier score: forecast vs actual
            forecast = llm_est  # Our forecast of P(YES)
            bs = brier_score(forecast, mkt.actual_outcome)
            trade.brier_score = bs

            trade.close(
                exit_price=exit_price,
                exit_timestamp=mkt.resolution_timestamp,
                exit_reason=ExitReason.RESOLUTION,
                fees=position_usd * 0.02,  # ~2% Polymarket fees round-trip
            )

            self.engine.add_trade(trade)

            # Track for calibration
            self.forecasts.append(forecast)
            self.actuals.append(mkt.actual_outcome)
            self.brier_scores.append(bs)

            # Update running stats for Kelly
            if trade.pnl_pct is not None:
                if trade.outcome == TradeOutcome.WIN:
                    self._wins += 1
                    self._win_returns.append(trade.pnl_pct)
                elif trade.outcome == TradeOutcome.LOSS:
                    self._losses += 1
                    self._loss_returns.append(trade.pnl_pct)

            # Update wallet
            if trade.pnl_usd is not None:
                wallet += trade.pnl_usd
                wallet = max(wallet, 0.01)  # Can't go fully negative

            trade_count += 1

        return self.engine.compute_stats(
            venue="polymarket",
            strategy="calibration_arbitrage",
        )

    def calibration_analysis(self, n_bins: int = 10) -> dict[str, Any]:
        """Compute calibration curve over all trades taken."""
        if not self.forecasts:
            return {"error": "No trades taken"}
        return calibration_curve(self.forecasts, self.actuals, n_bins=n_bins)


# ---------------------------------------------------------------------------
# Strategy 2: Base Rate Audit
# ---------------------------------------------------------------------------

class BaseRateAuditBacktester:
    """Exploit base-rate mispricing: market price diverges from historical
    base rate for the event category.

    Entry logic:
      1. Compute divergence = market_price - historical_base_rate.
      2. If |divergence| > edge_threshold: potential trade.
      3. Side: if market overprices relative to base rate, buy NO.
                if market underprices relative to base rate, buy YES.

    This strategy does NOT use LLM estimates — it is purely statistical.

    Sizing: quarter-Kelly based on running stats.
    """

    def __init__(
        self,
        edge_threshold: float = 0.08,
        kelly_fraction: float = 0.25,
        max_position_pct: float = 10.0,
        initial_capital: float = 10_000.0,
        seed: int = 123,
    ):
        self.edge_threshold = edge_threshold
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.initial_capital = initial_capital
        self.rng = np.random.default_rng(seed)

        self.engine = BacktestEngine(initial_capital=initial_capital)
        self.forecasts: list[float] = []
        self.actuals: list[float] = []
        self.brier_scores: list[float] = []

        self._wins: int = 0
        self._losses: int = 0
        self._win_returns: list[float] = []
        self._loss_returns: list[float] = []

    def _kelly_position_size(self, wallet_usd: float) -> float:
        """Compute quarter-Kelly position size from running stats."""
        if self._wins + self._losses < 5:
            return min(wallet_usd * 0.02, wallet_usd * self.max_position_pct / 100)

        total = self._wins + self._losses
        wr = self._wins / total
        avg_w = float(np.mean(self._win_returns)) if self._win_returns else 0.0
        avg_l = float(np.mean(np.abs(self._loss_returns))) if self._loss_returns else 0.01

        if avg_l == 0 or wr <= 0:
            return 0.0

        b = avg_w / avg_l
        q = 1.0 - wr
        f_kelly = (b * wr - q) / b

        if f_kelly <= 0:
            return 0.0

        f_sized = f_kelly * self.kelly_fraction
        position_usd = wallet_usd * f_sized
        max_usd = wallet_usd * (self.max_position_pct / 100)
        return min(position_usd, max_usd)

    def run(self, markets: list[PolymarketMarket]) -> BacktestStats:
        """Run the base rate audit backtest over resolved markets."""
        wallet = self.initial_capital
        trade_count = 0

        for mkt in markets:
            if mkt.historical_base_rate is None:
                continue

            # Step 1: compute divergence
            divergence = mkt.market_price - mkt.historical_base_rate
            abs_divergence = abs(divergence)

            if abs_divergence < self.edge_threshold:
                continue

            # Step 2: determine side
            # Market overpriced relative to base rate -> fade it (buy NO)
            # Market underpriced relative to base rate -> buy YES
            if divergence > 0:
                # Market price too high vs base rate — bet NO
                side = "buy_no"
                entry_price = 1.0 - mkt.market_price
                forecast = mkt.historical_base_rate  # Our forecast = base rate
            else:
                # Market price too low vs base rate — bet YES
                side = "buy_yes"
                entry_price = mkt.market_price
                forecast = mkt.historical_base_rate

            # Step 3: position sizing
            position_usd = self._kelly_position_size(wallet)
            if position_usd < 1.0:
                continue

            # Step 4: create and resolve trade
            trade_id = f"base_rate_{trade_count:04d}"
            entry_ts = mkt.resolution_timestamp - timedelta(
                hours=self.rng.uniform(1, 72)
            )

            trade = Trade(
                trade_id=trade_id,
                venue="polymarket",
                strategy="base_rate_audit",
                pair=mkt.question[:80],
                entry_timestamp=entry_ts,
                entry_price=entry_price,
                position_size_usd=position_usd,
                regime_state=RegimeState.NEUTRAL,
                side=side,
                leverage=1.0,
                llm_estimate=forecast,
                market_price=mkt.market_price,
            )

            # Resolution
            if side == "buy_yes":
                exit_price = mkt.actual_outcome
            else:
                exit_price = 1.0 - mkt.actual_outcome

            # Brier score
            bs = brier_score(forecast, mkt.actual_outcome)
            trade.brier_score = bs

            trade.close(
                exit_price=exit_price,
                exit_timestamp=mkt.resolution_timestamp,
                exit_reason=ExitReason.RESOLUTION,
                fees=position_usd * 0.02,
            )

            self.engine.add_trade(trade)

            # Track
            self.forecasts.append(forecast)
            self.actuals.append(mkt.actual_outcome)
            self.brier_scores.append(bs)

            if trade.pnl_pct is not None:
                if trade.outcome == TradeOutcome.WIN:
                    self._wins += 1
                    self._win_returns.append(trade.pnl_pct)
                elif trade.outcome == TradeOutcome.LOSS:
                    self._losses += 1
                    self._loss_returns.append(trade.pnl_pct)

            if trade.pnl_usd is not None:
                wallet += trade.pnl_usd
                wallet = max(wallet, 0.01)

            trade_count += 1

        return self.engine.compute_stats(
            venue="polymarket",
            strategy="base_rate_audit",
        )

    def calibration_analysis(self, n_bins: int = 10) -> dict[str, Any]:
        """Compute calibration curve over all trades taken."""
        if not self.forecasts:
            return {"error": "No trades taken"}
        return calibration_curve(self.forecasts, self.actuals, n_bins=n_bins)


# ---------------------------------------------------------------------------
# Main — full backtest on synthetic data
# ---------------------------------------------------------------------------

def _separator(char: str = "=", width: int = 60) -> str:
    return char * width


if __name__ == "__main__":
    print(_separator())
    print("POLYMARKET STRATEGY BACKTESTER")
    print("Synthetic data — 250 resolved markets")
    print(_separator())

    # Generate synthetic markets
    markets = generate_synthetic_markets(n=250, seed=42)

    # Summary of generated data
    cat_counts: dict[str, int] = {}
    price_ranges = {"<0.15": 0, "0.15-0.85": 0, ">0.85": 0}
    yes_count = sum(1 for m in markets if m.actual_outcome == 1.0)
    for m in markets:
        cat_counts[m.category] = cat_counts.get(m.category, 0) + 1
        if m.market_price < 0.15:
            price_ranges["<0.15"] += 1
        elif m.market_price > 0.85:
            price_ranges[">0.85"] += 1
        else:
            price_ranges["0.15-0.85"] += 1

    print(f"\nMarkets generated: {len(markets)}")
    print(f"  YES outcomes: {yes_count} ({yes_count/len(markets):.1%})")
    print(f"  NO outcomes:  {len(markets) - yes_count} ({(len(markets) - yes_count)/len(markets):.1%})")
    print(f"\nPrice distribution:")
    for rng_label, count in price_ranges.items():
        print(f"  {rng_label}: {count} ({count/len(markets):.1%})")
    print(f"\nCategory distribution:")
    for cat, cnt in sorted(cat_counts.items()):
        print(f"  {cat}: {cnt}")

    # ---- Strategy 1: Calibration Arbitrage ----
    print(f"\n{_separator()}")
    print("STRATEGY 1: CALIBRATION ARBITRAGE")
    print(_separator())

    cal_bt = CalibrationArbitrageBacktester(
        edge_threshold=0.05,
        confidence_min=0.60,
        kelly_fraction=0.25,
        initial_capital=10_000.0,
        noise_std=0.15,
        seed=42,
    )
    cal_stats = cal_bt.run(markets)
    print(f"\n{cal_stats.summary()}")

    # Calibration analysis
    if cal_bt.forecasts:
        cal_curve = cal_bt.calibration_analysis(n_bins=10)
        print(f"\n{format_calibration_table(cal_curve)}")
        print(f"Average Brier score: {float(np.mean(cal_bt.brier_scores)):.4f}")

    # ---- Strategy 2: Base Rate Audit ----
    print(f"\n{_separator()}")
    print("STRATEGY 2: BASE RATE AUDIT")
    print(_separator())

    br_bt = BaseRateAuditBacktester(
        edge_threshold=0.08,
        kelly_fraction=0.25,
        initial_capital=10_000.0,
        seed=123,
    )
    br_stats = br_bt.run(markets)
    print(f"\n{br_stats.summary()}")

    # Calibration analysis
    if br_bt.forecasts:
        br_curve = br_bt.calibration_analysis(n_bins=10)
        print(f"\n{format_calibration_table(br_curve)}")
        print(f"Average Brier score: {float(np.mean(br_bt.brier_scores)):.4f}")

    # ---- Graduation check ----
    print(f"\n{_separator()}")
    print("GRADUATION CHECKS")
    print(_separator())

    try:
        cfg = load_config()
        engine_combined = BacktestEngine(initial_capital=10_000.0)
        engine_combined.add_trades(cal_bt.engine.trades)
        engine_combined.add_trades(br_bt.engine.trades)

        for strat_name, strat_stats in [
            ("calibration_arbitrage", cal_stats),
            ("base_rate_audit", br_stats),
        ]:
            grad = engine_combined.graduation_check(strat_stats, "polymarket")
            status = "READY FOR REVIEW" if grad["ready_for_review"] else "NOT READY"
            print(f"\n  {strat_name}: {status}")
            for check_name, check_data in grad["checks"].items():
                marker = "PASS" if check_data["pass"] else "FAIL"
                print(f"    [{marker}] {check_name}: {check_data['actual']} (req: {check_data['required']})")
    except Exception as e:
        print(f"\n  Graduation check skipped (config not available): {e}")

    # ---- Combined summary ----
    print(f"\n{_separator()}")
    print("COMBINED SUMMARY")
    print(_separator())

    total_trades = cal_stats.n_trades + br_stats.n_trades
    total_pnl = cal_stats.total_pnl_usd + br_stats.total_pnl_usd
    all_brier = cal_bt.brier_scores + br_bt.brier_scores
    avg_brier_all = float(np.mean(all_brier)) if all_brier else 0.0

    print(f"\n  Total trades taken: {total_trades} / {len(markets)} markets ({total_trades/len(markets):.1%})")
    print(f"  Combined P&L: ${total_pnl:,.2f}")
    print(f"  Combined avg Brier: {avg_brier_all:.4f}")
    print(f"  Calibration Arb trades: {cal_stats.n_trades}")
    print(f"  Base Rate Audit trades: {br_stats.n_trades}")

    print(f"\n{_separator()}")
    print("Backtest complete.")
