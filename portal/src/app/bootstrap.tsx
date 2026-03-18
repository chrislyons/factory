import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CommandPaletteProvider } from "../components/CommandPalette";
import "../styles/app.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
});

export function bootstrapApp(component: React.ReactElement) {
  const rootElement = document.getElementById("root");
  if (!rootElement) {
    throw new Error("Missing #root mount node");
  }

  createRoot(rootElement).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <CommandPaletteProvider>{component}</CommandPaletteProvider>
      </QueryClientProvider>
    </StrictMode>
  );
}
