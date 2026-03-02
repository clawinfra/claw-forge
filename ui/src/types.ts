/**
 * TypeScript types for claw-forge Kanban UI.
 * These mirror the backend SQLAlchemy models and WebSocket event payloads.
 */

// ── Feature / Task status ─────────────────────────────────────────────────────

export type FeatureStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "blocked";

/** Maps backend Task to a Kanban-friendly Feature representation. */
export interface Feature {
  id: string;
  name: string;
  category: string;
  status: FeatureStatus;
  priority: number;
  /** List of task IDs this feature depends on */
  depends_on: string[];
  /** Agent session ID when in progress */
  session_id?: string;
  /** 0–100 progress percentage */
  progress?: number;
  /** Cost incurred for this feature in USD */
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  error_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

// ── Provider / Pool ───────────────────────────────────────────────────────────

export type ProviderHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ProviderStatus {
  name: string;
  type: string;
  health: ProviderHealth;
  /** Requests per minute (recent 60s window) */
  rpm: number;
  max_rpm: number;
  /** Circuit breaker state: closed | open | half_open */
  circuit_state: "closed" | "open" | "half_open";
  /** Accumulated cost in USD */
  total_cost_usd: number;
  /** Average latency in ms */
  avg_latency_ms: number;
  enabled: boolean;
}

// ── Project summary ───────────────────────────────────────────────────────────

export interface ProjectSummary {
  name: string;
  total_features: number;
  passing: number;
  failing: number;
  pending: number;
  in_progress: number;
  blocked: number;
  active_agents: number;
  total_cost_usd: number;
}

// ── WebSocket event payloads ──────────────────────────────────────────────────

export interface FeatureUpdateEvent {
  type: "feature_update";
  feature: Feature;
}

export interface PoolUpdateEvent {
  type: "pool_update";
  providers: ProviderStatus[];
}

export interface AgentStartedEvent {
  type: "agent_started";
  session_id: string;
  feature_id: string | number;
}

export interface AgentCompletedEvent {
  type: "agent_completed";
  session_id: string;
  feature_id: string | number;
  passed: boolean;
}

export interface CostUpdateEvent {
  type: "cost_update";
  total_cost: number;
  session_cost: number;
}

export type WsEvent =
  | FeatureUpdateEvent
  | PoolUpdateEvent
  | AgentStartedEvent
  | AgentCompletedEvent
  | CostUpdateEvent;

// ── Kanban columns ────────────────────────────────────────────────────────────

export interface KanbanColumn {
  id: FeatureStatus | "in_progress";
  label: string;
  statuses: FeatureStatus[];
  colorClass: string;
  headerClass: string;
}

export const KANBAN_COLUMNS: KanbanColumn[] = [
  {
    id: "pending",
    label: "Pending",
    statuses: ["pending", "queued"],
    colorClass: "bg-slate-50 border-slate-200",
    headerClass: "bg-slate-100 text-slate-700",
  },
  {
    id: "in_progress",
    label: "In Progress",
    statuses: ["running"],
    colorClass: "bg-blue-50 border-blue-200",
    headerClass: "bg-blue-100 text-blue-700",
  },
  {
    id: "completed",
    label: "Passing",
    statuses: ["completed"],
    colorClass: "bg-emerald-50 border-emerald-200",
    headerClass: "bg-emerald-100 text-emerald-700",
  },
  {
    id: "failed",
    label: "Failed",
    statuses: ["failed"],
    colorClass: "bg-red-50 border-red-200",
    headerClass: "bg-red-100 text-red-700",
  },
  {
    id: "blocked",
    label: "Blocked",
    statuses: ["blocked"],
    colorClass: "bg-amber-50 border-amber-200",
    headerClass: "bg-amber-100 text-amber-700",
  },
];
