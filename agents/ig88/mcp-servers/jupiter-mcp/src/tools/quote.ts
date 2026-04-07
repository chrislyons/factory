// jupiter_quote — GET https://api.jup.ag/ultra/v1/order
//
// Returns a swap quote with real AMM slippage estimate. This is the key tool for
// replacing the modeled 0.04% KuCoin cost assumption with actual on-chain data.
// The quote includes priceImpactPct and routePlan, giving true execution cost.

import { fetchWithTimeout } from "../utils/fetch.js";

const JUPITER_ORDER_URL = "https://api.jup.ag/ultra/v1/order";

// Well-known mint addresses for convenience
export const KNOWN_MINTS = {
  SOL: "So11111111111111111111111111111111111111112",
  USDC: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  USDT: "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
} as const;

export const quoteTool = {
  name: "jupiter_quote",
  description:
    "Get a swap quote from Jupiter Ultra. Returns real AMM slippage, price impact, and route. " +
    "Use this to measure actual execution costs vs the 0.04% KuCoin assumption from Phase 3. " +
    "Amount is in base units: SOL uses lamports (1 SOL = 1,000,000,000), " +
    "USDC uses micro-USDC (1 USDC = 1,000,000).",
  inputSchema: {
    type: "object",
    properties: {
      inputMint: {
        type: "string",
        description: "Input token mint address (e.g. SOL: So11111111111111111111111111111111111111112)",
      },
      outputMint: {
        type: "string",
        description: "Output token mint address (e.g. USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)",
      },
      amount: {
        type: "number",
        description: "Amount in base units (lamports for SOL, micro-USDC for USDC)",
      },
      slippageBps: {
        type: "number",
        description: "Max slippage in basis points. Default: 50 (0.5%). Increase for volatile tokens.",
        default: 50,
      },
    },
    required: ["inputMint", "outputMint", "amount"],
  },
} as const;

interface QuoteResponse {
  inputMint: string;
  outputMint: string;
  inAmount: string;
  outAmount: string;
  priceImpactPct: string;
  slippageBps: number;
  routePlan?: unknown[];
  contextSlot?: number;
  timeTaken?: number;
  [key: string]: unknown;
}

interface QuoteResult {
  quote: QuoteResponse;
  cost_analysis: {
    price_impact_pct: number;
    price_impact_bps: number;
    vs_kucoin_04pct_bps: number;
    vs_kucoin_04pct_label: string;
  };
  timestamp: string;
}

export async function handleQuote(
  args: { inputMint: string; outputMint: string; amount: number; slippageBps?: number },
  apiKey?: string
): Promise<QuoteResult> {
  const params = new URLSearchParams({
    inputMint: args.inputMint,
    outputMint: args.outputMint,
    amount: args.amount.toString(),
    slippageBps: (args.slippageBps ?? 50).toString(),
  });

  const headers: Record<string, string> = {};
  if (apiKey) headers["x-api-key"] = apiKey;

  const response = await fetchWithTimeout(`${JUPITER_ORDER_URL}?${params}`, { headers }, 10000);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Jupiter order API ${response.status}: ${body}`);
  }

  const quote = await response.json() as QuoteResponse;

  // Derive cost analysis for backtesting comparison
  const priceImpactPct = parseFloat(quote.priceImpactPct ?? "0");
  const priceImpactBps = priceImpactPct * 100;
  const kucoinBps = 4; // 0.04% = 4 bps

  return {
    quote,
    cost_analysis: {
      price_impact_pct: priceImpactPct,
      price_impact_bps: priceImpactBps,
      vs_kucoin_04pct_bps: priceImpactBps - kucoinBps,
      vs_kucoin_04pct_label:
        priceImpactBps <= kucoinBps
          ? `cheaper_than_kucoin_by_${(kucoinBps - priceImpactBps).toFixed(2)}bps`
          : `more_expensive_than_kucoin_by_${(priceImpactBps - kucoinBps).toFixed(2)}bps`,
    },
    timestamp: new Date().toISOString(),
  };
}
