/**
 * useFeatures — react-query hook for feature data.
 *
 * Real-time updates are handled by the shared useWebSocket hook.
 * This hook only does initial load + periodic fallback polling.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchFeatures } from "../api";

export const FEATURES_KEY = (sessionId: string) => ["features", sessionId];

/**
 * Subscribe to the feature list for the given session.
 *
 * Returns standard react-query result shape: `{ data, isLoading, error }`.
 * Real-time updates are handled by the shared useWebSocket hook.
 */
export function useFeatures(sessionId: string) {
  return useQuery({
    queryKey: FEATURES_KEY(sessionId),
    queryFn: () => fetchFeatures(sessionId),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}
