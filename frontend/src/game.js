import { getConnectionId } from "./connection.js";
import { createSyncScheduler } from "./sync.js";
import { createMapController } from "./map.js";
import { renderLeaderboard } from "./leaderboard.js";
import { createHud } from "./hud.js";
import { createDebugPanel } from "./debug-panel.js";

const params = new URLSearchParams(window.location.search);
const room = params.get("room");
const playerId = params.get("player_id");
const observe = params.get("observe") === "1";

if (!room || !playerId) {
  window.location.href = "/lobby";
}

const scheduler = createSyncScheduler();
const map = createMapController(
  document.getElementById("map-container"),
  document.getElementById("map-overlay"),
  async (lat, lon) => {
    try {
      await scheduler.postAction("/api/place_guess", { lat, lon });
    } catch (e) {
      console.error(e);
    }
  }
);

map.setSelfId(playerId);
map.setObserve(observe);

const hud = createHud(
  {
    roundCurrent: document.getElementById("round-current"),
    roundMax: document.getElementById("round-max"),
    countdown: document.getElementById("round-countdown"),
    multLabel: document.getElementById("mult-label"),
    dmgMult: document.getElementById("dmg-mult"),
    submitBtn: document.getElementById("submit-btn"),
  },
  scheduler,
  playerId,
  observe
);

const debugPanel = createDebugPanel(
  document.getElementById("debug-panel"),
  document.getElementById("debug-log")
);

document.getElementById("debug-reveal")?.addEventListener("click", () => {
  fetch(
    `/api/reveal?room=${encodeURIComponent(room)}&player_id=${encodeURIComponent(playerId)}`
  ).then(() => scheduler.fetchState());
});

document.getElementById("debug-prev")?.addEventListener("click", () => {
  scheduler.postAction("/api/prev_round").catch(console.error);
});

document.getElementById("debug-next")?.addEventListener("click", () => {
  scheduler.postAction("/api/next_round").catch(console.error);
});

if (observe) {
  document.getElementById("observe-banner").style.display = "block";
  map.setClickable(false);
}

const refOverlay = document.getElementById("ref-overlay");
document.getElementById("refmap-btn")?.addEventListener("click", () => {
  refOverlay.classList.add("open");
});
refOverlay?.addEventListener("click", () => refOverlay.classList.remove("open"));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") refOverlay.classList.remove("open");
});

document.getElementById("back-lobby")?.addEventListener("click", () => {
  window.location.href = "/lobby";
});

function updateUI(state) {
  if (state.pin_colors) map.setPinColors(state.pin_colors);
  map.render(state);
  renderLeaderboard(document.getElementById("leaderboard"), state, playerId);
  hud.update(state);

  const qImg = document.getElementById("question-img");
  if (state.question_img) qImg.src = `/${state.question_img}`;

  const comment = document.getElementById("question-comment");
  if (state.question_comment) {
    comment.textContent = state.question_comment;
    comment.style.display = "block";
  } else {
    comment.style.display = "none";
  }

  const answerInfo = document.getElementById("answer-info");
  if (state.answer_revealed && state.answer_loc) {
    document.getElementById("answer-name").textContent = state.answer_loc.name;
    answerInfo.style.display = "block";
  } else {
    answerInfo.style.display = "none";
  }

  map.setClickable(state.phase === "guess" && !observe);

  const go = document.getElementById("game-over-overlay");
  const goLeaderboard = document.getElementById("game-over-leaderboard");
  if (state.phase === "game_over" && state.rankings) {
    renderLeaderboard(goLeaderboard, state, playerId);
    go.classList.add("open");
  } else {
    go.classList.remove("open");
    if (goLeaderboard) goLeaderboard.innerHTML = "";
  }

  debugPanel.update(state);
}

scheduler.onState(updateUI);
scheduler.onLog((msg) => debugPanel.log(msg));

scheduler.connect(room, playerId).catch(() => {
  alert("Room not found. Return to lobby.");
  window.location.href = "/lobby";
});

window.addEventListener("pagehide", () => {
  const payload = JSON.stringify({
    connection_id: getConnectionId(),
  });
  navigator.sendBeacon(
    `/api/exit?room=${encodeURIComponent(room)}&player_id=${encodeURIComponent(playerId)}`,
    new Blob([payload], { type: "application/json" })
  );
});
