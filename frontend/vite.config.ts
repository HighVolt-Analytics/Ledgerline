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
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
      },
      "/connect-mailbox": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
