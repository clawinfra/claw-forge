/**
 * useWebSocket — single shared WebSocket connection with event dispatching.
 * Manages connection state, activity log, cost history, and toast notifications.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { openKanbanSocket } from "../api";
import type {
  ActivityLogEntry,
  Feature,
  ProviderStatus,

  Toast,
  WsEvent,
} from "../types";

export type ConnectionStatus = "connected" | "connecting" | "disconnected";

const MAX_LOG_ENTRIES = 200;
const MAX_COST_HISTORY = 20;
const TOAST_DURATION = 3000;

let logIdCounter = 0;
let toastIdCounter = 0;

function eventToMessage(event: WsEvent): string {
  switch (event.type) {
    case "feature_update":
      return `Feature "${event.feature.name}" → ${event.feature.status}`;
    case "agent_started":
      return `Agent started for feature ${event.feature_id}`;
    case "agent_completed":
      return `Agent completed for feature ${event.feature_id} (${event.passed ? "passed" : "failed"})`;
    case "cost_update":
      return `Cost update: $${event.total_cost.toFixed(3)} total (+$${event.session_cost.toFixed(3)})`;
    case "pool_update":
      return `Pool update: ${event.providers.length} providers`;
    case "regression_started":
      return `🔄 Regression run #${event.run_number} started`;
    case "regression_result":
      return event.passed
        ? `✅ Regression #${event.run_number}: ${event.total} passing (${event.duration_ms}ms)`
        : `❌ Regression #${event.run_number}: ${event.failed} failed — ${event.failed_tests.join(", ")}`;
  }
}

export function useWebSocket(sessionId: string) {
  const queryClient = useQueryClient();
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [activityLog, setActivityLog] = useState<ActivityLogEntry[]>([]);
  const [costHistory, setCostHistory] = useState<number[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [reconnectCountdown, setReconnectCountdown] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );
  const activeRef = useRef(true);

  const addToast = useCallback(
    (message: string, type: Toast["type"]) => {
      const id = ++toastIdCounter;
      setToasts((prev) => [...prev, { id, message, type }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, TOAST_DURATION);
    },
    [],
  );

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addLogEntry = useCallback((event: WsEvent) => {
    const entry: ActivityLogEntry = {
      id: ++logIdCounter,
      timestamp: new Date(),
      type: event.type,
      message: eventToMessage(event),
    };
    setActivityLog((prev) => {
      const next = [...prev, entry];
      return next.length > MAX_LOG_ENTRIES ? next.slice(-MAX_LOG_ENTRIES) : next;
    });
  }, []);

  const connect = useCallback(() => {
    if (!activeRef.current) return;

    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    setReconnectCountdown(0);
    setConnectionStatus("connecting");

    const ws = openKanbanSocket();
    socketRef.current = ws;

    ws.onopen = () => {
      if (!activeRef.current) return;
      setConnectionStatus("connected");
    };

    ws.onmessage = (evt: MessageEvent<string>) => {
      let event: WsEvent;
      try {
        event = JSON.parse(evt.data) as WsEvent;
      } catch {
        return;
      }

      // Log all events
      addLogEntry(event);

      // Route events
      if (event.type === "feature_update") {
        queryClient.setQueryData<Feature[]>(
          ["features", sessionId],
          (old = []) => {
            const idx = old.findIndex((f) => f.id === event.feature.id);
            if (idx >= 0) {
              const updated = [...old];
              updated[idx] = event.feature;
              return updated;
            }
            return [...old, event.feature];
          },
        );

        if (event.feature.status === "failed") {
          addToast(`❌ Feature failed: ${event.feature.name}`, "error");
        }
      } else if (event.type === "agent_completed") {
        void queryClient.invalidateQueries({
          queryKey: ["features", sessionId],
        });
        if (event.passed) {
          addToast(`✅ Agent completed: feature ${event.feature_id}`, "success");
        }
      } else if (event.type === "agent_started") {
        void queryClient.invalidateQueries({
          queryKey: ["features", sessionId],
        });
      } else if (event.type === "pool_update") {
        queryClient.setQueryData<ProviderStatus[]>(
          ["pool", "status"],
          event.providers,
        );
      } else if (event.type === "cost_update") {
        setCostHistory((prev) => {
          const next = [...prev, event.total_cost];
          return next.length > MAX_COST_HISTORY
            ? next.slice(-MAX_COST_HISTORY)
            : next;
        });
      }
    };

    ws.onclose = () => {
      if (!activeRef.current) return;
      setConnectionStatus("disconnected");
      const delay = 5;
      setReconnectCountdown(delay);
      countdownIntervalRef.current = setInterval(() => {
        setReconnectCountdown((prev) => {
          if (prev <= 1) {
            if (countdownIntervalRef.current) {
              clearInterval(countdownIntervalRef.current);
              countdownIntervalRef.current = null;
            }
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      reconnectTimerRef.current = setTimeout(connect, delay * 1000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [sessionId, queryClient, addLogEntry, addToast]);

  const forceReconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    socketRef.current?.close();
    connect();
  }, [connect]);

  useEffect(() => {
    activeRef.current = true;
    connect();

    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (countdownIntervalRef.current)
        clearInterval(countdownIntervalRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  return {
    connectionStatus,
    activityLog,
    costHistory,
    toasts,
    reconnectCountdown,
    forceReconnect,
    addToast,
    removeToast,
  };
}
