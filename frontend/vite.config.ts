import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During local dev the SPA runs on :5173 and proxies API + health to the
// backend on :8000. In production nginx serves the built files and proxies
// /api and /health to the backend container (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
