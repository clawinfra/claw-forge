/**
 * Haptic feedback utility.
 * Calls navigator.vibrate() on supported devices.
 */

export function triggerHaptic(durationMs = 50): void {
  try {
    if (navigator.vibrate) {
      navigator.vibrate(durationMs);
    }
  } catch {
    // Silently ignore — vibration not supported
  }
}
