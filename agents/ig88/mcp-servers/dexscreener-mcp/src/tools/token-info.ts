// dex_token_info — GET https://api.dexscreener.com/tokens/v1/solana/{addresses}
// Returns full pair data for the most liquid pair of each token.
// Adds flow_ratios (buys/(buys+sells) per time bucket) as a convenience field.
// Raw txns counts preserved verbatim — no information loss.

import { fetchWithTimeout } from "../utils/fetch.js";
import { DEX_BASE_URL } from "../constants.js";
import type { PairData, TxnBucket } from "../types.js";

export const tokenInfoTool = {
  name: "dex_token_info",
  description:
    "Get real-time price, volume, liquidity, and order flow data for Solana tokens from Dexscreener. " +
    "Returns the most liquid pair for each token. Includes raw txn counts (buys/sells) per time bucket " +
    "(m5/h1/h6/h24) plus computed flow_ratios (buy ratio = buys/(buys+sells)). " +
    "Primary price source for small-cap and newly-launched tokens not indexed by Jupiter. " +
    "Up to 30 mint addresses per request.",
  inputSchema: {
    type: "object",
    properties: {
      tokenAddresses: {
        type: "array",
        items: { type: "string" },
        description: "Solana mint addresses (up to 30)",
        maxItems: 30,
      },
    },
    required: ["tokenAddresses"],
  },
} as const;

function computeFlowRatios(txns: PairData["txns"]): Record<string, number | null> {
  const ratio = (bucket?: TxnBucket): number | null => {
    if (!bucket) return null;
    const total = bucket.buys + bucket.sells;
    return total === 0 ? null : bucket.buys / total;
  };

  return {
    m5_buy_ratio: ratio(txns?.m5),
    h1_buy_ratio: ratio(txns?.h1),
    h6_buy_ratio: ratio(txns?.h6),
    h24_buy_ratio: ratio(txns?.h24),
  };
}

function mostLiquidPair(pairs: PairData[]): PairData {
  return pairs.reduce((best, pair) => {
    const bestLiq = best.liquidity?.usd ?? 0;
    const pairLiq = pair.liquidity?.usd ?? 0;
    return pairLiq > bestLiq ? pair : best;
  });
}

export async function handleTokenInfo(
  args: { tokenAddresses: string[] }
): Promise<{ tokens: unknown[]; timestamp: string }> {
  const { tokenAddresses } = args;
  const addresses = tokenAddresses.slice(0, 30).join(",");
  const url = `${DEX_BASE_URL}/tokens/v1/solana/${addresses}`;

  const response = await fetchWithTimeout(url);
  if (!response.ok) {
    throw new Error(`Dexscreener tokens API ${response.status}: ${await response.text()}`);
  }

  const data = await response.json() as PairData[];
  const pairsArray = Array.isArray(data) ? data : [];

  // Group pairs by base token address, pick most liquid
  const byToken = new Map<string, PairData[]>();
  for (const pair of pairsArray) {
    const addr = pair.baseToken?.address;
    if (!addr) continue;
    if (!byToken.has(addr)) byToken.set(addr, []);
    byToken.get(addr)!.push(pair);
  }

  const tokens = [];
  for (const [, pairs] of byToken) {
    const best = mostLiquidPair(pairs);
    const flow_ratios = computeFlowRatios(best.txns);
    tokens.push({ ...best, flow_ratios });
  }

  return { tokens, timestamp: new Date().toISOString() };
}
