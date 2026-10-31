import { createSyncedCountdown } from "./countdown.js";

const TIMED_PHASES = new Set(["guess", "agree_next"]);

export function createHud(els, scheduler, selfId, observe) {
  const phaseCountdown = createSyncedCountdown({
    onTick: (left) => {
      if (els.countdown) els.countdown.textContent = formatTime(left);
    },
  });

  function formatTime(s) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  els.submitBtn?.addEventListener("click", async () => {
    if (observe) return;
    els.submitBtn.disabled = true;
    try {
      const phase = els.submitBtn.dataset.phase;
      if (phase === "guess") await scheduler.postAction("/api/submit");
      else if (phase === "agree_next") await scheduler.postAction("/api/agree_next");
    } catch (e) {
      els.submitBtn.disabled = false;
    }
  });

  function update(state) {
    if (els.roundCurrent) els.roundCurrent.textContent = state.round;
    if (els.roundMax) els.roundMax.textContent = state.total_rounds;
    if (els.dmgMult) els.dmgMult.textContent = `${state.dmg_mult}x`;
    if (els.multLabel) {
      els.multLabel.textContent =
        state.game_mode === "points" ? "Score Multiplier" : "Damage Multiplier";
    }

    if (TIMED_PHASES.has(state.phase)) {
      phaseCountdown.sync({
        remainingSeconds: state.phase_remaining_seconds,
        deadline: state.phase_deadline,
      });
    } else {
      phaseCountdown.stop();
      if (els.countdown) els.countdown.textContent = "--:--";
    }

    const btn = els.submitBtn;
    if (!btn) return;
    if (observe) {
      btn.style.display = "none";
      return;
    }
    btn.style.display = "";

    const me = (state.players || []).find((p) => p.player_id === selfId);
    if (state.phase === "guess") {
      btn.textContent = "Submit";
      btn.dataset.phase = "guess";
      const hasCoord = !!(state.coords && state.coords[selfId]);
      btn.disabled = !me || me.answered || !hasCoord;
      btn.style.display = me?.answered ? "" : "";
    } else if (state.phase === "agree_next") {
      btn.textContent = "Next";
      btn.dataset.phase = "agree_next";
      btn.disabled = !me || me.ready_next;
      btn.style.display = "";
    } else {
      btn.style.display = "none";
    }
  }

  return { update };
}
