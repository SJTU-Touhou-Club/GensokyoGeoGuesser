/**
 * Optimistic countdown: ticks locally, re-anchors on each server contact.
 * Prefers remainingSeconds (computed at send time); falls back to deadline (unix sec).
 */
export function createSyncedCountdown({ tickMs = 250, onTick, onExpire } = {}) {
  let timer = null;
  let endAt = 0;

  function stop() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    endAt = 0;
  }

  function remainingSeconds() {
    if (endAt <= 0) return 0;
    return Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
  }

  function ensureTimer() {
    if (timer) return;
    timer = setInterval(() => {
      if (endAt <= 0) return;
      const left = remainingSeconds();
      if (onTick) onTick(left);
      if (endAt - Date.now() <= 0) {
        stop();
        if (onExpire) onExpire();
      }
    }, tickMs);
  }

  /** @returns {number|null} remaining seconds after sync, or null if inactive */
  function sync({ remainingSeconds: remaining, deadline, active = true } = {}) {
    if (!active) {
      stop();
      return null;
    }
    let secs = null;
    if (typeof remaining === "number") {
      secs = remaining;
    } else if (deadline != null) {
      secs = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
    }
    if (secs == null) {
      stop();
      return null;
    }
    endAt = Date.now() + secs * 1000;
    if (onTick) onTick(remainingSeconds());
    ensureTimer();
    return remainingSeconds();
  }

  return { sync, stop, remainingSeconds };
}
