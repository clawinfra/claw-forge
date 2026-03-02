/**
 * API client for claw-forge state service.
 * All paths are relative so Vite's proxy (/api → localhost:8888) applies in dev,
 * and the same paths work in production when served from the same origin.
 */

import type { Feature, ProviderStatus, ProjectSummary } from "./types";

const BASE = "/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Sessions / Features ───────────────────────────────────────────────────────

/** List all tasks for the given session, mapped as features. */
export async function fetchFeatures(sessionId: string): Promise<Feature[]> {
  return fetchJSON<Feature[]>(`/sessions/${sessionId}/tasks`);
}

/** Fetch a summary for the given session. */
export async function fetchSession(
  sessionId: string,
): Promise<Record<string, unknown>> {
  return fetchJSON<Record<string, unknown>>(`/sessions/${sessionId}`);
}

// ── Pool status ───────────────────────────────────────────────────────────────

/** Fetch current provider pool health. */
export async function fetchPoolStatus(): Promise<ProviderStatus[]> {
  return fetchJSON<ProviderStatus[]>("/pool/status");
}

// ── Project summary ───────────────────────────────────────────────────────────

/** Fetch high-level project summary (passing / failing / cost). */
export async function fetchProjectSummary(
  sessionId: string,
): Promise<ProjectSummary> {
  return fetchJSON<ProjectSummary>(`/sessions/${sessionId}/summary`);
}

// ── WebSocket factory ─────────────────────────────────────────────────────────

/**
 * Open a WebSocket to the global Kanban endpoint.
 *
 * In development Vite proxies ``/ws`` → ``ws://localhost:8888/ws``.
 * In production the same path works when deployed on the same host.
 */
export function openKanbanSocket(): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host; // includes port in dev (5173)
  return new WebSocket(`${protocol}://${host}/ws`);
}
