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
      "/api": { target: "http://localhost:8001", changeOrigin: true },
      "/health": { target: "http://localhost:8001", changeOrigin: true },
    },
  },
});
