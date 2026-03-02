/**
 * ToastContainer — tiny custom toast notification system.
 * Bottom-right, auto-dismiss 3s, colour-coded by type.
 */
import { X } from "lucide-react";
import type { Toast } from "../types";

const TYPE_STYLES: Record<Toast["type"], string> = {
  success:
    "bg-emerald-600 dark:bg-emerald-700 text-white",
  error:
    "bg-red-600 dark:bg-red-700 text-white",
  info:
    "bg-blue-600 dark:bg-blue-700 text-white",
  warning:
    "bg-amber-500 dark:bg-amber-600 text-white",
};

interface ToastContainerProps {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-16 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium
            animate-slide-in-right ${TYPE_STYLES[toast.type]}`}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            className="shrink-0 opacity-70 hover:opacity-100 transition-opacity"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
