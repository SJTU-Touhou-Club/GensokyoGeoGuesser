export function renderLeaderboard(container, state, selfId) {
  container.innerHTML = "";
  const phase = state.phase;
  const pointsMode = state.game_mode === "points";
  const header = document.createElement("div");
  header.className = "lb-header";
  if (phase === "guess") {
    header.textContent = `Submitted: ${state.submitted_count} / ${state.player_count}`;
  } else {
    header.textContent = "LEADERBOARD";
  }
  container.appendChild(header);

  const list = document.createElement("div");
  list.className = "lb-list";

  const players =
    phase === "game_over"
      ? [...(state.players || [])].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
      : [...(state.players || [])].sort((a, b) =>
          pointsMode
            ? (b.score ?? 0) - (a.score ?? 0)
            : (b.hp ?? 0) - (a.hp ?? 0)
        );
  const pinColors = state.pin_colors || [];

  for (const p of players) {
    const row = document.createElement("div");
    row.className = "lb-row";
    if (p.player_id === selfId && !state.observe_mode) row.classList.add("self");

    const bar = document.createElement("span");
    bar.className = "lb-color";
    bar.style.background = pinColors[p.slot % pinColors.length] || "#888";

    const name = document.createElement("span");
    name.className = "lb-name";
    name.textContent = p.player_id;
    if (!p.connected) {
      const afk = document.createElement("span");
      afk.className = "lb-afk";
      afk.textContent = " (AFK)";
      name.appendChild(afk);
    }

    const stat = document.createElement("span");
    stat.className = pointsMode ? "lb-score" : "lb-hp";
    if (pointsMode) {
      stat.textContent = (p.score ?? 0).toFixed(1);
    } else {
      stat.textContent = (p.hp ?? 0).toFixed(1);
    }

    const extra = document.createElement("span");
    extra.className = "lb-extra";
    if (phase === "guess" && p.answered) extra.textContent = " ✓";
    if (!pointsMode && (phase === "reveal" || phase === "agree_next") && p.round_damage != null) {
      extra.textContent = ` -${p.round_damage.toFixed(1)}`;
      extra.style.color = "#c05621";
    }
    if (pointsMode && (phase === "reveal" || phase === "agree_next") && p.round_score != null) {
      extra.textContent = ` +${p.round_score.toFixed(1)}`;
      extra.style.color = "#2f855a";
    }
    if (phase === "game_over") {
      row.classList.add("lb-row-final");
      extra.textContent = `#${p.rank}`;
      extra.style.color = "#555";
      if (!pointsMode) {
        const survived = document.createElement("span");
        survived.className = "lb-survived";
        survived.textContent = `${p.rounds_survived ?? 0}r`;
        row.append(bar, name, stat, extra, survived);
      } else {
        row.append(bar, name, stat, extra);
      }
    } else {
      row.append(bar, name, stat, extra);
    }
    list.appendChild(row);
  }
  container.appendChild(list);
}
