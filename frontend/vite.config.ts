/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Same-origin in the browser; Vite forwards /api to FastAPI (no CORS needed).
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
  test: { environment: "jsdom" },
});
