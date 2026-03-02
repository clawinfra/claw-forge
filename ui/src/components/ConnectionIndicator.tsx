/**
 * ConnectionIndicator — fixed bottom-right dot showing WebSocket status.
 * 🟢 connected  🟡 connecting  🔴 disconnected (with countdown)
 */
import { Wifi, WifiOff } from "lucide-react";
import type { ConnectionStatus } from "../hooks/useWebSocket";

interface ConnectionIndicatorProps {
  status: ConnectionStatus;
  reconnectCountdown: number;
  onReconnect: () => void;
}

export function ConnectionIndicator({
  status,
  reconnectCountdown,
  onReconnect,
}: ConnectionIndicatorProps) {
  const dotColor =
    status === "connected"
      ? "bg-emerald-500"
      : status === "connecting"
        ? "bg-amber-400"
        : "bg-red-500";

  const pulseClass = status === "connected" ? "animate-pulse" : "";

  return (
    <button
      type="button"
      onClick={onReconnect}
      className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-1.5 rounded-full
        bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700
        shadow-lg hover:shadow-xl transition-all duration-200 group"
      title={
        status === "connected"
          ? "WebSocket connected"
          : status === "connecting"
            ? "Connecting..."
            : "Disconnected — click to reconnect"
      }
    >
      <span className={`h-2.5 w-2.5 rounded-full ${dotColor} ${pulseClass}`} />
      {status === "connected" && (
        <Wifi
          size={12}
          className="text-emerald-600 dark:text-emerald-400 opacity-0 group-hover:opacity-100 transition-opacity"
        />
      )}
      {status === "connecting" && (
        <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">
          Connecting…
        </span>
      )}
      {status === "disconnected" && (
        <>
          <WifiOff size={12} className="text-red-500" />
          {reconnectCountdown > 0 && (
            <span className="text-[10px] text-red-600 dark:text-red-400 font-medium">
              {reconnectCountdown}s
            </span>
          )}
        </>
      )}
    </button>
  );
}
