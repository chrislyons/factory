import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = dirname(fileURLToPath(new URL(import.meta.url)));

export default defineConfig({
  plugins: [react()],
  publicDir: "public",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        portal: resolve(root, "portal.html"),
        jobs: resolve(root, "pages/jobs.html"),
        dashboard: resolve(root, "pages/dashboard-v4.html"),
        topology: resolve(root, "pages/topology.html"),
        analytics: resolve(root, "pages/analytics.html"),
        loops: resolve(root, "pages/loops.html"),
        docs: resolve(root, "pages/docs.html"),
        agentBoot: resolve(root, "pages/agents/boot.html"),
        agentIg88: resolve(root, "pages/agents/ig88.html"),
        agentKelk: resolve(root, "pages/agents/kelk.html"),
        agentNan: resolve(root, "pages/agents/nan.html")
      }
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true
  }
});
