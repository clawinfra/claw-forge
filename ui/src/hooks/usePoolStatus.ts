/**
 * usePoolStatus — provider pool health polling hook.
 *
 * Polls /api/pool/status every 10 seconds.
 * Real-time updates are handled by the shared useWebSocket hook.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchPoolStatus } from "../api";
import type { PoolStatusResponse } from "../api";

export const POOL_KEY = ["pool", "status"];

/**
 * Subscribe to provider pool health.
 *
 * Returns react-query result with `{ data: PoolStatusResponse, isLoading, error }`.
 * Real-time updates arrive via the shared useWebSocket hook.
 */
export function usePoolStatus(paused = false) {
  return useQuery<PoolStatusResponse>({
    queryKey: POOL_KEY,
    queryFn: fetchPoolStatus,
    staleTime: 10_000,
    refetchInterval: paused ? false : 10_000,
  });
}
