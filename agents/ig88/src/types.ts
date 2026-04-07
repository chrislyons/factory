// IG-88 Core Types

export type RegimeStatus = 'RISK_ON' | 'RISK_OFF' | 'UNCERTAIN';
export type Signal = 'TRADE' | 'NO_TRADE' | 'WATCH';

export interface MarketData {
  btc: { price: number; change24h: number };
  eth: { price: number; change24h: number };
  sol: { price: number; change24h: number };
  timestamp: string;
}

export interface Regime {
  status: RegimeStatus;
  confidence: number;
  factors: string[];
}

export interface Candidate {
  symbol: string;
  name: string;
  price: number;
  change24h: number;
  rank: number | null;
  volume24h: number | null;
  score: number;
  reasons: string[];
}

export interface ScanResult {
  cycleId: string;
  timestamp: string;
  market: MarketData;
  regime: Regime;
  candidates: Candidate[];
  shouldEscalate: boolean;
  signal: Signal;
  reasoning: string;
}

export interface TradeParams {
  token: string;
  entry: number;
  stopLoss: number;
  takeProfit: number;
  positionSize: number;
  conviction: number;
}

export interface CycleLog {
  cycleId: string;
  timestamp: string;
  regime: Regime;
  candidateCount: number;
  topCandidate: string | null;
  escalated: boolean;
  signal: Signal;
  tradeParams: TradeParams | null;
}

// Kill Zone Ladder (RP5096)
export type KillZonePhase = 0 | 1 | 2 | 3 | 4 | 5;

export interface KillZoneConfig {
  phase: KillZonePhase;
  capitalRange: [number, number];
  riskPercent: number;
  name: string;
}

export const KILL_ZONE_LADDER: Record<KillZonePhase, KillZoneConfig> = {
  0: { phase: 0, capitalRange: [200, 999], riskPercent: 15, name: 'Ignition' },
  1: { phase: 1, capitalRange: [1000, 1999], riskPercent: 10, name: 'Kill Zone Exit' },
  2: { phase: 2, capitalRange: [2000, 4999], riskPercent: 5, name: 'Threshold of Safety' },
  3: { phase: 3, capitalRange: [5000, 9999], riskPercent: 3, name: 'Capital Expansion' },
  4: { phase: 4, capitalRange: [10000, 49999], riskPercent: 2, name: 'Autonomous Growth' },
  5: { phase: 5, capitalRange: [50000, Infinity], riskPercent: 1, name: 'Sovereign Viability' },
};

// Win Rate Boundaries (RP5099)
export const WR_BOUNDARIES = {
  shutdown: 0.45, // Emergency stop if WR < 45%
  alert: 0.48,    // Alert if WR < 48%
  target: 0.53,   // Target WR for profitability
};

// Price Source Priority (RP5112)
export type PriceSource = 'kucoin' | 'coingecko' | 'jupiter' | 'coinpaprika';

export interface PriceConsensus {
  price: number;
  sources: PriceSource[];
  variance: number;
  confidence: number;
}

// Autonomous Cycle Output (for claude -p)
export interface AutonomousCycleResult {
  cycleId: string;
  timestamp: string;
  market: MarketData;
  regime: Regime;
  candidate: Candidate | null;
  narrative: {
    assessment: 'COHERENT' | 'NOISE' | 'SUSPICIOUS';
    conviction: number;
    catalyst: string;
    source: string;
    redFlags: string[];
  } | null;
  decision: {
    signal: Signal;
    reasoning: string;
  };
  trade: TradeParams | null;
}

// Error types for resilience
export interface CycleError {
  component: 'scanner' | 'api' | 'matrix' | 'claude' | 'unknown';
  message: string;
  recoverable: boolean;
  retryAfter?: number; // seconds
}

// Claude Permission Types (for streaming JSON mode)
export interface ClaudePermissionRequest {
  type: 'input_request';
  request_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
}

export interface ClaudePermissionResponse {
  type: 'permission_response';
  request_id: string;
  decision: 'allow' | 'deny';
  message?: string;
}

export interface PendingApproval {
  requestId: string;
  tool: string;
  input: Record<string, unknown>;
  matrixEventId: string;
  threadRootId: string;
  sender: string;
  timestamp: number;
}

// Sprint Types
export interface Sprint {
  name: string;
  threadRootId: string;
  startedAt: number;
  messageCount: number;
}

// Approval Configuration
export interface ApprovalConfig {
  timeoutMs: number;
  owner: string;
  autoApprovePatterns: string[];
  alwaysRequireApproval: string[];
}
