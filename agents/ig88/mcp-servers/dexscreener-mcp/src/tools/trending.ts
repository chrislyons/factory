// dex_trending — GET https://api.dexscreener.com/token-boosts/top/v1
// Returns top boosted Solana tokens by active boost count.
// Boosts are a market-attention proxy: heavily boosted tokens tend to have elevated volume.
// Results filtered to chainId === "solana".

import { fetchWithTimeout } from "../utils/fetch.js";
import { DEX_BASE_URL } from "../constants.js";

const DEFAULT_LIMIT = 20;

export const trendingTool = {
  name: "dex_trending",
  description:
    "Get top trending Solana tokens from Dexscreener by active boost count. " +
    "Boosts are a market-attention proxy — heavily boosted tokens tend to have elevated volume and momentum. " +
    "Use as a seed input for the scanner agent's token discovery pipeline. " +
    "Returns Solana-only results (chainId filter applied). Default limit: 20.",
  inputSchema: {
    type: "object",
    properties: {
      limit: {
        type: "number",
        description: "Maximum number of tokens to return (default: 20, max: 100)",
        minimum: 1,
        maximum: 100,
      },
    },
    required: [],
  },
} as const;

interface BoostEntry {
  url: string;
  chainId: string;
  tokenAddress: string;
  amount: number;
  totalAmount: number;
  icon?: string;
  header?: string;
  description?: string;
  links?: unknown[];
}

export async function handleTrending(
  args: { limit?: number }
): Promise<{ tokens: unknown[]; count: number; timestamp: string }> {
  const limit = Math.min(args.limit ?? DEFAULT_LIMIT, 100);
  const url = `${DEX_BASE_URL}/token-boosts/top/v1`;

  const response = await fetchWithTimeout(url);
  if (!response.ok) {
    throw new Error(`Dexscreener token-boosts API ${response.status}: ${await response.text()}`);
  }

  const data = await response.json() as BoostEntry[];
  const allEntries = Array.isArray(data) ? data : [];

  // Filter to Solana, apply limit
  const solanaTokens = allEntries
    .filter((entry) => entry.chainId === "solana")
    .slice(0, limit);

  return {
    tokens: solanaTokens,
    count: solanaTokens.length,
    timestamp: new Date().toISOString(),
  };
}
