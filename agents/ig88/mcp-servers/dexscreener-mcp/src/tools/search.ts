// dex_search — GET https://api.dexscreener.com/latest/dex/search?q={query}
// Searches Dexscreener for pairs matching a token name, symbol, or address.
// Results filtered to Solana only.
// Use to resolve ticker symbols → mint addresses before calling other tools.

import { fetchWithTimeout } from "../utils/fetch.js";
import { DEX_BASE_URL } from "../constants.js";

export const searchTool = {
  name: "dex_search",
  description:
    "Search Dexscreener for Solana tokens by name, symbol, or partial mint address. " +
    "Returns matching pairs with price and volume data. " +
    "Useful for converting a ticker symbol (e.g. 'JUP', 'BONK') to its mint address " +
    "before calling dex_token_info or dex_token_pairs.",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "Token name, symbol, or partial mint address to search for",
      },
    },
    required: ["query"],
  },
} as const;

interface SearchPair {
  chainId: string;
  dexId: string;
  pairAddress: string;
  baseToken: { address: string; name: string; symbol: string };
  quoteToken: { address: string; name: string; symbol: string };
  priceUsd?: string;
  volume?: { h24?: number };
  liquidity?: { usd?: number };
  [key: string]: unknown;
}

interface SearchResponse {
  pairs?: SearchPair[];
}

export async function handleSearch(
  args: { query: string }
): Promise<{ pairs: unknown[]; count: number; timestamp: string }> {
  const { query } = args;
  const url = `${DEX_BASE_URL}/latest/dex/search?q=${encodeURIComponent(query)}`;

  const response = await fetchWithTimeout(url);
  if (!response.ok) {
    throw new Error(`Dexscreener search API ${response.status}: ${await response.text()}`);
  }

  const data = await response.json() as SearchResponse;
  const allPairs = data.pairs ?? [];

  // Filter to Solana only
  const solanaPairs = allPairs.filter((p) => p.chainId === "solana");

  return {
    pairs: solanaPairs,
    count: solanaPairs.length,
    timestamp: new Date().toISOString(),
  };
}
