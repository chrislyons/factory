export interface TxnBucket {
  buys: number;
  sells: number;
}

export interface PairData {
  chainId: string;
  dexId: string;
  pairAddress: string;
  baseToken: { address: string; name: string; symbol: string };
  quoteToken: { address: string; name: string; symbol: string };
  priceUsd?: string;
  priceNative?: string;
  txns?: {
    m5?: TxnBucket;
    h1?: TxnBucket;
    h6?: TxnBucket;
    h24?: TxnBucket;
  };
  volume?: { h24?: number; h6?: number; h1?: number; m5?: number };
  priceChange?: { m5?: number; h1?: number; h6?: number; h24?: number };
  liquidity?: { usd?: number; base?: number; quote?: number };
  fdv?: number;
  marketCap?: number;
  pairCreatedAt?: number;
  boosts?: { active?: number };
  [key: string]: unknown;
}
