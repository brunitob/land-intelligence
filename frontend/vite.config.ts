import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo la API corre en :8000; el frontend la llama siempre como /api/... (en producción lo resuelve Caddy).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_URL || "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
