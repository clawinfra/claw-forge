/**
 * useFeatures — react-query hook for feature data.
 *
 * Real-time updates are handled by the shared useWebSocket hook.
 * This hook only does initial load + periodic fallback polling.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchFeatures } from "../api";
import type { Feature } from "../types";

export const FEATURES_KEY = (sessionId: string) => ["features", sessionId];

const TERMINAL = new Set(["completed", "failed"]);

/**
 * Subscribe to the feature list for the given session.
 *
 * Returns standard react-query result shape: `{ data, isLoading, error }`.
 * Real-time updates are handled by the shared useWebSocket hook.
 * Polling stops automatically once all features reach a terminal state.
 */
export function useFeatures(sessionId: string) {
  return useQuery({
    queryKey: FEATURES_KEY(sessionId),
    queryFn: () => fetchFeatures(sessionId),
    staleTime: 30_000,
    refetchInterval: (query) => {
      const data = query.state.data as Feature[] | undefined;
      if (data && data.length > 0 && data.every((f) => TERMINAL.has(f.status))) {
        return false;
      }
      return 30_000;
    },
  });
}
