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
  INVALID_ROUNDS: "Rounds must be between the configured limits.",
  INVALID_DIFFICULTY: "Selected difficulty is not available.",
  INVALID_SCORING_STRATEGY: "Scoring must be ranking or distance.",
};

let evtSource = null;
let heartbeatTimer = null;
let reconnectDelay = 1000;
let currentRoom = null;
let selfPlayerId = null;
let isHost = false;
let role = "player";
let playerLimits = { min: 1, max: 10 };
let gameSettings = {
  rounds: { min: 1, max: 20, default: 6 },
  difficulties: ["N", "L"],
  default_difficulty: "N",
  scoring_strategies: ["ranking", "distance"],
  default_scoring_strategy: "ranking",
};
let lastRoomSettings = {
  min: 2,
  max: 8,
  rounds: 6,
  difficulty: "N",
  scoring_strategy: "ranking",
};
let syncingSettings = false;
let soloLimits = null;

const els = {
  playerId: document.getElementById("player-id"),
  roomId: document.getElementById("room-id"),
  minPlayers: document.getElementById("min-players"),
  maxPlayers: document.getElementById("max-players"),
  rounds: document.getElementById("rounds"),
  difficulty: document.getElementById("difficulty"),
  scoringStrategy: document.getElementById("scoring-strategy"),
  join: document.getElementById("btn-join"),
  solo: document.getElementById("btn-solo"),
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

function applyGameSettings(settings) {
  if (!settings) return;
  gameSettings = { ...gameSettings, ...settings };
  if (settings.rounds) {
    els.rounds.min = settings.rounds.min;
    els.rounds.max = settings.rounds.max;
    if (!currentRoom) els.rounds.value = settings.rounds.default;
  }
  if (settings.difficulties) {
    const current = els.difficulty.value;
    els.difficulty.innerHTML = "";
    for (const d of settings.difficulties) {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      els.difficulty.appendChild(opt);
    }
    const preferred =
      settings.difficulties.includes(current)
        ? current
        : settings.default_difficulty || settings.difficulties[0];
    if (preferred) els.difficulty.value = preferred;
  }
  if (settings.scoring_strategies) {
    const current = els.scoringStrategy.value;
    els.scoringStrategy.innerHTML = "";
    for (const s of settings.scoring_strategies) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      els.scoringStrategy.appendChild(opt);
    }
    const preferred =
      settings.scoring_strategies.includes(current)
        ? current
        : settings.default_scoring_strategy || settings.scoring_strategies[0];
    if (preferred) els.scoringStrategy.value = preferred;
  }
}

function syncSettingsInputs(room) {
  if (!room) return;
  syncingSettings = true;
  if (room.min_players != null) els.minPlayers.value = room.min_players;
  if (room.max_players != null) els.maxPlayers.value = room.max_players;
  if (room.rounds != null) els.rounds.value = room.rounds;
  if (room.difficulty != null) els.difficulty.value = room.difficulty;
  if (room.scoring_strategy != null) {
    els.scoringStrategy.value = room.scoring_strategy;
  }
  lastRoomSettings = {
    min: Number(els.minPlayers.value),
    max: Number(els.maxPlayers.value),
    rounds: Number(els.rounds.value),
    difficulty: els.difficulty.value,
    scoring_strategy: els.scoringStrategy.value,
  };
  syncingSettings = false;
}

function showError(code) {
  els.statusText.textContent = ERROR_MESSAGES[code] || code;
  els.statusBar.style.display = "block";
}

document.getElementById("status-close")?.addEventListener("click", () => {
  els.statusBar.style.display = "none";
});

const MAP_CACHE_URLS = ["/media/map_v2.jpg", "/media/ref_map_v2.jpg"];

function warmMapCache() {
  for (const url of MAP_CACHE_URLS) {
    const img = new Image();
    if ("fetchPriority" in img) img.fetchPriority = "low";
    img.decoding = "async";
    img.src = url;
  }
}

function ensureRefMapSrc() {
  const img = els.refOverlay?.querySelector("img");
  if (!img) return;
  const src = img.dataset.src || "/media/ref_map_v2.jpg";
  if (img.getAttribute("src") !== src) img.src = src;
}

// Low-priority warm so match → game hits HTTP cache instead of a map burst.
if ("requestIdleCallback" in window) {
  requestIdleCallback(() => warmMapCache(), { timeout: 2500 });
} else {
  setTimeout(warmMapCache, 1200);
}

els.refMap?.addEventListener("click", () => {
  ensureRefMapSrc();
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
    if (!isHost || (el.id === "minmax-row" && soloLimits)) {
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
  applyGameSettings(data.game_settings);
  els.waiting.style.display = "block";
  els.cancel.style.display = "";
  els.join.disabled = true;
  els.solo.disabled = true;
  els.observe.disabled = true;
  updateRoomUI(data.room);
  connectLobbySSE(data.sse_url);
  startHeartbeat();
}

function updateRoomUI(room) {
  if (!room) return;
  if (selfPlayerId && Object.prototype.hasOwnProperty.call(room, "host_id")) {
    isHost = room.host_id === selfPlayerId;
  }
  els.wrRoom.textContent = room.room_id;
  if (Object.prototype.hasOwnProperty.call(room, "host_id")) {
    els.wrHost.textContent = room.host_id;
  }
  const lines = (room.players || [])
    .map((p) => {
      const mark = p.player_id === room.host_id ? "*" : "";
      return `${p.player_id}${mark}`;
    })
    .join(", ");
  els.wrPlayers.textContent = `Players (${(room.players || []).length}/${room.max_players}): ${lines}`;
  syncSettingsInputs(room);

  const status = room.status;
  const n = (room.players || []).length;
  const min = room.min_players;
  let text = "";
  if (status === "WAITING" && room.max_players === 1) {
    text = "Solo ready. Choose your settings, then press Start Game Now.";
  } else if (status === "WAITING" && n < min) {
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
      host_id:
        partial.host_id !== undefined ? partial.host_id : els.wrHost.textContent,
      min_players: partial.min_players,
      max_players: partial.max_players,
      rounds: partial.rounds,
      difficulty: partial.difficulty,
      scoring_strategy: partial.scoring_strategy,
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
          .then((data) => {
            if (data.game_settings) applyGameSettings(data.game_settings);
            if (data.player_limits) applyPlayerLimitBounds(data.player_limits);
            updateRoomUI(data);
          })
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
  if (!currentRoom || !isHost || syncingSettings) return;
  const min_players = Number(els.minPlayers.value);
  const max_players = Number(els.maxPlayers.value);
  const rounds = Number(els.rounds.value);
  const difficulty = els.difficulty.value;
  const scoring_strategy = els.scoringStrategy.value;
  if (max_players < min_players) {
    showError("INVALID_PLAYER_LIMITS");
    syncSettingsInputs(lastRoomSettings);
    return;
  }
  try {
    const data = await post("/api/lobby/update_settings", {
      room_id: currentRoom,
      player_id: selfPlayerId,
      min_players,
      max_players,
      rounds,
      difficulty,
      scoring_strategy,
    });
    if (data.player_limits) applyPlayerLimitBounds(data.player_limits);
    if (data.game_settings) applyGameSettings(data.game_settings);
    updateRoomUI(data.room);
  } catch (e) {
    syncSettingsInputs(lastRoomSettings);
    showError(e.code || e.error);
  }
}

els.minPlayers.addEventListener("change", () => {
  pushRoomSettings();
});
els.maxPlayers.addEventListener("change", () => {
  pushRoomSettings();
});
els.rounds.addEventListener("change", () => {
  pushRoomSettings();
});
els.difficulty.addEventListener("change", () => {
  pushRoomSettings();
});
els.scoringStrategy.addEventListener("change", () => {
  pushRoomSettings();
});

async function joinRoom(solo = false) {
  const player_id = els.playerId.value.trim() ||
    (solo ? `solo-${crypto.randomUUID().slice(0, 12)}` : "");
  els.playerId.value = player_id;
  setStoredPlayerId(player_id);
  els.join.disabled = true;
  els.solo.disabled = true;
  els.observe.disabled = true;
  try {
    const room_id = solo ? `solo_${crypto.randomUUID()}` : els.roomId.value.trim() || null;
    const data = await post("/api/lobby/join", {
      room_id,
      player_id,
      connection_id: getConnectionId(),
      min_players: solo ? 1 : Number(els.minPlayers.value),
      max_players: solo ? 1 : Number(els.maxPlayers.value),
      rounds: Number(els.rounds.value),
      difficulty: els.difficulty.value,
      scoring_strategy: els.scoringStrategy.value,
    });
    soloLimits = solo ? {
      min: Number(els.minPlayers.value),
      max: Number(els.maxPlayers.value),
    } : null;
    enterWaiting(data);
  } catch (e) {
    showError(e.code || e.error);
    els.join.disabled = false;
    els.solo.disabled = false;
    els.observe.disabled = false;
  }
}

els.join.addEventListener("click", () => joinRoom());
els.solo.addEventListener("click", () => joinRoom(true));

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
  if (soloLimits) {
    els.minPlayers.value = soloLimits.min;
    els.maxPlayers.value = soloLimits.max;
    soloLimits = null;
  }
  isHost = false;
  setHostOnlyVisible();
  els.waiting.style.display = "none";
  els.cancel.style.display = "none";
  els.join.disabled = false;
  els.solo.disabled = false;
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
