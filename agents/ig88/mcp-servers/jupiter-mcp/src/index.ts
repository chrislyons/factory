import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { priceTool, handlePrice } from "./tools/price.js";
import { quoteTool, handleQuote } from "./tools/quote.js";
import { portfolioTool, handlePortfolio } from "./tools/portfolio.js";
import { swapTool, handleSwap } from "./tools/swap.js";

// Read API key from environment — never hardcode
const JUPITER_API_KEY = process.env.JUPITER_API_KEY;

if (!JUPITER_API_KEY) {
  console.error(
    "[jupiter-mcp] WARNING: JUPITER_API_KEY not set. " +
      "Price and quote calls will use the public rate limit tier. " +
      "Execution requires a valid API key from portal.jup.ag"
  );
}

const server = new Server(
  { name: "jupiter-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [priceTool, quoteTool, portfolioTool, swapTool],
  };
});

const TOOLS: Record<string, (args: unknown) => Promise<unknown>> = {
  jupiter_price: (args) => handlePrice(args as Parameters<typeof handlePrice>[0], JUPITER_API_KEY),
  jupiter_quote: (args) => handleQuote(args as Parameters<typeof handleQuote>[0], JUPITER_API_KEY),
  jupiter_portfolio: (args) => handlePortfolio(args as Parameters<typeof handlePortfolio>[0], JUPITER_API_KEY),
  jupiter_swap: (args) => handleSwap(args as Parameters<typeof handleSwap>[0], JUPITER_API_KEY),
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
    `[jupiter-mcp] v1.0.0 running — tools: jupiter_price, jupiter_quote, jupiter_portfolio, jupiter_swap`
  );
}

main().catch(console.error);
