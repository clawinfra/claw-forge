/**
 * ExecutionDrawer — slides up from bottom, streams command output in real-time.
 *
 * Shows last 3 executions stacked. Each has:
 *  - Header: command label + spinner/✅/❌ + duration + close
 *  - Body: terminal-style scrollable output (dark bg, monospace, green text)
 *  - "Copy output" button
 */

import { useEffect, useRef } from "react";
import { CheckCircle, Copy, Loader2, X, XCircle } from "lucide-react";
import type { Execution } from "../types";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ExecutionDrawerProps {
  executions: Execution[];
  onDismiss: (execution_id: string) => void;
}

// ── Single execution pane ─────────────────────────────────────────────────────

function ExecutionPane({
  execution,
  onDismiss,
}: {
  execution: Execution;
  onDismiss: (id: string) => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as output streams in
  useEffect(() => {
    const el = bodyRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [execution.output.length]);

  function handleCopy() {
    navigator.clipboard.writeText(execution.output.join("\n")).catch(() => {});
  }

  const isRunning = execution.status === "running";
  const isDone = execution.status === "done";
  const isFailed = execution.status === "failed";

  return (
    <div className="border border-slate-700 rounded-lg overflow-hidden shadow-xl">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-800 border-b border-slate-700">
        {isRunning && (
          <Loader2 size={14} className="text-blue-400 animate-spin shrink-0" />
        )}
        {isDone && <CheckCircle size={14} className="text-emerald-400 shrink-0" />}
        {isFailed && <XCircle size={14} className="text-red-400 shrink-0" />}

        <span className="flex-1 text-sm font-semibold text-slate-100 truncate">
          {execution.command_label}
        </span>

        {execution.duration_ms !== undefined && (
          <span className="text-xs text-slate-400 font-mono shrink-0">
            {execution.duration_ms}ms
          </span>
        )}

        {isRunning && (
          <span className="text-xs text-blue-400 animate-pulse shrink-0">running</span>
        )}

        <button
          type="button"
          onClick={handleCopy}
          title="Copy output"
          className="text-slate-400 hover:text-slate-200 transition-colors p-0.5 shrink-0"
        >
          <Copy size={13} />
        </button>

        <button
          type="button"
          onClick={() => onDismiss(execution.execution_id)}
          className="text-slate-400 hover:text-slate-200 transition-colors p-0.5 shrink-0"
        >
          <X size={14} />
        </button>
      </div>

      {/* Terminal body */}
      <div
        ref={bodyRef}
        className="bg-slate-950 px-3 py-2 max-h-40 overflow-y-auto font-mono text-xs
          text-emerald-400 leading-relaxed"
      >
        {execution.output.length === 0 && isRunning && (
          <span className="text-slate-500 animate-pulse">Waiting for output…</span>
        )}
        {execution.output.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}
        {!isRunning && execution.output.length === 0 && (
          <span className="text-slate-600">(no output)</span>
        )}
        {isFailed && execution.exit_code !== undefined && (
          <div className="mt-1 text-red-400 font-semibold">
            ✗ exited with code {execution.exit_code}
          </div>
        )}
        {isDone && (
          <div className="mt-1 text-emerald-500 font-semibold">✓ done</div>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExecutionDrawer({ executions, onDismiss }: ExecutionDrawerProps) {
  // Show last 3 executions
  const visible = executions.slice(-3);

  if (visible.length === 0) return null;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-40 pointer-events-none
        flex flex-col gap-2 p-4 items-end"
    >
      <div className="pointer-events-auto flex flex-col gap-2 w-full max-w-2xl mx-auto">
        {visible.map((ex) => (
          <ExecutionPane key={ex.execution_id} execution={ex} onDismiss={onDismiss} />
        ))}
      </div>
    </div>
  );
}
