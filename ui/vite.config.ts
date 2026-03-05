import { defineConfig, createLogger } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
// VITE_API_PORT is injected by `claw-forge ui --dev` (defaults to 8420).
const statePort = process.env.VITE_API_PORT ?? "8420";

// Custom logger that silences the WS proxy disconnect noise that occurs when
// the state service restarts (uvicorn --reload on file save).  The frontend
// useWebSocket hook already handles reconnection automatically; these messages
// are harmless but fill the terminal on every hot-reload.
const logger = createLogger();
const _origError = logger.error.bind(logger);
logger.error = (msg, opts) => {
  if (
    msg.includes("[vite] ws proxy error") &&
    (msg.includes("ended by the other party") ||
      msg.includes("ECONNRESET") ||
      msg.includes("ECONNREFUSED"))
  ) {
    return; // suppress routine state-service disconnect noise
  }
  _origError(msg, opts);
};

export default defineConfig({
  customLogger: logger,
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
      // WebSocket upgrade
      "/ws": {
        target: `ws://localhost:${statePort}`,
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
