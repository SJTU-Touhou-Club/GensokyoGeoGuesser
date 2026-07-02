import { getConnectionId } from "./connection.js";

export function createSyncScheduler() {
  let roomId = null;
  let playerId = null;
  let localVersion = 0;
  let evtSource = null;
  let fetchTimer = null;
  let pollTimer = null;
  let pollAttempt = 0;
  let onStateCb = null;
  let onLogCb = null;
  let destroyed = false;

  function log(msg) {
    if (onLogCb) onLogCb(msg);
  }

  function qs(extra = {}) {
    const p = new URLSearchParams({
      room: roomId,
      player_id: playerId,
      ...extra,
    });
    return p.toString();
  }

  function applyStateIfNewer(data) {
    if (!data || typeof data.state_version !== "number") return;
    if (data.state_version < localVersion) {
      log(`discard stale v${data.state_version} < ${localVersion}`);
      return;
    }
    localVersion = data.state_version;
    try {
      if (onStateCb) onStateCb(data);
    } catch (e) {
      console.error("UI update failed:", e);
      log(`UI error: ${e.message}`);
    }
  }

  function scheduleFetch(delay = 100) {
    if (fetchTimer) clearTimeout(fetchTimer);
    fetchTimer = setTimeout(() => fetchState(), delay);
  }

  async function fetchState() {
    if (destroyed) return null;
    try {
      const url = `/api/state?${qs({ connection_id: getConnectionId() })}`;
      const r = await fetch(url);
      if (r.status === 404) {
        log("room not found");
        return null;
      }
      const data = await r.json();
      if (data.error) {
        log(`state error: ${data.code}`);
        return null;
      }
      applyStateIfNewer(data);
      return data;
    } catch (e) {
      log(`fetch failed: ${e.message}`);
      return null;
    }
  }

  function startPollingFallback() {
    if (pollTimer) return;
    log("SSE error, polling fallback");
    if (evtSource) {
      evtSource.close();
      evtSource = null;
    }
    const attempt = () => {
      if (destroyed) return;
      const delay = Math.min(16000, 1000 * 2 ** pollAttempt);
      pollTimer = setTimeout(async () => {
        const ok = await fetchState();
        if (ok) {
          pollAttempt = Math.max(0, pollAttempt - 1);
          if (pollAttempt <= 0 && !evtSource) connectEventSource();
        } else {
          pollAttempt = Math.min(4, pollAttempt + 1);
        }
        attempt();
      }, delay);
    };
    pollAttempt = 0;
    attempt();
  }

  function connectEventSource() {
    if (destroyed || evtSource) return;
    evtSource = new EventSource(`/events/${encodeURIComponent(roomId)}`);
    evtSource.onmessage = () => scheduleFetch();
    evtSource.onerror = () => startPollingFallback();
  }

  return {
    connect(rid, pid) {
      roomId = rid;
      playerId = pid;
      localVersion = 0;
      destroyed = false;
      return fetchState()
        .then(() => connectEventSource())
        .catch((e) => {
          console.error("connect failed:", e);
          connectEventSource();
        });
    },

    async postAction(path, body = {}) {
      const url = `${path}?${qs()}`;
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, connection_id: getConnectionId() }),
      });
      const data = await r.json();
      if (data.error) throw new Error(data.code || data.error);
      applyStateIfNewer(data);
      scheduleFetch(100);
      return data;
    },

    fetchState,

    onState(cb) {
      onStateCb = cb;
    },

    onLog(cb) {
      onLogCb = cb;
    },

    destroy() {
      destroyed = true;
      if (evtSource) evtSource.close();
      if (fetchTimer) clearTimeout(fetchTimer);
      if (pollTimer) clearTimeout(pollTimer);
    },
  };
}
