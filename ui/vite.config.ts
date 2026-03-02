import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // REST API calls proxied to the claw-forge state service
      "/api": {
        target: "http://localhost:8888",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      // WebSocket upgrade — Vite doesn't auto-proxy WS via the same rule
      "/ws": {
        target: "ws://localhost:8888",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
