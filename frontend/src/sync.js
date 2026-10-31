import { getConnectionId, requestJson } from "./connection.js";

export function createSyncScheduler() {
  let roomId, playerId;
  let localVersion = -1;
  let latestState = null;
  let evtSource = null;
  let pollTimer = null;
  let reconnectTimer = null;
  let fetchTimer = null;
  let inFlight = null;
  let fetchAgain = false;
  let actionQueue = Promise.resolve();
  let latestGuess = null;
  let onStateCb, onLogCb, onStatusCb;
  let destroyed = true;
  let suspended = false;
  let generation = 0;
  let lastStream = 0;
  let retryDelay = 250;

  const log = message => onLogCb?.(message);
  const status = message => onStatusCb?.(message);
  const qs = () => new URLSearchParams({ room: roomId, player_id: playerId });

  function applyState(data) {
    if (destroyed || data?.state_version == null || data.state_version < localVersion) return;
    latestState = data;
    localVersion = data.state_version;
    status("");
    try { onStateCb?.(data); } catch (error) { log(`UI error: ${error.message}`); }
  }

  function fetchState() {
    if (destroyed || suspended) return Promise.resolve(null);
    if (inFlight) {
      fetchAgain = true;
      return inFlight;
    }
    const currentGeneration = generation;
    inFlight = requestJson(`/api/state?${qs()}&connection_id=${encodeURIComponent(getConnectionId())}`)
      .then(data => {
        if (currentGeneration === generation) applyState(data);
        return data;
      })
      .catch(error => {
        if (currentGeneration === generation && !destroyed) {
          log(`State request: ${error.code || error.message}`);
          status(error.status === 404 ? "Game no longer available." : "Reconnecting…");
        }
        return null;
      })
      .finally(() => {
        if (currentGeneration !== generation) return;
        inFlight = null;
        if (fetchAgain && !destroyed && !suspended) {
          fetchAgain = false;
          scheduleFetch();
        }
      });
    return inFlight;
  }

  function scheduleFetch() {
    if (fetchTimer || destroyed || suspended) return;
    fetchTimer = setTimeout(() => { fetchTimer = null; fetchState(); }, 30);
  }

  function reconnect() {
    evtSource?.close();
    evtSource = null;
    if (destroyed || suspended || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectEvents();
    }, retryDelay + Math.random() * 100);
    retryDelay = Math.min(1500, retryDelay * 2);
  }

  function connectEvents() {
    if (destroyed || suspended || evtSource) return;
    const source = new EventSource(`/events/${encodeURIComponent(roomId)}`);
    evtSource = source;
    lastStream = Date.now();
    const alive = () => {
      if (source !== evtSource) return;
      lastStream = Date.now();
      retryDelay = 250;
    };
    source.onopen = () => { alive(); scheduleFetch(); };
    source.addEventListener("ping", alive);
    source.onmessage = () => { alive(); scheduleFetch(); };
    source.onerror = () => { if (source === evtSource) reconnect(); };
  }

  function resume() {
    if (destroyed || document.hidden) return;
    suspended = false;
    fetchState();
    connectEvents();
  }

  function suspend() {
    suspended = true;
    evtSource?.close();
    evtSource = null;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  async function deliver(command) {
    for (let attempt = 0; attempt < 2; attempt++) {
      if (destroyed || suspended) throw new Error("Connection is paused");
      try {
        const data = await requestJson(`${command.path}?${qs()}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(command.body),
        });
        if (command.body.action_id && data.ack?.action_id !== command.body.action_id) {
          throw new Error("Action acknowledgement missing");
        }
        command.acknowledged = true;
        applyState(data);
        return data;
      } catch (error) {
        if (error.status && error.status < 500 && error.status !== 408 && error.status !== 429) {
          await fetchState();
          throw error;
        }
        if (attempt === 1) {
          status("Action not confirmed. Reconnecting…");
          scheduleFetch();
          throw error;
        }
        await new Promise(resolve => setTimeout(resolve, 150 + Math.random() * 100));
      }
    }
  }

  window.addEventListener("online", resume);
  window.addEventListener("pageshow", resume);
  window.addEventListener("pagehide", suspend);
  const visibilityChanged = () => document.hidden ? suspend() : resume();
  document.addEventListener("visibilitychange", visibilityChanged);

  return {
    connect(rid, pid) {
      generation += 1;
      roomId = rid;
      playerId = pid;
      localVersion = -1;
      latestState = null;
      destroyed = false;
      suspended = false;
      inFlight = null;
      fetchAgain = false;
      latestGuess = null;
      clearInterval(pollTimer);
      connectEvents();
      // This bounded safety reconciliation also renews the player's presence lease.
      pollTimer = setInterval(() => {
        if (suspended || destroyed) return;
        fetchState();
        if (Date.now() - lastStream > 3000) reconnect();
      }, 2000);
      return fetchState();
    },

    postAction(path, body = {}) {
      const reliable = ["/api/place_guess", "/api/submit", "/api/agree_next"].includes(path);
      if (reliable && !latestState) return Promise.reject(new Error("Waiting for game state"));
      const sequence = Number(sessionStorage.getItem("ggg_action_sequence") || 0) + 1;
      sessionStorage.setItem("ggg_action_sequence", sequence);
      const command = { path, body: {
        ...body, connection_id: getConnectionId(),
        ...(reliable ? { action_id: crypto.randomUUID(), sequence, round: latestState.round } : {}),
      } };
      if (path === "/api/place_guess") latestGuess = command;
      const requiredGuess = path === "/api/submit" ? latestGuess : null;
      const task = actionQueue.catch(() => {}).then(async () => {
        if (requiredGuess && !requiredGuess.acknowledged) await deliver(requiredGuess);
        return deliver(command);
      });
      actionQueue = task;
      return task;
    },

    fetchState,
    onState(cb) { onStateCb = cb; },
    onLog(cb) { onLogCb = cb; },
    onStatus(cb) { onStatusCb = cb; },
    destroy() {
      destroyed = true;
      generation += 1;
      suspend();
      clearInterval(pollTimer);
      clearTimeout(fetchTimer);
      window.removeEventListener("online", resume);
      window.removeEventListener("pageshow", resume);
      window.removeEventListener("pagehide", suspend);
      document.removeEventListener("visibilitychange", visibilityChanged);
    },
  };
}
