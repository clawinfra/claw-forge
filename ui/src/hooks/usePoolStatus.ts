/**
 * usePoolStatus — provider pool health polling hook.
 *
 * Polls /api/pool/status every 10 seconds and also updates via WebSocket
 * pool_update events pushed from the backend.
 */

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPoolStatus, openKanbanSocket } from "../api";
import type { ProviderStatus, WsEvent } from "../types";

const POOL_KEY = ["pool", "status"];

/**
 * Subscribe to provider pool health.
 *
 * Returns react-query result: `{ data: ProviderStatus[], isLoading, error }`.
 *
 * Updates arrive via:
 * 1. HTTP poll (every 10s — reasonably frequent for a health panel)
 * 2. WebSocket ``pool_update`` events for instant reflection after provider
 *    changes (circuit opens/closes, rate limit hits, etc.)
 */
export function usePoolStatus() {
  const queryClient = useQueryClient();

  const result = useQuery({
    queryKey: POOL_KEY,
    queryFn: fetchPoolStatus,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });

  const socketRef = useRef<WebSocket | null>(null);

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

        if (event.type === "pool_update") {
          queryClient.setQueryData<ProviderStatus[]>(POOL_KEY, event.providers);
        }
      };

      ws.onclose = () => {
        if (!active) return;
        setTimeout(connect, 5_000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      active = false;
      socketRef.current?.close();
    };
  }, [queryClient]);

  return result;
}
