from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from neo.config import get_config, is_debug
from neo.game import database as db
from neo.game.database import Phase
from neo.scoring.rank import assign_score_ranks, assign_standings_ranks
from neo.settlement.mode import get_game_mode


def build_state(
    room_id: str,
    player_id: str,
    observe_mode: bool = False,
) -> Dict[str, Any]:
    room = db.get_room(room_id)
    cfg = get_config()
    max_rounds = cfg["rounds"]["max_rounds"]
    game_mode = get_game_mode()

    question = db.get_current_question(room_id)
    answer_coord = db.loc_db.get(question.location)
    if answer_coord is None:
        answer_coord = (0.5, 0.5)

    answer_loc = {
        "name": question.location,
        "lat": answer_coord[0],
        "lon": answer_coord[1],
    }

    now = time.time()
    phase_deadline: Optional[float] = None
    if room.phase == Phase.GUESS:
        timeout = cfg["timeouts"]["place_guess"]
        remaining = timeout - (now - room.phase_started_at)
        phase_deadline = room.phase_started_at + timeout
    elif room.phase == Phase.AGREE_NEXT:
        timeout = cfg["timeouts"]["agree_next"]
        remaining = timeout - (now - room.phase_started_at)
        phase_deadline = room.phase_started_at + timeout
    else:
        remaining = 0
    remaining = max(0, int(remaining))

    revealed = room.phase in (
        Phase.REVEAL,
        Phase.AGREE_NEXT,
        Phase.GAME_OVER,
    )

    coords = _filter_coords(room, player_id, revealed, observe_mode)
    show_answer = revealed or room.phase == Phase.GAME_OVER

    players = _build_players(room, revealed, game_mode)
    submitted_count = sum(1 for pid in room.player_ids if room.player_answered.get(pid))

    return {
        "state_version": room.state_version,
        "game_mode": game_mode,
        "phase": room.phase.value,
        "phase_remaining_seconds": remaining,
        "phase_deadline": phase_deadline,
        "round": room.round_index + 1,
        "total_rounds": max_rounds,
        "dmg_mult": db.get_dmg_mult(room_id),
        "self_player_id": player_id,
        "player_count": len(room.player_ids),
        "submitted_count": submitted_count,
        "observe_mode": observe_mode,
        "players": players,
        "coords": coords,
        "answer_revealed": show_answer,
        "answer_coord": list(answer_coord) if show_answer else None,
        "answer_loc": answer_loc if show_answer else None,
        "question_img": question.image_path,
        "question_comment": question.comment,
        "rankings": room.rankings,
        "has_next": db.has_next_round(room_id),
        "has_prev": db.has_prev_round(room_id),
        "debug": is_debug(),
        "debug_log": room.debug_log if is_debug() else [],
        "pin_colors": cfg.get("pin_colors", []),
    }


def _filter_coords(
    room,
    player_id: str,
    revealed: bool,
    observe_mode: bool,
) -> Dict[str, List[float]]:
    result: Dict[str, List[float]] = {}
    if revealed:
        for pid in room.player_ids:
            c = room.player_coord.get(pid)
            if c is not None:
                result[pid] = [c[0], c[1]]
    elif not observe_mode and player_id in room.player_ids:
        c = room.player_coord.get(player_id)
        if c is not None:
            result[player_id] = [c[0], c[1]]
    return result


def _build_players(room, revealed: bool, game_mode: str) -> List[dict]:
    tie_threshold = get_config()["scoring"].get("tie_threshold", 0.1)
    entries = []
    for pid in room.player_ids:
        entry = {
            "player_id": pid,
            "slot": room.player_slot.get(pid, 0),
            "answered": room.player_answered.get(pid, False),
            "ready_next": room.player_ready_next.get(pid, False),
            "connected": room.player_connected.get(pid, True),
        }
        if game_mode == "points":
            entry["score"] = room.player_score.get(pid, 0)
            entry["round_score"] = (
                room.player_round_score.get(pid) if revealed else None
            )
            entry["hp"] = None
            entry["round_damage"] = None
            entry["rounds_survived"] = None
        else:
            entry["hp"] = room.player_hp.get(pid, 0)
            entry["rounds_survived"] = room.rounds_survived.get(pid, 0)
            entry["round_damage"] = (
                room.player_round_damage.get(pid) if revealed else None
            )
            entry["score"] = None
            entry["round_score"] = None
        entries.append(entry)

    if game_mode == "points":
        return assign_score_ranks(entries, tie_threshold)
    return assign_standings_ranks(entries, tie_threshold)
