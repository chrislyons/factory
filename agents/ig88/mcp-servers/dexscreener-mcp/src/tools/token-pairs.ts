// dex_token_pairs — GET https://api.dexscreener.com/token-pairs/v1/solana/{address}
// Returns all DEX venues for a token, sorted by liquidity.usd descending.
// Adds routing_recommendation: name of the highest-liquidity venue.
// Use before Jupiter swap to confirm TVL > threshold and avoid excessive slippage.

import { fetchWithTimeout } from "../utils/fetch.js";
import { DEX_BASE_URL } from "../constants.js";
import type { PairData } from "../types.js";

export const tokenPairsTool = {
  name: "dex_token_pairs",
  description:
    "Get all DEX trading pairs for a Solana token across every venue (Raydium, Orca, Meteora, etc.). " +
    "Sorted by liquidity USD descending. Includes a routing_recommendation field naming the " +
    "highest-liquidity venue. Use this for pre-trade liquidity validation before Jupiter swap — " +
    "confirm total TVL is above your slippage threshold before routing an order.",
  inputSchema: {
    type: "object",
    properties: {
      tokenAddress: {
        type: "string",
        description: "Solana mint address of the token",
      },
    },
    required: ["tokenAddress"],
  },
} as const;

export async function handleTokenPairs(
  args: { tokenAddress: string }
): Promise<{ pairs: unknown[]; routing_recommendation: string | null; total_liquidity_usd: number; timestamp: string }> {
  const { tokenAddress } = args;
  const url = `${DEX_BASE_URL}/token-pairs/v1/solana/${tokenAddress}`;

  const response = await fetchWithTimeout(url);
  if (!response.ok) {
    throw new Error(`Dexscreener token-pairs API ${response.status}: ${await response.text()}`);
  }

  const data = await response.json() as PairData[];
  const pairs = Array.isArray(data) ? data : [];

  // Sort by liquidity USD descending
  const sorted = [...pairs].sort((a, b) => {
    const aLiq = a.liquidity?.usd ?? 0;
    const bLiq = b.liquidity?.usd ?? 0;
    return bLiq - aLiq;
  });

  const topPair = sorted[0];
  const routing_recommendation = topPair?.dexId ?? null;
  const total_liquidity_usd = sorted.reduce((sum, p) => sum + (p.liquidity?.usd ?? 0), 0);

  return {
    pairs: sorted,
    routing_recommendation,
    total_liquidity_usd,
    timestamp: new Date().toISOString(),
  };
}
