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
  onRegressionResult?: (implicatedIds: string[]) => void;
}

export function useWebSocket(sessionId: string, options: UseWebSocketOptions = {}) {
  const queryClient = useQueryClient();
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");

  const storageKey = `cf_activity:${sessionId}`;

  const [activityLog, setActivityLog] = useState<ActivityLogEntry[]>(() => {
    try {
      const stored = sessionStorage.getItem(storageKey);
      if (stored) {
        const restored = (JSON.parse(stored) as Array<ActivityLogEntry & { timestamp: string }>)
          .map((e) => ({ ...e, timestamp: new Date(e.timestamp) }));
        // Ensure new IDs never collide with restored entries
        if (restored.length > 0) {
          logIdCounter = Math.max(logIdCounter, ...restored.map((e) => e.id));
        }
        return restored;
      }
    } catch {}
    return [];
  });

  const [costHistory, setCostHistory] = useState<number[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [reconnectCountdown, setReconnectCountdown] = useState(0);
  const [regressionIsRunning, setRegressionIsRunning] = useState(false);
  const [regressionRunNumber, setRegressionRunNumber] = useState(0);

  // Persist activity log to sessionStorage so it survives page refreshes
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(activityLog));
    } catch {}
  }, [storageKey, activityLog]);

  const socketRef = useRef<WebSocket | null>(null);
  // task_id (string) → assigned slot number (1-based)
  const agentSlotMapRef = useRef<Map<string, number>>(new Map());
  // freed slot numbers available for reuse, kept sorted ascending
  const freeSlotsRef = useRef<number[]>([]);
  // next slot to assign when no free slots remain
  const nextSlotRef = useRef(1);
  const seenAgentLogsRef = useRef<Set<string>>(new Set());
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
    let agentIndex: number | undefined;
    if (event.type === "agent_log") {
      // Dedup: skip agent_log events we've already rendered
      const fp = `${event.task_id}:${event.role}:${event.content}`;
      const seen = seenAgentLogsRef.current;
      if (seen.has(fp)) return;
      seen.add(fp);
      // Cap set size to prevent memory leak
      if (seen.size > 1000) seen.clear();

      const slotMap = agentSlotMapRef.current;
      const taskId = event.task_id;
      if (!slotMap.has(taskId)) {
        // Reuse lowest freed slot, or allocate next
        const slot = freeSlotsRef.current.length > 0
          ? freeSlotsRef.current.shift()!
          : nextSlotRef.current++;
        slotMap.set(taskId, slot);
      }
      agentIndex = slotMap.get(taskId);
    }

    const entry: ActivityLogEntry = {
      id: ++logIdCounter,
      timestamp: new Date(),
      type: event.type,
      message: eventToMessage(event),
      ...(event.type === "agent_log" && {
        taskName: event.task_name,
        role: event.role,
        level: event.level,
        agentIndex,
        // event.model may be null (JSON null from Python None) — coerce to undefined
        model: event.model ?? undefined,
      }),
    };
    setActivityLog((prev) => {
      const next = [...prev, entry];
      return next.length > MAX_LOG_ENTRIES ? next.slice(-MAX_LOG_ENTRIES) : next;
    });
  }, []);

  const connect = useCallback(() => {
    if (!activeRef.current) return;

    // Close any existing socket to prevent orphaned connections
    if (socketRef.current) {
      socketRef.current.onclose = null; // prevent reconnect from old socket
      socketRef.current.close();
      socketRef.current = null;
    }

    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    setReconnectCountdown(0);
    setConnectionStatus("connecting");

    const ws = openKanbanSocket();
    socketRef.current = ws;

    ws.onopen = () => {
      if (!activeRef.current || socketRef.current !== ws) return;
      setConnectionStatus("connected");
    };

    ws.onmessage = (evt: MessageEvent<string>) => {
      if (socketRef.current !== ws) return; // ignore stale sockets
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
        // Free the agent slot only on terminal states — NOT on "paused", because
        // late agent_log events may still arrive during the ~2s cancellation window
        // and would be assigned a new slot, creating phantom agents in the log.
        if (event.feature.status === "completed" || event.feature.status === "failed") {
          const taskId = String((event.feature as any).id);
          const slot = agentSlotMapRef.current.get(taskId);
          if (slot !== undefined) {
            agentSlotMapRef.current.delete(taskId);
            freeSlotsRef.current.push(slot);
            freeSlotsRef.current.sort((a, b) => a - b);
          }
        }
        // Clear stale agent_log entries when a task is paused so the activity
        // log no longer shows in-progress work for stopped tasks.
        if (event.feature.status === "paused" && event.feature.name) {
          const pausedName = event.feature.name;
          setActivityLog((prev) =>
            prev.filter(
              (e) => !(e.type === "agent_log" && e.taskName === pausedName),
            ),
          );
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
      if (!activeRef.current || socketRef.current !== ws) return;
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
