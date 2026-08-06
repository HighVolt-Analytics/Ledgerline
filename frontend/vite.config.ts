import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const basePath = process.env.VITE_BASE_PATH ?? "/";

export default defineConfig({
  base: basePath,
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (id.includes("recharts") || id.includes("d3-")) return "charts";
          if (id.includes("simple-icons")) return "icons-brands";
          if (id.includes("lucide-react")) return "icons";
          if (
            id.includes("react-dom") ||
            id.includes("react-router") ||
            id.includes("/react/") ||
            id.includes("\\react\\")
          ) {
            return "react-vendor";
          }
          if (id.includes("@tanstack")) return "query";
        },
      },
    },
  },
  server: {
    port: 5173,
    allowedHosts: [".ngrok-free.dev", ".ngrok.io"],
    proxy: {
      // Timeouts prevent a hung API from saturating Vite and stalling lazy page chunks
      // (e.g. DashboardPage.tsx stuck pending in the browser Network tab).
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
        // Approve / ingest paths can exceed 30s when LLM posting runs; empty
        // proxy responses show up as net::ERR_EMPTY_RESPONSE in the browser.
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
      "/health": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
        timeout: 10_000,
        proxyTimeout: 10_000,
      },
      "/connect-mailbox": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
        timeout: 30_000,
        proxyTimeout: 30_000,
      },
    },
  },
});
