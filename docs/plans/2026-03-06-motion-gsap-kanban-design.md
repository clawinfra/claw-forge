# Motion.dev + GSAP Kanban UI Enhancement

**Date:** 2026-03-06
**Style:** Functional & Fast — animations aid comprehension, never ornamental
**Libraries:** `motion` (Motion.dev v11) + `gsap` (GSAP 3)

## Architectural Rule

| Library | Surface | Rationale |
|---------|---------|-----------|
| `motion/react` | React component boundaries (enter/exit/layout) | AnimatePresence handles unmounted components; layout prop handles reflow |
| `gsap` | Numeric DOM values via `useRef` + `useEffect` | Superior easing curves for counters and progress tweens |

Zero conflicts — they operate on entirely different surfaces.

## Dependencies

```bash
npm --prefix ui install motion gsap
```

## Changes by File

### `ui/package.json`
- Add `motion` and `gsap` to `dependencies`

### `ui/src/components/FeatureCard.tsx`
**Card enter/exit (column list must wrap in `AnimatePresence`):**
```tsx
// Each card's outer div → motion.div
initial={{ opacity: 0, y: -8 }}
animate={{ opacity: 1, y: 0, transition: { duration: 0.2, ease: "easeOut" } }}
exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.15 } }}
layout  // cards shift smoothly when a card above exits
```

**Status badge → motion.span with key={feature.status}:**
```tsx
initial={{ scale: 0.8, opacity: 0 }}
animate={{ scale: 1, opacity: 1, transition: { type: "spring", stiffness: 400, damping: 20 } }}
```

### `ui/src/App.tsx`
**Column card lists:** Wrap `cards.map(...)` in `<AnimatePresence initial={false}>` so existing cards don't animate on first load.

**Drag overlay ghost card:**
```tsx
<DragOverlay>
  <motion.div
    initial={{ scale: 1.02, rotate: 1.5 }}
    animate={{ scale: 1.02, rotate: 1.5 }}
    style={{ boxShadow: "0 20px 40px rgba(0,0,0,0.2)" }}
  >
    <FeatureCard feature={activeFeature} />
  </motion.div>
</DragOverlay>
```

**Drop zone column highlight:** Replace hard CSS class swap with `motion.div animate={{ backgroundColor }}` transition on the pending column.

**Header — agent count counter (GSAP):**
```tsx
const countRef = useRef<HTMLSpanElement>(null);
useEffect(() => {
  const obj = { val: 0 };
  gsap.to(obj, { val: summary.running, duration: 0.4, snap: { val: 1 },
    onUpdate: () => { if (countRef.current) countRef.current.textContent = String(Math.round(obj.val)); }
  });
}, [summary.running]);
```

### `ui/src/components/ProgressBar.tsx`
Replace CSS `transition` on the fill bar with GSAP tween:
```tsx
const fillRef = useRef<HTMLDivElement>(null);
useEffect(() => {
  gsap.to(fillRef.current, { width: `${pct}%`, duration: 0.6, ease: "power2.out" });
}, [pct]);
```
Remove `transition-all duration-500` from the fill element's className.

### `ui/src/components/FeatureDetailDrawer.tsx`
Wrap drawer panel in `motion.div` inside `AnimatePresence`:
```tsx
initial={{ x: "100%", opacity: 0 }}
animate={{ x: 0, opacity: 1, transition: { type: "spring", stiffness: 300, damping: 30 } }}
exit={{ x: "100%", opacity: 0, transition: { duration: 0.2 } }}
```

### `ui/src/components/ActivityLogPanel.tsx`
Same spring slide-from-right pattern as FeatureDetailDrawer.

### `ui/src/components/CommandPalette.tsx`
```tsx
initial={{ scale: 0.96, opacity: 0, y: -8 }}
animate={{ scale: 1, opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" } }}
exit={{ scale: 0.96, opacity: 0, transition: { duration: 0.1 } }}
```

### `ui/src/components/TaskDetailModal.tsx`
Replace CSS `animate-slide-up` with Motion spring bottom sheet:
```tsx
initial={{ y: "100%", opacity: 0 }}
animate={{ y: 0, opacity: 1, transition: { type: "spring", stiffness: 350, damping: 35 } }}
exit={{ y: "100%", opacity: 0 }}
```

### `ui/src/index.css`
Remove unused CSS keyframes that are replaced by Motion.dev:
- `slide-up` / `.animate-slide-up`

Keep existing keyframes that remain in use:
- `slide-in-right` (toast — not yet migrated)
- `mascot-glow`, `confetti-*`, `celebration-pop`, `fab-expand`, `fade-in`

## Files Not Changed
- `DependencyGraph.tsx` — no motion needed
- `CelebrationOverlay.tsx` — existing CSS confetti is sufficient
- `ToastContainer.tsx` — existing CSS slide-in is sufficient
- All hooks and utility files

## Performance Notes
- `AnimatePresence initial={false}` prevents animating cards that are already on-screen at page load
- `layout` prop on cards uses GPU-accelerated FLIP technique — no layout thrashing
- GSAP tweens operate on `ref.current` — no React re-renders during counter/progress animations
- Both libraries are tree-shaken; estimated bundle addition: ~35KB gzipped
