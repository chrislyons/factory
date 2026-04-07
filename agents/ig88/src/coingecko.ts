// CoinGecko API Client (Free tier)

import type { MarketData, Candidate } from './types.js';

const BASE_URL = 'https://api.coingecko.com/api/v3';

// Rate limit: 10-30 calls/minute on free tier
async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`CoinGecko API error: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

interface PriceResponse {
  [id: string]: {
    usd: number;
    usd_24h_change: number;
    usd_market_cap?: number;
    usd_24h_vol?: number;
  };
}

export async function getMarketData(): Promise<MarketData> {
  const data = await fetchJson<PriceResponse>(
    `${BASE_URL}/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true`
  );

  return {
    btc: {
      price: data.bitcoin?.usd ?? 0,
      change24h: data.bitcoin?.usd_24h_change ?? 0,
    },
    eth: {
      price: data.ethereum?.usd ?? 0,
      change24h: data.ethereum?.usd_24h_change ?? 0,
    },
    sol: {
      price: data.solana?.usd ?? 0,
      change24h: data.solana?.usd_24h_change ?? 0,
    },
    timestamp: new Date().toISOString(),
  };
}

interface TrendingCoin {
  item: {
    id: string;
    symbol: string;
    name: string;
    market_cap_rank: number | null;
    data?: {
      price?: number;
      price_change_percentage_24h?: {
        usd?: number;
      };
      total_volume?: string;
    };
  };
}

interface TrendingResponse {
  coins: TrendingCoin[];
}

export async function getTrendingTokens(): Promise<Candidate[]> {
  const data = await fetchJson<TrendingResponse>(`${BASE_URL}/search/trending`);

  return data.coins.slice(0, 15).map((coin) => {
    const item = coin.item;
    const change24h = item.data?.price_change_percentage_24h?.usd ?? 0;
    const price = item.data?.price ?? 0;
    const volumeStr = item.data?.total_volume ?? '0';
    const volume = parseFloat(volumeStr.replace(/[^0-9.]/g, '')) || null;

    return {
      symbol: item.symbol.toUpperCase(),
      name: item.name,
      price,
      change24h,
      rank: item.market_cap_rank,
      volume24h: volume,
      score: 0, // Calculated by scanner
      reasons: [],
    };
  });
}

// Get specific token data
export async function getTokenInfo(id: string): Promise<{
  price: number;
  change24h: number;
  volume24h: number;
  rank: number | null;
} | null> {
  try {
    const data = await fetchJson<PriceResponse>(
      `${BASE_URL}/simple/price?ids=${id}&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true`
    );

    const token = data[id];
    if (!token) return null;

    return {
      price: token.usd,
      change24h: token.usd_24h_change ?? 0,
      volume24h: token.usd_24h_vol ?? 0,
      rank: null, // Would need separate call
    };
  } catch {
    return null;
  }
}
