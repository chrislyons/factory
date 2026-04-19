/**
 * Global fetch interceptor for demo mode.
 *
 * Intercepts raw fetch() calls that bypass fetchJson (e.g. RepoExplorer's
 * direct /index.json fetch) and returns mock data.
 */

import { DEMO_INDEX } from "./demo-data";

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

if (DEMO_MODE && typeof window !== "undefined") {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

    // Only intercept GET requests
    if (init && init.method && init.method !== "GET") {
      return originalFetch(input, init);
    }

    // /index.json → factory-only demo index
    if (url === "/index.json" || url.endsWith("/index.json")) {
      return new Response(JSON.stringify(DEMO_INDEX), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    return originalFetch(input, init);
  };
}
