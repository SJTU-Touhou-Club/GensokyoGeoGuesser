import {
  getConnectionId,
  getStoredPlayerId,
  setStoredPlayerId,
} from "./connection.js";
import { createSyncedCountdown } from "./countdown.js";

const ERROR_MESSAGES = {
  ROOM_IN_GAME: "Room already started. Use Observe to watch.",
  ROOM_FULL: "Room is full.",
  INVALID_PLAYER_ID: "Invalid player ID (1–32 characters).",
  NOT_HOST: "Only the host can start the game.",
  ALREADY_IN_ROOM: "You are already in another room. Leave first.",
  ROOM_NOT_FOUND: "Room not found.",
  INVALID_PLAYER_LIMITS: "Player limits must be between 1 and the number of pin colors, with min ≤ max.",
  MAX_BELOW_PLAYER_COUNT: "Max players cannot be below the current player count.",
};

let evtSource = null;
let heartbeatTimer = null;
let reconnectDelay = 1000;
let currentRoom = null;
let selfPlayerId = null;
let isHost = false;
let role = "player";
let playerLimits = { min: 1, max: 10 };
let lastRoomLimits = { min: 2, max: 8 };
let syncingLimits = false;

const els = {
  playerId: document.getElementById("player-id"),
  roomId: document.getElementById("room-id"),
  minPlayers: document.getElementById("min-players"),
  maxPlayers: document.getElementById("max-players"),
  join: document.getElementById("btn-join"),
  observe: document.getElementById("btn-observe"),
  refMap: document.getElementById("btn-refmap"),
  cancel: document.getElementById("btn-cancel"),
  start: document.getElementById("btn-start"),
  waiting: document.getElementById("waiting-room"),
  wrRoom: document.getElementById("wr-room"),
  wrHost: document.getElementById("wr-host"),
  wrPlayers: document.getElementById("wr-players"),
  wrStatus: document.getElementById("wr-status"),
  statusBar: document.getElementById("status-bar"),
  statusText: document.getElementById("status-text"),
  refOverlay: document.getElementById("lobby-ref-overlay"),
};

els.playerId.value = getStoredPlayerId();

function applyPlayerLimitBounds(limits) {
  if (!limits) return;
  playerLimits = limits;
  els.minPlayers.min = limits.min;
  els.minPlayers.max = limits.max;
  els.maxPlayers.min = limits.min;
  els.maxPlayers.max = limits.max;
}

function syncLimitInputs(room) {
  const min = room?.min_players ?? room?.min;
  const max = room?.max_players ?? room?.max;
  if (min == null || max == null) return;
  syncingLimits = true;
  els.minPlayers.value = min;
  els.maxPlayers.value = max;
  lastRoomLimits = { min, max };
  syncingLimits = false;
}

function showError(code) {
  els.statusText.textContent = ERROR_MESSAGES[code] || code;
  els.statusBar.style.display = "block";
}

document.getElementById("status-close")?.addEventListener("click", () => {
  els.statusBar.style.display = "none";
});

els.refMap?.addEventListener("click", () => {
  els.refOverlay?.classList.add("open");
});

els.refOverlay?.addEventListener("click", () => {
  els.refOverlay.classList.remove("open");
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    els.refOverlay?.classList.remove("open");
  }
});

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw data;
  return data;
}

const lobbyCountdown = createSyncedCountdown({
  onTick: (left) => {
    els.wrStatus.textContent = left > 0 ? `${left}s until start` : "Starting…";
  },
});

function syncLobbyCountdown(room) {
  if (room.status !== "COUNTDOWN") {
    lobbyCountdown.stop();
    return;
  }
  const left = lobbyCountdown.sync({
    remainingSeconds: room.countdown_remaining_seconds,
    deadline: room.countdown_deadline,
  });
  if (left == null) els.wrStatus.textContent = "?s until start";
}

function setHostOnlyVisible() {
  document.querySelectorAll(".host-only").forEach((el) => {
    if (!isHost) {
      el.style.display = "none";
      return;
    }
    if (el.classList.contains("row")) {
      el.style.display = "flex";
    } else if (el.tagName === "BUTTON") {
      el.style.display = "inline-block";
    } else {
      el.style.display = "block";
    }
  });
}

function enterWaiting(data) {
  currentRoom = data.room_id;
  selfPlayerId = els.playerId.value.trim();
  isHost = data.is_host;
  role = data.role;
  applyPlayerLimitBounds(data.player_limits);
  els.waiting.style.display = "block";
  els.cancel.style.display = "";
  els.join.disabled = true;
  els.observe.disabled = true;
  updateRoomUI(data.room);
  connectLobbySSE(data.sse_url);
  startHeartbeat();
}

function updateRoomUI(room) {
  if (!room) return;
  if (room.host_id && selfPlayerId) {
    isHost = room.host_id === selfPlayerId;
  }
  els.wrRoom.textContent = room.room_id;
  els.wrHost.textContent = room.host_id;
  const lines = (room.players || [])
    .map((p) => {
      const mark = p.player_id === room.host_id ? "*" : "";
      return `${p.player_id}${mark}`;
    })
    .join(", ");
  els.wrPlayers.textContent = `Players (${(room.players || []).length}/${room.max_players}): ${lines}`;
  syncLimitInputs(room);

  const status = room.status;
  const n = (room.players || []).length;
  const min = room.min_players;
  let text = "";
  if (status === "WAITING" && n < min) {
    text = `Waiting for players… (need at least ${min})`;
  } else if (status === "WAITING") {
    text = "Minimum reached. Waiting for host or more players.";
  } else if (status === "COUNTDOWN") {
    syncLobbyCountdown(room);
    setHostOnlyVisible();
    return;
  } else {
    lobbyCountdown.stop();
    if (status === "STARTING") {
      text = "Entering game…";
    } else if (status === "IN_GAME" && role === "spectator") {
      text = "Game in progress. Entering spectator view…";
    }
  }
  els.wrStatus.textContent = text;

  setHostOnlyVisible();
}

function connectLobbySSE(url) {
  if (evtSource) evtSource.close();
  evtSource = new EventSource(url);
  reconnectDelay = 1000;

  evtSource.addEventListener("lobby_snapshot", (e) => {
    const room = JSON.parse(e.data);
    updateRoomUI(room);
  });

  evtSource.addEventListener("lobby_update", (e) => {
    const partial = JSON.parse(e.data);
    const room = {
      room_id: currentRoom,
      host_id: els.wrHost.textContent,
      min_players: partial.min_players,
      max_players: partial.max_players,
      players: partial.players,
      spectators: partial.spectators,
      status: partial.status,
      countdown_deadline: partial.countdown_deadline,
      countdown_remaining_seconds: partial.countdown_remaining_seconds,
    };
    updateRoomUI(room);
  });

  evtSource.addEventListener("match_starting", (e) => {
    const data = JSON.parse(e.data);
    redirectToGame(data.room_id);
  });

  evtSource.onerror = () => {
    evtSource.close();
    evtSource = null;
    setTimeout(() => {
      if (currentRoom && selfPlayerId) {
        connectLobbySSE(
          `/events/lobby/${encodeURIComponent(currentRoom)}?player_id=${encodeURIComponent(selfPlayerId)}`
        );
        fetch(`/api/lobby/room_status?room_id=${encodeURIComponent(currentRoom)}`)
          .then((r) => r.json())
          .then(updateRoomUI)
          .catch(() => {});
      }
    }, reconnectDelay);
    reconnectDelay = Math.min(30000, reconnectDelay * 2);
  };
}

function startHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(() => {
    if (!currentRoom) return;
    post("/api/lobby/heartbeat", {
      room_id: currentRoom,
      player_id: selfPlayerId,
      connection_id: getConnectionId(),
    })
      .then((data) => {
        if (data.status) {
          syncLobbyCountdown(data);
        }
      })
      .catch(() => {});
  }, 5000);
}

async function pushRoomSettings() {
  if (!currentRoom || !isHost || syncingLimits) return;
  const min_players = Number(els.minPlayers.value);
  const max_players = Number(els.maxPlayers.value);
  if (max_players < min_players) {
    showError("INVALID_PLAYER_LIMITS");
    syncLimitInputs(lastRoomLimits);
    return;
  }
  try {
    const data = await post("/api/lobby/update_settings", {
      room_id: currentRoom,
      player_id: selfPlayerId,
      min_players,
      max_players,
    });
    if (data.player_limits) applyPlayerLimitBounds(data.player_limits);
    updateRoomUI(data.room);
  } catch (e) {
    syncLimitInputs(lastRoomLimits);
    showError(e.code || e.error);
  }
}

els.minPlayers.addEventListener("change", () => {
  pushRoomSettings();
});
els.maxPlayers.addEventListener("change", () => {
  pushRoomSettings();
});

els.join.addEventListener("click", async () => {
  const player_id = els.playerId.value.trim();
  setStoredPlayerId(player_id);
  els.join.disabled = true;
  try {
    const room_id = els.roomId.value.trim() || null;
    const data = await post("/api/lobby/join", {
      room_id,
      player_id,
      connection_id: getConnectionId(),
      min_players: Number(els.minPlayers.value),
      max_players: Number(els.maxPlayers.value),
    });
    enterWaiting(data);
  } catch (e) {
    showError(e.code || e.error);
    els.join.disabled = false;
  }
});

els.observe.addEventListener("click", async () => {
  const player_id = els.playerId.value.trim();
  const room_id = els.roomId.value.trim();
  if (!room_id) {
    showError("Room ID required for Observe");
    return;
  }
  setStoredPlayerId(player_id);
  els.observe.disabled = true;
  try {
    const data = await post("/api/lobby/observe", {
      room_id,
      player_id,
      connection_id: getConnectionId(),
    });
    enterWaiting(data);
  } catch (e) {
    showError(e.code || e.error);
    els.observe.disabled = false;
  }
});

els.cancel.addEventListener("click", async () => {
  if (currentRoom) {
    await post("/api/lobby/leave", {
      room_id: currentRoom,
      player_id: selfPlayerId,
      connection_id: getConnectionId(),
    }).catch(() => {});
  }
  if (evtSource) evtSource.close();
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  lobbyCountdown.stop();
  currentRoom = null;
  els.waiting.style.display = "none";
  els.cancel.style.display = "none";
  els.join.disabled = false;
  els.observe.disabled = false;
});

function redirectToGame(roomId) {
  const observeParam = role === "spectator" ? "&observe=1" : "";
  window.location.href = `/index.html?room=${encodeURIComponent(roomId)}&player_id=${encodeURIComponent(selfPlayerId)}${observeParam}`;
}

els.start?.addEventListener("click", async () => {
  if (!currentRoom || !isHost) return;
  els.start.disabled = true;
  try {
    await post("/api/lobby/start", {
      room_id: currentRoom,
      player_id: selfPlayerId,
    });
    redirectToGame(currentRoom);
  } catch (e) {
    els.start.disabled = false;
    showError(e.code || e.error);
  }
});

window.addEventListener("pagehide", () => {
  if (!currentRoom) return;
  const payload = JSON.stringify({
    room_id: currentRoom,
    player_id: selfPlayerId,
    connection_id: getConnectionId(),
  });
  navigator.sendBeacon("/api/lobby/leave", new Blob([payload], { type: "application/json" }));
});
