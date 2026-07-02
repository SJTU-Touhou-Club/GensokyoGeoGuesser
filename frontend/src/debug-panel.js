export function createDebugPanel(panel, logEl) {
  let paused = false;
  const seenLogs = new Set();

  function log(line) {
    if (!logEl) return;
    const div = document.createElement("div");
    div.textContent = line;
    logEl.appendChild(div);
    while (logEl.children.length > 200) logEl.removeChild(logEl.firstChild);
    if (!paused) logEl.scrollTop = logEl.scrollHeight;
  }

  panel?.querySelector(".debug-toggle")?.addEventListener("click", () => {
    panel.classList.toggle("collapsed");
  });

  panel?.querySelector("#debug-pause")?.addEventListener("click", () => {
    paused = !paused;
  });

  function update(state) {
    if (!panel) return;
    panel.style.display = state.debug ? "block" : "none";
    for (const entry of state.debug_log || []) {
      const key = `${entry.time}-${entry.message}`;
      if (seenLogs.has(key)) continue;
      seenLogs.add(key);
      const t = new Date(entry.time * 1000).toLocaleTimeString();
      log(`[${t}] ${entry.level}: ${entry.message}`);
    }
  }

  return { log, update };
}
