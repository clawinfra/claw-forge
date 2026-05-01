/**
 * ConfirmModal — generic confirmation dialog.
 *
 * Replaces ``window.confirm()`` for any in-app confirmation flow.
 * Backdrop dims; click-outside, the X button, or the Cancel button all
 * dismiss with ``onCancel``.  ``onConfirm`` fires when the user clicks the
 * primary action button.  ``tone`` colors the primary button (and its
 * hover) — ``info`` (blue) for routine actions like "Reset All to
 * Pending", ``warning`` (amber) for actions that need extra thought,
 * ``danger`` (red) for destructive actions like delete.
 *
 * The component is uncontrolled in terms of close-after-confirm — the
 * caller is responsible for setting ``isOpen=false`` after acting on the
 * confirm signal.  This keeps the modal pure and lets callers run async
 * work without the modal vanishing too eagerly.
 */
import { AlertTriangle, CheckCircle2, X } from "lucide-react";

type ModalTone = "info" | "warning" | "danger";

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ModalTone;
  onConfirm: () => void;
  onCancel: () => void;
}

const TONE_CLASSES: Record<ModalTone, {
  iconColor: string;
  confirmBtn: string;
  Icon: typeof CheckCircle2;
}> = {
  info: {
    iconColor: "text-blue-500 dark:text-blue-400",
    confirmBtn:
      "bg-blue-600 hover:bg-blue-700 text-white dark:bg-blue-500 dark:hover:bg-blue-600",
    Icon: CheckCircle2,
  },
  warning: {
    iconColor: "text-amber-500 dark:text-amber-400",
    confirmBtn:
      "bg-amber-600 hover:bg-amber-700 text-white dark:bg-amber-500 dark:hover:bg-amber-600",
    Icon: AlertTriangle,
  },
  danger: {
    iconColor: "text-red-500 dark:text-red-400",
    confirmBtn:
      "bg-red-600 hover:bg-red-700 text-white dark:bg-red-500 dark:hover:bg-red-600",
    Icon: AlertTriangle,
  },
};

export function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "info",
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  if (!isOpen) return null;
  const { iconColor, confirmBtn, Icon } = TONE_CLASSES[tone];

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={onCancel}
      role="presentation"
    >
      <div
        className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-start gap-3">
            <Icon size={20} className={`${iconColor} mt-0.5 shrink-0`} aria-hidden="true" />
            <h3
              id="confirm-modal-title"
              className="font-semibold text-slate-800 dark:text-slate-100"
            >
              {title}
            </h3>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300 transition-colors"
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>

        {/* Message */}
        <div className="px-5 py-4 text-sm text-slate-600 dark:text-slate-300 whitespace-pre-line">
          {message}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 bg-slate-50 dark:bg-slate-900/40 border-t border-slate-200 dark:border-slate-700">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-sm font-medium rounded-md text-slate-700 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`px-3 py-1.5 text-sm font-semibold rounded-md transition-colors ${confirmBtn}`}
            data-testid="confirm-modal-confirm"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
