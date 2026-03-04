import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
// VITE_API_PORT is injected by `claw-forge ui --dev` (defaults to 8420).
const statePort = process.env.VITE_API_PORT ?? "8420";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // REST API calls proxied to the claw-forge state service
      "/api": {
        target: `http://localhost:${statePort}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      // WebSocket upgrade — Vite doesn't auto-proxy WS via the same rule
      "/ws": {
        target: `ws://localhost:${statePort}`,
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
