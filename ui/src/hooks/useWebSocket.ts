/**
 * useWebSocket — single shared WebSocket connection with event dispatching.
 * Manages connection state, activity log, cost history, and toast notifications.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { openKanbanSocket } from "../api";
import type { PoolStatusResponse } from "../api";
import type {
  ActivityLogEntry,
  Feature,

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
      return `Regression run #${event.run_number} started`;
    case "regression_result":
      return event.passed
        ? `Regression #${event.run_number}: ${event.total} passing (${event.duration_ms}ms)`
        : `Regression #${event.run_number}: ${event.failed} failed — ${event.failed_tests.join(", ")}`;
    case "agent_log":
      return event.content;
  }
}

export interface UseWebSocketOptions {
  onCommandEvent?: (event: Record<string, unknown>) => void;
  onRegressionResult?: (implicatedIds: number[]) => void;
}

export function useWebSocket(sessionId: string, options: UseWebSocketOptions = {}) {
  const queryClient = useQueryClient();
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [activityLog, setActivityLog] = useState<ActivityLogEntry[]>([]);
  const [costHistory, setCostHistory] = useState<number[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [reconnectCountdown, setReconnectCountdown] = useState(0);
  const [regressionIsRunning, setRegressionIsRunning] = useState(false);
  const [regressionRunNumber, setRegressionRunNumber] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const onCommandEventRef = useRef(options.onCommandEvent);
  onCommandEventRef.current = options.onCommandEvent;
  const onRegressionResultRef = useRef(options.onRegressionResult);
  onRegressionResultRef.current = options.onRegressionResult;
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
      ...(event.type === "agent_log" && {
        taskName: event.task_name,
        role: event.role,
      }),
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let raw: Record<string, any>;
      try {
        raw = JSON.parse(evt.data) as Record<string, unknown>;
      } catch {
        return;
      }

      // Handle command execution events (not part of WsEvent union)
      if (raw.type === "command_output" || raw.type === "command_done") {
        onCommandEventRef.current?.(raw);
        return;
      }

      const event = raw as unknown as WsEvent;

      // Log all events
      addLogEntry(event);

      // Route events
      if (event.type === "feature_update") {
        queryClient.setQueryData<Feature[]>(
          ["features", sessionId],
          (old = []) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const featureId = (event.feature as any).id ?? null;
            // Partial payloads (e.g. task.updated with only {session_id, task_id, status})
            // have no "id" field — skip them; the optimistic update already handled it.
            if (featureId == null) return old;
            const idx = old.findIndex((f) => f.id === featureId);
            if (idx >= 0) {
              // Merge so that partial events don't wipe fields missing from the payload.
              const updated = [...old];
              updated[idx] = { ...old[idx], ...event.feature };
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
        queryClient.setQueryData<PoolStatusResponse>(
          ["pool", "status"],
          (old) => ({
            ...old,
            providers: event.providers,
            active: true,
          } as PoolStatusResponse),
        );
      } else if (event.type === "cost_update") {
        setCostHistory((prev) => {
          const next = [...prev, event.total_cost];
          return next.length > MAX_COST_HISTORY
            ? next.slice(-MAX_COST_HISTORY)
            : next;
        });
      } else if (event.type === "regression_started") {
        setRegressionIsRunning(true);
        setRegressionRunNumber(event.run_number);
      } else if (event.type === "regression_result") {
        setRegressionIsRunning(false);
        void queryClient.invalidateQueries({ queryKey: ["regression", "status"] });
        onRegressionResultRef.current?.(event.implicated_feature_ids);
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
    regressionIsRunning,
    regressionRunNumber,
  };
}
