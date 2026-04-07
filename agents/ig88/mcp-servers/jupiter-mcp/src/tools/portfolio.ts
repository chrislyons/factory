// jupiter_portfolio — GET https://api.jup.ag/portfolio/
//
// Tracks positions across all Jupiter platforms: swaps, perps, lend, etc.
// This is the feedback loop — after a trade executes, portfolio tracks the outcome
// so signal accuracy can be measured (did the GARCH call match the actual PnL?).

import { fetchWithTimeout } from "../utils/fetch.js";

const JUPITER_PORTFOLIO_URL = "https://api.jup.ag/portfolio/v1/positions";

export const portfolioTool = {
  name: "jupiter_portfolio",
  description:
    "Get portfolio positions for a wallet address across all Jupiter platforms " +
    "(spot, perps, lend, locked tokens). Use this to track trade outcomes and close the " +
    "signal → execute → feedback loop. Required for measuring signal accuracy.",
  inputSchema: {
    type: "object",
    properties: {
      walletAddress: {
        type: "string",
        description: "Solana wallet public key (base58 encoded)",
      },
    },
    required: ["walletAddress"],
  },
} as const;

interface PortfolioResponse {
  [key: string]: unknown;
}

interface PortfolioResult {
  wallet: string;
  portfolio: PortfolioResponse;
  timestamp: string;
}

export async function handlePortfolio(
  args: { walletAddress: string },
  apiKey?: string
): Promise<PortfolioResult> {
  const headers: Record<string, string> = {};
  if (apiKey) headers["x-api-key"] = apiKey;

  const url = `${JUPITER_PORTFOLIO_URL}/${args.walletAddress}`;
  const response = await fetchWithTimeout(url, { headers }, 10000);

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Jupiter portfolio API ${response.status}: ${body}`);
  }

  const portfolio = await response.json() as PortfolioResponse;

  return {
    wallet: args.walletAddress,
    portfolio,
    timestamp: new Date().toISOString(),
  };
}
