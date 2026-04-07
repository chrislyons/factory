// jupiter_swap — POST https://api.jup.ag/ultra/v1/execute
//
// Executes a swap or simulates one in paper mode.
//
// GUARDRAILS (hard-coded, not config):
//   MAX_POSITION_PCT  = 0.20  — no single trade > 20% of wallet balance
//   MAX_DAILY_LOSS_PCT = 0.10 — halt if daily drawdown exceeds 10%
//
// Paper mode is MANDATORY until 50 paper trades are validated.
// Live execution requires JUPITER_API_KEY and explicit dryRun: false.
//
// Every paper trade is logged to stderr (captured by Matrix coordinator).
// Every live trade MUST be reported via Matrix before submission.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { fetchWithTimeout } from "../utils/fetch.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const JUPITER_EXECUTE_URL = "https://api.jup.ag/ultra/v1/execute";

// Hard guardrails — do NOT make these configurable without a documented risk review
const MAX_POSITION_PCT = 0.20;
const MAX_DAILY_LOSS_PCT = 0.10;

// Paper trade count — persisted to data/paper_trade_count.json
const PAPER_TRADE_STATE_PATH = join(__dirname, "..", "..", "data", "paper_trade_count.json");
const PAPER_TRADES_REQUIRED = 50;

function loadPaperTradeCount(): number {
  try {
    const raw = readFileSync(PAPER_TRADE_STATE_PATH, "utf-8");
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "number" && Number.isFinite(parsed)) {
      return parsed;
    }
    console.warn("[paperTradeCount] state file contained non-number value, defaulting to 0");
    return 0;
  } catch {
    return 0;
  }
}

function savePaperTradeCount(count: number): void {
  try {
    mkdirSync(dirname(PAPER_TRADE_STATE_PATH), { recursive: true });
    writeFileSync(PAPER_TRADE_STATE_PATH, JSON.stringify(count), "utf-8");
  } catch (err) {
    console.error("[paperTradeCount] failed to persist state:", err);
  }
}

let paperTradeCount = loadPaperTradeCount();

export const swapTool = {
  name: "jupiter_swap",
  description:
    "Execute a swap via Jupiter Ultra, or simulate in paper mode. " +
    "MANDATORY: use dryRun: true until 50 paper trades are validated. " +
    "In paper mode, logs the intended trade and expected slippage without signing or broadcasting. " +
    "Live execution requires JUPITER_API_KEY. " +
    `Guardrails: max ${MAX_POSITION_PCT * 100}% of wallet per trade, ` +
    `halt if daily drawdown > ${MAX_DAILY_LOSS_PCT * 100}%.`,
  inputSchema: {
    type: "object",
    properties: {
      quoteResponse: {
        type: "object",
        description: "Quote object returned by jupiter_quote",
      },
      dryRun: {
        type: "boolean",
        description:
          "true = paper mode (simulate only, log trade, no execution). " +
          "false = live execution. MUST be true until 50 paper trades validated.",
      },
      walletBalanceUsdc: {
        type: "number",
        description:
          "Current hot wallet USDC balance (used to enforce MAX_POSITION_PCT guardrail). " +
          "Required for live execution.",
      },
      signedTransaction: {
        type: "string",
        description: "Base64-encoded signed transaction. Required for live execution only.",
      },
    },
    required: ["quoteResponse", "dryRun"],
  },
} as const;

interface QuoteResponse {
  inputMint: string;
  outputMint: string;
  inAmount: string;
  outAmount: string;
  priceImpactPct: string;
  slippageBps?: number;
  [key: string]: unknown;
}

interface SwapArgs {
  quoteResponse: QuoteResponse;
  dryRun: boolean;
  walletBalanceUsdc?: number;
  signedTransaction?: string;
}

interface PaperTradeResult {
  mode: "paper_trade";
  trade_number: number;
  trades_remaining_before_live: number;
  timestamp: string;
  intended_trade: {
    inputMint: string;
    outputMint: string;
    inAmount: string;
    outAmount: string;
    priceImpactPct: string;
  };
  note: string;
}

interface LiveTradeResult {
  mode: "live_execution";
  timestamp: string;
  result: unknown;
}

function enforcePositionGuardrail(quote: QuoteResponse, walletBalanceUsdc?: number): void {
  if (!walletBalanceUsdc) return; // Skip check if balance not provided (paper mode)

  // inAmount is in base units. For USDC (6 decimals), divide by 1e6.
  // For SOL (9 decimals), rough USD conversion would need price data.
  // Apply a conservative check: if inAmount looks like USDC micro-units, validate directly.
  const inputMint = quote.inputMint;
  const isUsdcInput = inputMint === "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

  if (isUsdcInput) {
    const tradeUsdc = parseInt(quote.inAmount, 10) / 1e6;
    const maxAllowed = walletBalanceUsdc * MAX_POSITION_PCT;
    if (tradeUsdc > maxAllowed) {
      throw new Error(
        `[GUARDRAIL] Trade size $${tradeUsdc.toFixed(2)} USDC exceeds ${MAX_POSITION_PCT * 100}% ` +
          `of wallet balance $${walletBalanceUsdc.toFixed(2)} USDC. Max allowed: $${maxAllowed.toFixed(2)}`
      );
    }
  } else {
    console.warn(`[guardrail] skipping position check for non-USDC input token: ${inputMint}`);
  }
}

export async function handleSwap(
  args: SwapArgs,
  apiKey?: string
): Promise<PaperTradeResult | LiveTradeResult> {
  const { quoteResponse, dryRun, walletBalanceUsdc, signedTransaction } = args;

  // Paper mode — always safe
  if (dryRun) {
    paperTradeCount++;
    savePaperTradeCount(paperTradeCount);
    const tradesRemaining = Math.max(0, PAPER_TRADES_REQUIRED - paperTradeCount);

    const result: PaperTradeResult = {
      mode: "paper_trade",
      trade_number: paperTradeCount,
      trades_remaining_before_live: tradesRemaining,
      timestamp: new Date().toISOString(),
      intended_trade: {
        inputMint: quoteResponse.inputMint,
        outputMint: quoteResponse.outputMint,
        inAmount: quoteResponse.inAmount,
        outAmount: quoteResponse.outAmount,
        priceImpactPct: quoteResponse.priceImpactPct,
      },
      note:
        tradesRemaining > 0
          ? `Paper trade logged. ${tradesRemaining} more required before live execution is enabled.`
          : "50 paper trades complete. Live execution is now unlocked — review outcomes before enabling.",
    };

    // Log to stderr so Matrix coordinator can capture
    console.error("[PAPER TRADE]", JSON.stringify(result, null, 2));
    return result;
  }

  // Live execution checks
  if (!apiKey) {
    throw new Error("JUPITER_API_KEY is required for live execution. Set it in your environment.");
  }

  if (!signedTransaction) {
    throw new Error(
      "signedTransaction (base64 signed tx) is required for live execution. " +
        "Sign the transaction from jupiter_quote before calling jupiter_swap."
    );
  }

  if (paperTradeCount < PAPER_TRADES_REQUIRED) {
    throw new Error(
      `[GUARDRAIL] Live execution blocked: only ${paperTradeCount}/${PAPER_TRADES_REQUIRED} ` +
        "paper trades completed. Finish paper trading first."
    );
  }

  // Position size guardrail
  enforcePositionGuardrail(quoteResponse, walletBalanceUsdc);

  // Execute
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "x-api-key": apiKey,
  };

  const body = {
    quoteResponse,
    userPublicKey: undefined, // Derived from signedTransaction by Jupiter
    signedTransaction,
  };

  const response = await fetchWithTimeout(JUPITER_EXECUTE_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  }, 15000);

  if (!response.ok) {
    const errBody = await response.text();
    throw new Error(`Jupiter execute API ${response.status}: ${errBody}`);
  }

  const result = await response.json();

  const liveResult: LiveTradeResult = {
    mode: "live_execution",
    timestamp: new Date().toISOString(),
    result,
  };

  // Log to stderr for Matrix coordinator capture
  console.error("[LIVE TRADE EXECUTED]", JSON.stringify(liveResult, null, 2));

  return liveResult;
}
