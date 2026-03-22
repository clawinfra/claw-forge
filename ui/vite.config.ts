import { defineConfig, createLogger } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
// VITE_API_PORT is injected by `claw-forge ui --dev` (defaults to 8420).
const statePort = process.env.VITE_API_PORT ?? "8420";

// Custom logger that silences WS proxy disconnect noise when the state service
// restarts (uvicorn --reload on file save).  Checked via opts.error so ANSI
// codes in the formatted message string never interfere with the match.
// useWebSocket.ts handles reconnection automatically — these are harmless.
const logger = createLogger();
const _origError = logger.error.bind(logger);
logger.error = (msg, opts) => {
  const err = opts?.error as (NodeJS.ErrnoException & { code?: string }) | undefined;
  if (
    err?.message?.includes("ended by the other party") ||
    err?.code === "ECONNRESET" ||
    err?.code === "ECONNREFUSED" ||
    err?.code === "EPIPE"
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
