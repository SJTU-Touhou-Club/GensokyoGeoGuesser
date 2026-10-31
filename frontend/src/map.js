const ANSWER_COLOR = "#57EE55";
const OUTER_RING_SELF = "#ffffff";
const OUTER_RING_OTHER = "#9ca3af";
const LINE_STROKE_WIDTH = 0.5;
const MIN_ZOOM = 1;
const MAX_ZOOM = 5;

export function createMapController(container, overlay, onPlaceGuess) {
  const pins = {};
  let pinColors = [];
  let selfId = null;
  let observe = false;
  let clickable = true;

  let scale = 1;
  let panX = 0;
  let panY = 0;
  let panning = false;
  let panStart = { x: 0, y: 0, panX: 0, panY: 0 };

  const layer = ensureMapLayer(container);

  function ensureMapLayer(root) {
    let mapLayer = root.querySelector(".map-layer");
    if (mapLayer) return mapLayer;
    mapLayer = document.createElement("div");
    mapLayer.className = "map-layer";
    [...root.childNodes].forEach((node) => mapLayer.appendChild(node));
    root.appendChild(mapLayer);
    return mapLayer;
  }

  function clearLines() {
    if (overlay) overlay.innerHTML = "";
  }

  function applyTransform() {
    layer.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
  }

  function clampPan() {
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    const lw = layer.offsetWidth * scale;
    const lh = layer.offsetHeight * scale;
    const minX = Math.min(0, cw - lw);
    const minY = Math.min(0, ch - lh);
    panX = Math.min(0, Math.max(minX, panX));
    panY = Math.min(0, Math.max(minY, panY));
  }

  function zoomAt(clientX, clientY, nextScale) {
    const rect = container.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const lx = (mx - panX) / scale;
    const ly = (my - panY) / scale;
    scale = nextScale;
    if (scale <= 1) {
      scale = 1;
      panX = 0;
      panY = 0;
    } else {
      panX = mx - lx * scale;
      panY = my - ly * scale;
      clampPan();
    }
    applyTransform();
  }

  function resetZoom() {
    scale = 1;
    panX = 0;
    panY = 0;
    applyTransform();
  }

  container.addEventListener(
    "wheel",
    (e) => {
      if (!container.contains(e.target)) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale * factor));
      if (next === scale) return;
      zoomAt(e.clientX, e.clientY, next);
    },
    { passive: false }
  );

  container.addEventListener("mousedown", (e) => {
    if (e.button !== 2 || scale <= 1) return;
    e.preventDefault();
    panning = true;
    panStart = { x: e.clientX, y: e.clientY, panX, panY };
    container.classList.add("is-panning");
  });

  window.addEventListener("mousemove", (e) => {
    if (!panning) return;
    panX = panStart.panX + (e.clientX - panStart.x);
    panY = panStart.panY + (e.clientY - panStart.y);
    clampPan();
    applyTransform();
  });

  window.addEventListener("mouseup", () => {
    if (!panning) return;
    panning = false;
    container.classList.remove("is-panning");
  });

  container.addEventListener("contextmenu", (e) => {
    if (scale > 1) e.preventDefault();
  });

  container.addEventListener("dblclick", (e) => {
    e.preventDefault();
    resetZoom();
  });

  function setPinColors(colors) {
    pinColors = colors;
  }

  function setSelfId(id) {
    selfId = id;
  }

  function setObserve(mode) {
    observe = mode;
  }

  function setClickable(v) {
    clickable = v;
    container.classList.toggle("map-clickable", v && !observe);
  }

  function normFromEvent(e) {
    const rect = layer.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return { lat: Math.max(0, Math.min(1, y)), lon: Math.max(0, Math.min(1, x)) };
  }

  container.addEventListener("click", (e) => {
    if (!clickable || observe || panning) return;
    if (e.button !== 0) return;
    const { lat, lon } = normFromEvent(e);
    onPlaceGuess(lat, lon);
  });

  function clearPins() {
    Object.values(pins).forEach((el) => el.remove());
    for (const k of Object.keys(pins)) delete pins[k];
    clearLines();
  }

  function playerColor(slot) {
    return pinColors[slot % pinColors.length] || "#888";
  }

  function upsertPin(id, coord, slot, isAnswer = false) {
    if (!coord) return;
    let el = pins[id];
    if (!el) {
      el = document.createElement("div");
      layer.appendChild(el);
      pins[id] = el;
    }
    if (isAnswer) {
      el.className = "pin answer-pin";
      el.innerHTML = "";
      el.style.background = ANSWER_COLOR;
      el.style.border = "2px solid #fff";
      el.style.borderRadius = "2px";
      el.style.transform = "translate(-50%, -50%) rotate(45deg)";
    } else {
      const isSelf = id === selfId;
      const centerColor = playerColor(slot);
      el.className = `pin player-pin ${isSelf ? "pin-self" : "pin-other"}`;
      el.style.background = isSelf ? OUTER_RING_SELF : OUTER_RING_OTHER;
      el.style.border = "none";
      el.style.borderRadius = "50%";
      el.style.transform = "translate(-50%, -50%)";
      let inner = el.querySelector(".pin-inner");
      if (!inner) {
        el.innerHTML = "";
        inner = document.createElement("span");
        inner.className = "pin-inner";
        el.appendChild(inner);
      }
      inner.style.background = centerColor;
    }
    el.style.left = `${coord[1] * 100}%`;
    el.style.top = `${coord[0] * 100}%`;
  }

  function drawLines(coords, answerCoord, slots) {
    if (!overlay) return;
    overlay.innerHTML = "";
    if (!answerCoord) return;
    const entries = Object.entries(coords).filter(([, coord]) => coord);
    entries.sort(([pidA], [pidB]) => {
      if (pidA === selfId) return 1;
      if (pidB === selfId) return -1;
      return 0;
    });
    for (const [pid, coord] of entries) {
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      const color = playerColor(slots[pid] ?? 0);
      line.setAttribute("x1", coord[1] * 100);
      line.setAttribute("y1", coord[0] * 100);
      line.setAttribute("x2", answerCoord[1] * 100);
      line.setAttribute("y2", answerCoord[0] * 100);
      line.setAttribute("stroke", color);
      line.setAttribute("stroke-width", String(LINE_STROKE_WIDTH));
      line.setAttribute("stroke-linecap", "round");
      overlay.appendChild(line);
    }
  }

  function sortedPinEntries(coords) {
    const entries = Object.entries(coords).filter(([, coord]) => coord);
    entries.sort(([pidA], [pidB]) => {
      if (pidA === selfId) return 1;
      if (pidB === selfId) return -1;
      return 0;
    });
    return entries;
  }

  function render(state) {
    clearPins();
    const slots = {};
    for (const p of state.players || []) slots[p.player_id] = p.slot;

    const revealed = state.answer_revealed;
    for (const [pid, coord] of sortedPinEntries(state.coords || {})) {
      upsertPin(pid, coord, slots[pid] || 0);
    }
    if (revealed && state.answer_coord) {
      upsertPin("__answer__", state.answer_coord, 0, true);
      drawLines(state.coords || {}, state.answer_coord, slots);
    }
  }

  applyTransform();

  return {
    setPinColors,
    setSelfId,
    setObserve,
    setClickable,
    render,
    resetZoom,
  };
}
