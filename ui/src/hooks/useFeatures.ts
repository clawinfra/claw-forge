/**
 * useFeatures — react-query + WebSocket hook for real-time feature updates.
 *
 * Combines:
 * 1. Initial data load via react-query (polls every 30s as fallback)
 * 2. Real-time updates pushed over the global WebSocket (/ws)
 */

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchFeatures, openKanbanSocket } from "../api";
import type { Feature, WsEvent } from "../types";

const FEATURES_KEY = (sessionId: string) => ["features", sessionId];

/**
 * Subscribe to the feature list for the given session.
 *
 * Returns standard react-query result shape: `{ data, isLoading, error }`.
 * The feature list is kept up-to-date via WebSocket pushes without waiting
 * for the 30-second polling interval.
 */
export function useFeatures(sessionId: string) {
  const queryClient = useQueryClient();

  const result = useQuery({
    queryKey: FEATURES_KEY(sessionId),
    queryFn: () => fetchFeatures(sessionId),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;

    function connect() {
      if (!active) return;
      const ws = openKanbanSocket();
      socketRef.current = ws;

      ws.onmessage = (evt: MessageEvent<string>) => {
        let event: WsEvent;
        try {
          event = JSON.parse(evt.data) as WsEvent;
        } catch {
          return;
        }

        if (event.type === "feature_update") {
          // Merge the updated feature into the cached list
          queryClient.setQueryData<Feature[]>(
            FEATURES_KEY(sessionId),
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
        } else if (
          event.type === "agent_started" ||
          event.type === "agent_completed"
        ) {
          // Partial update — refresh from server for accuracy
          void queryClient.invalidateQueries({
            queryKey: FEATURES_KEY(sessionId),
          });
        }
      };

      ws.onclose = () => {
        if (!active) return;
        // Exponential back-off reconnect (max 10s)
        reconnectTimer.current = setTimeout(connect, Math.min(1000 * 2, 10_000));
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      active = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      socketRef.current?.close();
    };
  }, [sessionId, queryClient]);

  return result;
}
