// IG-88 Codified Scanner
// Deterministic regime detection and candidate scoring

import type { MarketData, Regime, Candidate, ScanResult, Signal } from './types.js';
import { getMarketData, getTrendingTokens } from './coingecko.js';

// Generate cycle ID: CXXX
let cycleCounter = 0;
function generateCycleId(): string {
  cycleCounter++;
  return `C${String(cycleCounter).padStart(3, '0')}`;
}

// Check if weekend (lower liquidity)
function isWeekend(): boolean {
  const day = new Date().getUTCDay();
  return day === 0 || day === 6;
}

// Regime Detection (deterministic rules)
function detectRegime(market: MarketData): Regime {
  const { btc, eth, sol } = market;
  const factors: string[] = [];
  let confidence = 0.5;

  // RISK_ON conditions
  if (btc.change24h > 2) {
    factors.push(`BTC strong (+${btc.change24h.toFixed(1)}%)`);
    confidence += 0.2;
  }
  if (btc.change24h > 0 && sol.change24h > 3) {
    factors.push(`SOL outperforming (+${sol.change24h.toFixed(1)}%)`);
    confidence += 0.15;
  }
  if (eth.change24h > 2 && sol.change24h > 2) {
    factors.push('Broad alt strength');
    confidence += 0.15;
  }

  // RISK_OFF conditions
  if (btc.change24h < -3) {
    factors.push(`BTC dump (${btc.change24h.toFixed(1)}%)`);
    confidence -= 0.3;
  }
  if (btc.change24h < -1 && eth.change24h < -1 && sol.change24h < -1) {
    factors.push('Broad market weakness');
    confidence -= 0.2;
  }

  // Weekend penalty
  if (isWeekend()) {
    factors.push('Weekend (lower liquidity)');
    confidence -= 0.1;
  }

  // Clamp confidence
  confidence = Math.max(0, Math.min(1, confidence));

  // Determine status
  let status: 'RISK_ON' | 'RISK_OFF' | 'UNCERTAIN';
  if (confidence >= 0.65) {
    status = 'RISK_ON';
  } else if (confidence <= 0.35) {
    status = 'RISK_OFF';
  } else {
    status = 'UNCERTAIN';
  }

  if (factors.length === 0) {
    factors.push('No strong directional signals');
  }

  return { status, confidence, factors };
}

// Candidate Scoring (0-7 scale)
function scoreCandidate(candidate: Candidate, regime: Regime): Candidate {
  let score = 0;
  const reasons: string[] = [];

  // Rank score
  if (candidate.rank !== null && candidate.rank < 200) {
    score += 1;
    reasons.push(`Top 200 rank (#${candidate.rank})`);
  }

  // Momentum score (sweet spot: moved but not exhausted)
  if (candidate.change24h >= 5 && candidate.change24h < 30) {
    score += 1;
    reasons.push(`Healthy momentum (+${candidate.change24h.toFixed(1)}%)`);
  } else if (candidate.change24h >= 30 && candidate.change24h < 100) {
    score += 2;
    reasons.push(`Strong momentum (+${candidate.change24h.toFixed(1)}%)`);
  } else if (candidate.change24h >= 100) {
    // Already pumped - risky to chase
    reasons.push(`⚠️ Extended (+${candidate.change24h.toFixed(1)}%)`);
  } else if (candidate.change24h < 0) {
    reasons.push(`Negative momentum (${candidate.change24h.toFixed(1)}%)`);
  }

  // Weekend check
  if (!isWeekend()) {
    score += 1;
    reasons.push('Weekday (better liquidity)');
  }

  // Volume check (if available)
  if (candidate.volume24h !== null && candidate.volume24h > 10_000_000) {
    score += 1;
    reasons.push(`Good volume ($${(candidate.volume24h / 1_000_000).toFixed(1)}M)`);
  }

  // Trending bonus
  score += 1;
  reasons.push('On trending list');

  // Regime bonus
  if (regime.status === 'RISK_ON') {
    score += 1;
    reasons.push('Favorable regime');
  }

  return {
    ...candidate,
    score,
    reasons,
  };
}

// Filter out tokens we don't want
function filterCandidates(candidates: Candidate[]): Candidate[] {
  const skipSymbols = ['BTC', 'ETH', 'USDT', 'USDC', 'PAXG', 'WBTC', 'STETH'];

  return candidates.filter((c) => {
    // Skip stablecoins and wrapped assets
    if (skipSymbols.includes(c.symbol)) return false;
    // Skip if already pumped too much (chasing)
    if (c.change24h > 200) return false;
    // Skip if dumping
    if (c.change24h < -10) return false;
    return true;
  });
}

// Main scan function
export async function runScan(): Promise<ScanResult> {
  const cycleId = generateCycleId();
  const timestamp = new Date().toISOString();

  // Fetch data
  const market = await getMarketData();
  const rawCandidates = await getTrendingTokens();

  // Detect regime
  const regime = detectRegime(market);

  // Filter and score candidates
  const filtered = filterCandidates(rawCandidates);
  const candidates = filtered
    .map((c) => scoreCandidate(c, regime))
    .sort((a, b) => b.score - a.score);

  // Determine if we should escalate to LLM
  const hasQualityCandidate = candidates.some((c) => c.score >= 4);
  const regimeAcceptable = regime.confidence >= 0.5;
  const shouldEscalate = regimeAcceptable && hasQualityCandidate;

  // Determine signal
  let signal: Signal = 'NO_TRADE';
  let reasoning = '';

  if (regime.status === 'RISK_OFF') {
    signal = 'NO_TRADE';
    reasoning = `Regime RISK_OFF (${regime.confidence.toFixed(2)}). Standing aside.`;
  } else if (!hasQualityCandidate) {
    signal = 'NO_TRADE';
    reasoning = 'No candidates scoring ≥4/7. No quality setups.';
  } else if (regime.status === 'UNCERTAIN') {
    signal = 'WATCH';
    reasoning = `Regime uncertain (${regime.confidence.toFixed(2)}). Candidates exist but waiting for clarity.`;
  } else if (shouldEscalate) {
    signal = 'WATCH'; // Will become TRADE if LLM confirms
    reasoning = `Quality candidate found. Escalating to narrative analysis.`;
  }

  return {
    cycleId,
    timestamp,
    market,
    regime,
    candidates: candidates.slice(0, 5), // Top 5
    shouldEscalate,
    signal,
    reasoning,
  };
}

// Format result for console output
export function formatScanResult(result: ScanResult): string {
  const lines: string[] = [
    '═'.repeat(60),
    `IG-88 SCAN CYCLE ${result.cycleId}`,
    '═'.repeat(60),
    `Timestamp: ${result.timestamp}`,
    '',
    '── MARKET ──',
    `BTC: $${result.market.btc.price.toLocaleString()} (${result.market.btc.change24h >= 0 ? '+' : ''}${result.market.btc.change24h.toFixed(2)}%)`,
    `ETH: $${result.market.eth.price.toLocaleString()} (${result.market.eth.change24h >= 0 ? '+' : ''}${result.market.eth.change24h.toFixed(2)}%)`,
    `SOL: $${result.market.sol.price.toLocaleString()} (${result.market.sol.change24h >= 0 ? '+' : ''}${result.market.sol.change24h.toFixed(2)}%)`,
    '',
    '── REGIME ──',
    `Status: ${result.regime.status}`,
    `Confidence: ${result.regime.confidence.toFixed(2)}`,
    `Factors: ${result.regime.factors.join(', ')}`,
    '',
    '── CANDIDATES ──',
  ];

  if (result.candidates.length === 0) {
    lines.push('No qualifying candidates');
  } else {
    for (const c of result.candidates) {
      lines.push(`${c.symbol} (${c.score}/7): $${c.price.toFixed(6)} ${c.change24h >= 0 ? '+' : ''}${c.change24h.toFixed(1)}%`);
      lines.push(`  └─ ${c.reasons.join(', ')}`);
    }
  }

  lines.push('');
  lines.push('── DECISION ──');
  lines.push(`Signal: ${result.signal}`);
  lines.push(`Escalate to LLM: ${result.shouldEscalate ? 'YES' : 'NO'}`);
  lines.push(`Reasoning: ${result.reasoning}`);
  lines.push('═'.repeat(60));

  return lines.join('\n');
}

// CLI entry point
if (import.meta.url === `file://${process.argv[1]}`) {
  runScan()
    .then((result) => {
      console.log(formatScanResult(result));
      process.exit(result.shouldEscalate ? 1 : 0); // Exit 1 if LLM needed
    })
    .catch((err) => {
      console.error('Scan failed:', err);
      process.exit(2);
    });
}
