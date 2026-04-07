// jupiter_price — GET https://api.jup.ag/price/v2?ids=<mints>
// Falls back to CoinGecko if Jupiter doesn't have the token data.
//
// Jupiter Price API returns prices for Solana SPL tokens by mint address.
// CoinGecko is used as fallback for tokens not indexed by Jupiter, or on API errors.

import { fetchWithTimeout } from "../utils/fetch.js";

const JUPITER_PRICE_URL = "https://api.jup.ag/price/v3";
const COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price";

// Well-known mint → CoinGecko ID mapping (fallback path only)
const MINT_TO_GECKO: Record<string, string> = {
  So11111111111111111111111111111111111111112: "solana",
  EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v: "usd-coin",
  Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB: "tether",
  "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "wrapped-bitcoin",
  mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So: "msol",
  "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj": "lido-staked-sol",
  DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263: "bonk",
  EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm: "dogwifcoin",
  JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN: "jupiter-exchange-solana",
  "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "raydium",
  orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE: "orca",
  HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3: "pyth-network",
};

export const priceTool = {
  name: "jupiter_price",
  description:
    "Get real-time token prices from Jupiter (primary) with CoinGecko fallback. " +
    "Pass mint addresses for on-chain tokens. Up to 50 mints per request. " +
    "Common mints — SOL: So11111111111111111111111111111111111111112, " +
    "USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  inputSchema: {
    type: "object",
    properties: {
      mints: {
        type: "array",
        items: { type: "string" },
        description: "Solana mint addresses (up to 50)",
        maxItems: 50,
      },
    },
    required: ["mints"],
  },
} as const;

async function jupiterPrice(mints: string[], apiKey?: string): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {};
  if (apiKey) headers["x-api-key"] = apiKey;

  const url = `${JUPITER_PRICE_URL}?ids=${mints.join(",")}`;
  const response = await fetchWithTimeout(url, { headers });

  if (!response.ok) {
    throw new Error(`Jupiter price API ${response.status}: ${await response.text()}`);
  }

  const data = await response.json() as { data?: Record<string, unknown> };
  return data.data ?? {};
}

async function coingeckoPrice(mints: string[]): Promise<Record<string, unknown>> {
  const knownIds = mints
    .map((m) => MINT_TO_GECKO[m])
    .filter(Boolean)
    .join(",");

  if (!knownIds) return {};

  const url = `${COINGECKO_PRICE_URL}?ids=${knownIds}&vs_currencies=usd&include_24hr_change=true`;
  const response = await fetchWithTimeout(url);

  if (!response.ok) return {};

  const raw = await response.json() as Record<string, { usd?: number; usd_24h_change?: number }>;

  // Re-key by mint address
  const result: Record<string, unknown> = {};
  for (const mint of mints) {
    const geckoId = MINT_TO_GECKO[mint];
    if (geckoId && raw[geckoId]?.usd !== undefined) {
      result[mint] = {
        id: mint,
        mintSymbol: geckoId,
        price: raw[geckoId].usd,
        change24h: raw[geckoId].usd_24h_change,
        source: "coingecko_fallback",
      };
    }
  }
  return result;
}

export async function handlePrice(
  args: { mints: string[] },
  apiKey?: string
): Promise<{ prices: Record<string, unknown>; partial_fallback: boolean; timestamp: string }> {
  const { mints } = args;

  let jupiterData: Record<string, unknown> = {};
  let jupiterFailed = false;

  try {
    jupiterData = await jupiterPrice(mints, apiKey);
  } catch (err) {
    console.error("[jupiter_price] Jupiter API failed, falling back to CoinGecko:", err);
    jupiterFailed = true;
  }

  // Identify mints with no Jupiter data
  const missing = mints.filter((m) => !jupiterData[m]);
  let geckoData: Record<string, unknown> = {};

  if (jupiterFailed || missing.length > 0) {
    const toFetch = jupiterFailed ? mints : missing;
    try {
      geckoData = await coingeckoPrice(toFetch);
    } catch (err) {
      console.error("[jupiter_price] CoinGecko fallback also failed:", err);
    }
  }

  const prices = { ...geckoData, ...jupiterData };
  const partial_fallback = Object.values(prices).some(
    (p) => (p as { source?: string }).source === "coingecko_fallback"
  );

  return {
    prices,
    partial_fallback,
    timestamp: new Date().toISOString(),
  };
}
