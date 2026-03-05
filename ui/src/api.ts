/**
 * API client for claw-forge state service.
 * All paths are relative so Vite's proxy (/api → localhost:8420) applies in dev,
 * and the same paths work in production when served from the same origin.
 */

import type { Command, Feature, ProviderStatus, ProjectSummary } from "./types";

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

/** List all sessions for the current project. */
export async function fetchSessions(): Promise<
  { id: string; project_path: string; status: string; created_at: string }[]
> {
  return fetchJSON("/sessions");
}

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

/** Response shape from GET /pool/status */
export interface PoolStatusResponse {
  providers: ProviderStatus[];
  active: boolean;
  model_aliases?: Record<string, string>;
  usage?: Record<string, unknown>;
  strategy?: string;
}

/** Fetch current provider pool health and model aliases. */
export async function fetchPoolStatus(): Promise<PoolStatusResponse> {
  return fetchJSON<PoolStatusResponse>("/pool/status");
}

// ── Project summary ───────────────────────────────────────────────────────────

/** Fetch high-level project summary (passing / failing / cost). */
export async function fetchProjectSummary(
  sessionId: string,
): Promise<ProjectSummary> {
  return fetchJSON<ProjectSummary>(`/sessions/${sessionId}/summary`);
}

// ── Commands ──────────────────────────────────────────────────────────────────

/** Fetch the full command registry from the backend. */
export async function fetchCommands(): Promise<Command[]> {
  return fetchJSON<Command[]>("/commands/list");
}

/** Execute a command. Returns { execution_id, status }. */
export async function executeCommand(
  command: string,
  args: Record<string, unknown> = {},
  project_dir = ".",
): Promise<{ execution_id: string; status: string }> {
  return fetchJSON<{ execution_id: string; status: string }>("/commands/execute", {
    method: "POST",
    body: JSON.stringify({ command, args, project_dir }),
  });
}

// ── Task status ───────────────────────────────────────────────────────────────

/** PATCH a task's status (e.g. reset failed/blocked → pending for retry). */
export async function patchTaskStatus(
  _sessionId: string,
  taskId: string,
  status: string,
): Promise<void> {
  await fetchJSON<unknown>(`/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// ── Provider toggle ───────────────────────────────────────────────────────────

/** Runtime-toggle a provider (does NOT write to disk). */
export async function toggleProvider(name: string, enabled: boolean): Promise<void> {
  await fetchJSON<unknown>(`/pool/providers/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

/** Persist a provider's enabled state to claw-forge.yaml. */
export async function persistProvider(name: string, enabled: boolean): Promise<void> {
  await fetchJSON<unknown>(`/pool/providers/${encodeURIComponent(name)}/persist`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

// ── WebSocket factory ─────────────────────────────────────────────────────────

/**
 * Open a WebSocket to the global Kanban endpoint.
 *
 * In development Vite proxies ``/ws`` → ``ws://localhost:8420/ws``.
 * In production the same path works when deployed on the same host.
 */
export function openKanbanSocket(): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host; // includes port in dev (5173)
  return new WebSocket(`${protocol}://${host}/ws`);
}
