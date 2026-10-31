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

  const mapEl = container.querySelector("#map");
  const mapSizer = container.querySelector("#map-sizer");
  const mapContent = container.querySelector("#map-content");
  if (!mapEl || !mapSizer || !mapContent) {
    throw new Error("Map viewer structure is incomplete");
  }

  // Persistent scale is separate from temporary gesture state.
  const pointers = new Map();
  let pointerGesture = null;

  const viewerState = {
    scale: MIN_ZOOM,
    minScale: MIN_ZOOM,
    maxScale: MAX_ZOOM,
    baseWidth: 0,
    baseHeight: 0,
    viewportWidth: 0,
    viewportHeight: 0,
    frameId: 0,
    panFrameId: 0,
    pendingPanX: 0,
    pendingPanY: 0,
    clickUnlockAt: 0,
    cursorViewport: null,
    gesture: null,
    ready: false,
  };

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function clampScrollLeft(scrollLeft, scale = viewerState.scale) {
    const maxScroll = Math.max(
      0,
      viewerState.baseWidth * scale - viewerState.viewportWidth
    );
    return clamp(scrollLeft, 0, maxScroll);
  }

  function clampScrollTop(scrollTop, scale = viewerState.scale) {
    const maxScroll = Math.max(
      0,
      viewerState.baseHeight * scale - viewerState.viewportHeight
    );
    return clamp(scrollTop, 0, maxScroll);
  }

  function updateMapAspectRatio() {
    if (!mapEl.naturalWidth || !mapEl.naturalHeight) return;
    container.style.aspectRatio = mapEl.naturalWidth + " / " + mapEl.naturalHeight;
  }

  function applyViewerScale(scale) {
    mapSizer.style.width = viewerState.baseWidth * scale + "px";
    mapSizer.style.height = viewerState.baseHeight * scale + "px";
    mapContent.style.transform = "scale(" + scale + ")";
  }

  function syncViewerBaseSize() {
    updateMapAspectRatio();

    const nextViewportWidth = container.clientWidth;
    const nextViewportHeight = container.clientHeight;
    if (!nextViewportWidth || !nextViewportHeight) return;

    let centerRatioX = 0.5;
    let centerRatioY = 0.5;
    if (viewerState.ready) {
      const centerX = container.scrollLeft + viewerState.viewportWidth / 2;
      const centerY = container.scrollTop + viewerState.viewportHeight / 2;
      centerRatioX = clamp(
        centerX / (viewerState.baseWidth * viewerState.scale),
        0,
        1
      );
      centerRatioY = clamp(
        centerY / (viewerState.baseHeight * viewerState.scale),
        0,
        1
      );
    }

    viewerState.viewportWidth = nextViewportWidth;
    viewerState.viewportHeight = nextViewportHeight;
    viewerState.baseWidth = nextViewportWidth;
    viewerState.baseHeight = nextViewportHeight;
    mapContent.style.width = viewerState.baseWidth + "px";
    mapContent.style.height = viewerState.baseHeight + "px";
    applyViewerScale(viewerState.scale);

    if (viewerState.ready) {
      const nextScrollLeft =
        centerRatioX * viewerState.baseWidth * viewerState.scale -
        viewerState.viewportWidth / 2;
      const nextScrollTop =
        centerRatioY * viewerState.baseHeight * viewerState.scale -
        viewerState.viewportHeight / 2;
      container.scrollLeft = clampScrollLeft(nextScrollLeft);
      container.scrollTop = clampScrollTop(nextScrollTop);
    } else {
      container.scrollLeft = 0;
      container.scrollTop = 0;
    }

    viewerState.ready = true;
  }

  function getViewportPoint(clientX, clientY) {
    const rect = container.getBoundingClientRect();
    return {
      x: clamp(clientX - rect.left, 0, rect.width),
      y: clamp(clientY - rect.top, 0, rect.height),
    };
  }

  function isPointInsideViewer(clientX, clientY) {
    const rect = container.getBoundingClientRect();
    return (
      clientX >= rect.left &&
      clientX <= rect.right &&
      clientY >= rect.top &&
      clientY <= rect.bottom
    );
  }

  function getContentPointFromViewport(
    viewportX,
    viewportY,
    scale = viewerState.scale
  ) {
    return {
      x: (container.scrollLeft + viewportX) / scale,
      y: (container.scrollTop + viewportY) / scale,
    };
  }

  function getGestureViewportPoint(event, fallback) {
    if (
      Number.isFinite(event.clientX) &&
      Number.isFinite(event.clientY) &&
      isPointInsideViewer(event.clientX, event.clientY)
    ) {
      return getViewportPoint(event.clientX, event.clientY);
    }
    return (
      fallback ||
      viewerState.cursorViewport || {
        x: viewerState.viewportWidth / 2,
        y: viewerState.viewportHeight / 2,
      }
    );
  }

  function isGestureInsideViewer(event) {
    if (event.target instanceof Element && container.contains(event.target)) {
      return true;
    }
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) {
      return false;
    }
    return isPointInsideViewer(event.clientX, event.clientY);
  }

  function renderGestureFrame() {
    viewerState.frameId = 0;
    const gesture = viewerState.gesture;
    if (!gesture || !viewerState.ready) return;

    // Read native scroll before writing the new scale.
    const currentScale = viewerState.scale;
    const nextScale = clamp(
      gesture.startScale * gesture.latestScaleFactor,
      viewerState.minScale,
      viewerState.maxScale
    );
    const anchorViewportX = gesture.latestViewportX;
    const anchorViewportY = gesture.latestViewportY;
    const anchorContent = gesture.hasRendered
      ? getContentPointFromViewport(anchorViewportX, anchorViewportY, currentScale)
      : {
          x:
            gesture.startAnchorContentX +
            (container.scrollLeft - gesture.startScrollLeft) / currentScale,
          y:
            gesture.startAnchorContentY +
            (container.scrollTop - gesture.startScrollTop) / currentScale,
        };
    gesture.hasRendered = true;

    if (Math.abs(nextScale - currentScale) > 1e-4) {
      viewerState.scale = nextScale;
      applyViewerScale(nextScale);
      container.scrollLeft = clampScrollLeft(
        anchorContent.x * nextScale - anchorViewportX,
        nextScale
      );
      container.scrollTop = clampScrollTop(
        anchorContent.y * nextScale - anchorViewportY,
        nextScale
      );
    }

    if (gesture.endRequested) {
      viewerState.gesture = null;
      container.classList.remove("gesture-active");
      viewerState.clickUnlockAt = performance.now() + 160;
    }
  }

  function scheduleGestureFrame() {
    if (!viewerState.frameId) {
      viewerState.frameId = requestAnimationFrame(renderGestureFrame);
    }
  }

  function beginGesture(event) {
    if (!viewerState.ready) syncViewerBaseSize();
    if (!viewerState.ready) return;

    const anchorViewport = getGestureViewportPoint(event);
    const anchorContent = getContentPointFromViewport(
      anchorViewport.x,
      anchorViewport.y
    );
    viewerState.gesture = {
      startScale: viewerState.scale,
      startScrollLeft: container.scrollLeft,
      startScrollTop: container.scrollTop,
      startAnchorContentX: anchorContent.x,
      startAnchorContentY: anchorContent.y,
      latestScaleFactor: 1,
      latestViewportX: anchorViewport.x,
      latestViewportY: anchorViewport.y,
      hasRendered: false,
      endRequested: false,
    };
    container.classList.add("gesture-active");
  }

  function updateGesture(event) {
    const gesture = viewerState.gesture;
    if (!gesture) return;

    const anchorViewport = getGestureViewportPoint(event, {
      x: gesture.latestViewportX,
      y: gesture.latestViewportY,
    });
    gesture.latestScaleFactor = Number.isFinite(event.scale) ? event.scale : 1;
    gesture.latestViewportX = anchorViewport.x;
    gesture.latestViewportY = anchorViewport.y;
    scheduleGestureFrame();
  }

  function endGesture(event) {
    const gesture = viewerState.gesture;
    if (!gesture) return;

    if (Number.isFinite(event.scale)) gesture.latestScaleFactor = event.scale;
    const anchorViewport = getGestureViewportPoint(event, {
      x: gesture.latestViewportX,
      y: gesture.latestViewportY,
    });
    gesture.latestViewportX = anchorViewport.x;
    gesture.latestViewportY = anchorViewport.y;
    gesture.endRequested = true;
    scheduleGestureFrame();
  }

  function renderDiagonalPanFrame() {
    viewerState.panFrameId = 0;
    const deltaX = viewerState.pendingPanX;
    const deltaY = viewerState.pendingPanY;
    viewerState.pendingPanX = 0;
    viewerState.pendingPanY = 0;

    if (!deltaX && !deltaY) return;
    container.scrollLeft = clampScrollLeft(container.scrollLeft + deltaX);
    container.scrollTop = clampScrollTop(container.scrollTop + deltaY);
  }

  function scheduleDiagonalPanFrame() {
    if (!viewerState.panFrameId) {
      viewerState.panFrameId = requestAnimationFrame(renderDiagonalPanFrame);
    }
  }

  function wheelDeltaInPixels(event) {
    if (event.deltaMode === 1) {
      return { x: event.deltaX * 16, y: event.deltaY * 16 };
    }
    if (event.deltaMode === 2) {
      return {
        x: event.deltaX * viewerState.viewportWidth,
        y: event.deltaY * viewerState.viewportHeight,
      };
    }
    return { x: event.deltaX, y: event.deltaY };
  }

  function zoomAt(viewportPoint, nextScale) {
    const anchor = getContentPointFromViewport(viewportPoint.x, viewportPoint.y);
    viewerState.scale = clamp(nextScale, viewerState.minScale, viewerState.maxScale);
    applyViewerScale(viewerState.scale);
    container.scrollLeft = clampScrollLeft(anchor.x * viewerState.scale - viewportPoint.x);
    container.scrollTop = clampScrollTop(anchor.y * viewerState.scale - viewportPoint.y);
  }

  function handleWheel(event) {
    if (!viewerState.ready) return;
    const delta = wheelDeltaInPixels(event);
    if (!Number.isFinite(delta.x) || !Number.isFinite(delta.y)) return;
    event.preventDefault();
    // Safari can emit wheel events alongside its native pinch gestures.
    if (viewerState.gesture || pointers.size) return;

    // Discrete wheel steps zoom; smooth trackpad scrolling pans in both axes.
    const discreteWheel = event.deltaMode !== 0 ||
      (event.deltaX === 0 && Number.isInteger(event.deltaY) && Math.abs(event.deltaY) >= 40);
    if (event.ctrlKey || discreteWheel) {
      zoomAt(
        getViewportPoint(event.clientX, event.clientY),
        viewerState.scale * Math.exp(-delta.y * (event.ctrlKey ? 0.01 : 0.002))
      );
    } else {
      viewerState.pendingPanX += delta.x;
      viewerState.pendingPanY += delta.y;
      scheduleDiagonalPanFrame();
    }
  }

  function handleWindowGesture(event) {
    // Touch pointers handle mobile pinch; native gestures handle Safari trackpads.
    if (pointers.size) return;
    if (event.type === "gesturestart") {
      if (!isGestureInsideViewer(event)) return;
      event.preventDefault();
      beginGesture(event);
      return;
    }
    if (!viewerState.gesture) return;
    event.preventDefault();
    if (event.type === "gesturechange") {
      updateGesture(event);
    } else {
      endGesture(event);
    }
  }

  function pointerPosition() {
    const points = Array.from(pointers.values());
    const first = points[0];
    const second = points[1] || first;
    return {
      x: (first.x + second.x) / 2,
      y: (first.y + second.y) / 2,
      distance: points.length > 1 ? Math.hypot(first.x - second.x, first.y - second.y) : 0,
    };
  }

  function resetPointerGesture() {
    if (!pointers.size) {
      pointerGesture = null;
      container.classList.remove("gesture-active");
      return;
    }
    const point = pointerPosition();
    pointerGesture = {
      ...point,
      scale: viewerState.scale,
      anchor: getContentPointFromViewport(point.x, point.y),
      scrollLeft: container.scrollLeft,
      scrollTop: container.scrollTop,
      moved: pointerGesture?.moved || pointers.size > 1,
    };
    if (pointerGesture.moved) viewerState.clickUnlockAt = Infinity;
  }

  container.addEventListener("pointerdown", (event) => {
    if (!viewerState.ready || (event.pointerType === "mouse" && event.button !== 0 && event.button !== 2)) return;
    if (viewerState.gesture) {
      if (viewerState.frameId) cancelAnimationFrame(viewerState.frameId);
      viewerState.frameId = 0;
      viewerState.gesture = null;
    }
    pointers.set(event.pointerId, getViewportPoint(event.clientX, event.clientY));
    container.setPointerCapture(event.pointerId);
    resetPointerGesture();
  });

  container.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return;
    pointers.set(event.pointerId, getViewportPoint(event.clientX, event.clientY));
    const point = pointerPosition();
    const dx = point.x - pointerGesture.x;
    const dy = point.y - pointerGesture.y;
    if (!pointerGesture.moved && Math.hypot(dx, dy) < 4) return;
    pointerGesture.moved = true;
    viewerState.clickUnlockAt = Infinity;
    container.classList.add("gesture-active");
    if (pointers.size > 1 && pointerGesture.distance > 0) {
      viewerState.scale = clamp(
        pointerGesture.scale * point.distance / pointerGesture.distance,
        viewerState.minScale, viewerState.maxScale
      );
      applyViewerScale(viewerState.scale);
      container.scrollLeft = clampScrollLeft(pointerGesture.anchor.x * viewerState.scale - point.x);
      container.scrollTop = clampScrollTop(pointerGesture.anchor.y * viewerState.scale - point.y);
    } else {
      container.scrollLeft = clampScrollLeft(pointerGesture.scrollLeft - dx);
      container.scrollTop = clampScrollTop(pointerGesture.scrollTop - dy);
    }
  });

  function endPointer(event) {
    if (!pointers.has(event.pointerId)) return;
    if (pointerGesture.moved || event.type !== "pointerup") {
      viewerState.clickUnlockAt = performance.now() + 160;
    }
    pointers.delete(event.pointerId);
    resetPointerGesture();
  }

  container.addEventListener("pointerup", endPointer);
  container.addEventListener("pointercancel", endPointer);
  container.addEventListener("lostpointercapture", endPointer);
  container.addEventListener("contextmenu", (event) => event.preventDefault());

  function recordViewerCursor(event) {
    if (isPointInsideViewer(event.clientX, event.clientY)) {
      viewerState.cursorViewport = getViewportPoint(event.clientX, event.clientY);
    }
  }

  function clearLines() {
    if (overlay) overlay.innerHTML = "";
  }

  function setPinColors(colors) {
    pinColors = colors;
  }

  function setSelfId(id) {
    selfId = id;
  }

  function setObserve(mode) {
    observe = mode;
  }

  function setClickable(value) {
    clickable = value;
    container.classList.toggle("map-clickable", value && !observe);
  }

  function normFromEvent(event) {
    const viewportPoint = getViewportPoint(event.clientX, event.clientY);
    const contentPoint = getContentPointFromViewport(
      viewportPoint.x,
      viewportPoint.y
    );
    return {
      lat: clamp(contentPoint.y / viewerState.baseHeight, 0, 1),
      lon: clamp(contentPoint.x / viewerState.baseWidth, 0, 1),
    };
  }

  container.addEventListener("click", (event) => {
    if (
      !viewerState.ready ||
      !clickable ||
      observe ||
      viewerState.gesture ||
      pointers.size ||
      performance.now() < viewerState.clickUnlockAt
    ) {
      return;
    }
    if (event.button !== 0) return;
    const { lat, lon } = normFromEvent(event);
    onPlaceGuess(lat, lon);
  });

  function clearPins() {
    Object.values(pins).forEach((el) => el.remove());
    for (const key of Object.keys(pins)) delete pins[key];
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
      mapContent.appendChild(el);
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
      el.className = "pin player-pin " + (isSelf ? "pin-self" : "pin-other");
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
      inner.style.background = playerColor(slot);
    }
    el.style.left = coord[1] * 100 + "%";
    el.style.top = coord[0] * 100 + "%";
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
    for (const player of state.players || []) {
      slots[player.player_id] = player.slot;
    }

    for (const [pid, coord] of sortedPinEntries(state.coords || {})) {
      upsertPin(pid, coord, slots[pid] || 0);
    }
    if (state.answer_revealed && state.answer_coord) {
      upsertPin("__answer__", state.answer_coord, 0, true);
      drawLines(state.coords || {}, state.answer_coord, slots);
    }
  }

  mapEl.addEventListener("load", syncViewerBaseSize);
  if (mapEl.complete) syncViewerBaseSize();
  window.addEventListener("resize", syncViewerBaseSize);
  container.addEventListener("mousemove", recordViewerCursor, { passive: true });
  container.addEventListener("wheel", handleWheel, { passive: false });
  window.addEventListener("gesturestart", handleWindowGesture, {
    passive: false,
    capture: true,
  });
  window.addEventListener("gesturechange", handleWindowGesture, {
    passive: false,
    capture: true,
  });
  window.addEventListener("gestureend", handleWindowGesture, {
    passive: false,
    capture: true,
  });

  syncViewerBaseSize();

  return {
    setPinColors,
    setSelfId,
    setObserve,
    setClickable,
    render,
  };
}
