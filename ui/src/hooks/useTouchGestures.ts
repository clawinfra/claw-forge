/**
 * useTouchGestures — provides pinch-to-zoom and swipe detection for touch UIs.
 *
 * Returns:
 *  - scale: current zoom level (1 = default)
 *  - swipeDirection: "left" | "right" | null after each swipe
 *  - clearSwipe(): reset swipe state
 *  - boardRef: attach to the scrollable board container
 */
import { useCallback, useRef, useState } from "react";

export type SwipeDirection = "left" | "right" | null;

interface TouchGestureOptions {
  /** Minimum horizontal distance (px) to count as a swipe */
  swipeThreshold?: number;
  /** Minimum & maximum zoom scale */
  minScale?: number;
  maxScale?: number;
}

export function useTouchGestures(options: TouchGestureOptions = {}) {
  const { swipeThreshold = 50, minScale = 0.5, maxScale = 2 } = options;

  const [scale, setScale] = useState(1);
  const [swipeDirection, setSwipeDirection] = useState<SwipeDirection>(null);

  // Refs for touch tracking
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null);
  const pinchStartDistRef = useRef<number | null>(null);
  const pinchStartScaleRef = useRef<number>(1);
  const boardRef = useRef<HTMLDivElement>(null);

  const clearSwipe = useCallback(() => setSwipeDirection(null), []);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      // Pinch start
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      pinchStartDistRef.current = Math.hypot(dx, dy);
      pinchStartScaleRef.current = scale;
    } else if (e.touches.length === 1) {
      touchStartRef.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
        time: Date.now(),
      };
    }
    // We intentionally do NOT call e.preventDefault() here to avoid blocking scrolling
  }, [scale]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2 && pinchStartDistRef.current !== null) {
      // Pinch zoom
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      const ratio = dist / pinchStartDistRef.current;
      const newScale = Math.min(maxScale, Math.max(minScale, pinchStartScaleRef.current * ratio));
      setScale(newScale);
    }
  }, [minScale, maxScale]);

  const onTouchEnd = useCallback((e: React.TouchEvent) => {
    // End pinch
    if (pinchStartDistRef.current !== null && e.touches.length < 2) {
      pinchStartDistRef.current = null;
    }

    // Detect swipe (single finger)
    if (e.changedTouches.length === 1 && touchStartRef.current) {
      const start = touchStartRef.current;
      const endX = e.changedTouches[0].clientX;
      const endY = e.changedTouches[0].clientY;
      const dx = endX - start.x;
      const dy = endY - start.y;
      const elapsed = Date.now() - start.time;

      // Must be mostly horizontal, fast enough, and far enough
      if (Math.abs(dx) > swipeThreshold && Math.abs(dx) > Math.abs(dy) * 1.5 && elapsed < 500) {
        setSwipeDirection(dx < 0 ? "left" : "right");
      }
      touchStartRef.current = null;
    }
  }, [swipeThreshold]);

  // Wheel-based zoom (desktop pinch via trackpad)
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey) {
      e.preventDefault();
      const delta = -e.deltaY * 0.01;
      setScale((prev) => Math.min(maxScale, Math.max(minScale, prev + delta)));
    }
  }, [minScale, maxScale]);

  return {
    scale,
    setScale,
    swipeDirection,
    clearSwipe,
    boardRef,
    touchHandlers: {
      onTouchStart,
      onTouchMove,
      onTouchEnd,
      onWheel,
    },
  };
}
