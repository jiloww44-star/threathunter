import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Browser-facing code uses RELATIVE /api paths only (never localhost) —
// the dev server proxies them to the backend (Arena preview requirement).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
