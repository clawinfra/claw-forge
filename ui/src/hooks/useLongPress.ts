/**
 * useLongPress — detects a long-press (500ms default) on a touch target.
 * Returns event handlers to attach to the target element.
 * Calls `onLongPress` callback when triggered with haptic feedback.
 */
import { useCallback, useRef } from "react";
import { triggerHaptic } from "../utils/haptic";

interface LongPressOptions {
  /** Duration in ms before long-press fires (default 500) */
  duration?: number;
  /** Callback when long-press completes */
  onLongPress: () => void;
  /** Callback for regular tap (shorter than duration) */
  onTap?: () => void;
}

export function useLongPress({ duration = 500, onLongPress, onTap }: LongPressOptions) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressTriggeredRef = useRef(false);
  const startPosRef = useRef<{ x: number; y: number } | null>(null);

  const clear = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      longPressTriggeredRef.current = false;
      startPosRef.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
      };
      timerRef.current = setTimeout(() => {
        longPressTriggeredRef.current = true;
        triggerHaptic(50);
        onLongPress();
      }, duration);
    },
    [duration, onLongPress],
  );

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      // Cancel long-press if finger moves too far
      if (startPosRef.current) {
        const dx = Math.abs(e.touches[0].clientX - startPosRef.current.x);
        const dy = Math.abs(e.touches[0].clientY - startPosRef.current.y);
        if (dx > 10 || dy > 10) {
          clear();
        }
      }
    },
    [clear],
  );

  const onTouchEnd = useCallback(() => {
    clear();
    if (!longPressTriggeredRef.current && onTap) {
      onTap();
    }
  }, [clear, onTap]);

  return {
    onTouchStart,
    onTouchMove,
    onTouchEnd,
  };
}
