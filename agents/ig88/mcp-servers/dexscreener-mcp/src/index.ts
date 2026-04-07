import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { tokenInfoTool, handleTokenInfo } from "./tools/token-info.js";
import { tokenPairsTool, handleTokenPairs } from "./tools/token-pairs.js";
import { searchTool, handleSearch } from "./tools/search.js";
import { trendingTool, handleTrending } from "./tools/trending.js";

// Dexscreener is fully public — no API key required.
// Rate limits: 300 req/min for DEX/pairs endpoints, 60 req/min for boosts.

const server = new Server(
  { name: "dexscreener-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [tokenInfoTool, tokenPairsTool, searchTool, trendingTool],
  };
});

const TOOLS: Record<string, (args: unknown) => Promise<unknown>> = {
  dex_token_info: (args) => handleTokenInfo(args as Parameters<typeof handleTokenInfo>[0]),
  dex_token_pairs: (args) => handleTokenPairs(args as Parameters<typeof handleTokenPairs>[0]),
  dex_search: (args) => handleSearch(args as Parameters<typeof handleSearch>[0]),
  dex_trending: (args) => handleTrending(args as Parameters<typeof handleTrending>[0]),
};

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    const handler = TOOLS[name];
    if (!handler) {
      return {
        content: [{ type: "text", text: `Unknown tool: ${name}` }],
        isError: true,
      };
    }

    const result = await handler(args);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(
    `[dexscreener-mcp] v1.0.0 running — tools: dex_token_info, dex_token_pairs, dex_search, dex_trending`
  );
}

main().catch(console.error);
