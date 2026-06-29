import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const basePath =
  process.env.VITE_BASE_PATH ??
  (process.env.NODE_ENV === "production" ? "/ledgerlink/" : "/");

export default defineConfig({
  base: basePath,
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
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
