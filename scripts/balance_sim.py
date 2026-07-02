#!/usr/bin/env python3
"""Monte Carlo calibration for HP / dmg_mult / distance_scale.

Usage:
    python scripts/balance_sim.py
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Callable, List, Sequence


@dataclass
class SimConfig:
    max_rounds: int = 16
    max_hp: float = 100.0
    distance_scale: float = 100.0
    schedule: Sequence[tuple[int, float]] = (
        (11, 1.0),
        (3, 1.5),
        (999, 2.0),
    )
    skill_mu: float = -2.1
    skill_sigma: float = 0.55
    n_players: int = 1
    mode: str = "ffa_hp"
    rank_tolerance: float = 3.0
    hp_budget_factor: float = 0.55
    trials: int = 5000


def build_mults(max_rounds: int, schedule: Sequence[tuple[int, float]]) -> List[float]:
    mults: List[float] = []
    for rounds, mult in schedule:
        mults.extend([float(mult)] * int(rounds))
    return [mults[i] if i < len(mults) else mults[-1] for i in range(max_rounds)]


def sample_distance(rng: random.Random, mu: float, sigma: float) -> float:
    return min(rng.lognormvariate(mu, sigma), math.sqrt(2))


def scaled_distance(d: float, scale: float) -> float:
    return d * scale


def rank_by_distance_no_relay(distances: dict[str, float], tolerance: float) -> dict[str, int]:
    sorted_players = sorted(distances.items(), key=lambda item: item[1])
    ranks: dict[str, int] = {}
    cluster_min: float | None = None
    for index, (player_id, distance) in enumerate(sorted_players):
        if cluster_min is None or distance - cluster_min > tolerance:
            cluster_min = distance
            current_rank = index + 1
        ranks[player_id] = current_rank
    return ranks


def damage_ffa_hp(s: float, mult: float) -> float:
    return s * mult


def damage_ranking(
    rank: int,
    n: int,
    mult: float,
    max_hp: float,
    max_rounds: int,
    hp_budget_factor: float,
) -> float:
    hp_budget = max_hp / max(hp_budget_factor * max_rounds, 1.0)
    weight = (rank - 1) / max(n - 1, 1)
    return hp_budget * weight * mult


def simulate_player(cfg: SimConfig, rng: random.Random, mults: List[float]) -> int | None:
    hp = cfg.max_hp
    death_round: int | None = None

    for r in range(cfg.max_rounds):
        if cfg.mode == "ffa_hp" or cfg.n_players == 1:
            d = sample_distance(rng, cfg.skill_mu, cfg.skill_sigma)
            s = scaled_distance(d, cfg.distance_scale)
            dmg = damage_ffa_hp(s, mults[r])
        else:
            distances = {
                f"p{i}": scaled_distance(
                    sample_distance(rng, cfg.skill_mu, cfg.skill_sigma),
                    cfg.distance_scale,
                )
                for i in range(cfg.n_players)
            }
            ranks = rank_by_distance_no_relay(distances, cfg.rank_tolerance)
            player_rank = ranks["p0"]
            dmg = damage_ranking(
                player_rank,
                cfg.n_players,
                mults[r],
                cfg.max_hp,
                cfg.max_rounds,
                cfg.hp_budget_factor,
            )

        hp -= dmg
        if hp <= 0 and death_round is None:
            death_round = r + 1

    return death_round


def death_round_percentile(cfg: SimConfig, p: float) -> float | None:
    rng = random.Random(42)
    mults = build_mults(cfg.max_rounds, cfg.schedule)
    deaths: List[int] = []
    survived = 0

    for _ in range(cfg.trials):
        death = simulate_player(cfg, rng, mults)
        if death is None:
            survived += 1
        else:
            deaths.append(death)

    if not deaths:
        return None
    deaths.sort()
    idx = int(p * (len(deaths) - 1))
    return deaths[idx]


def report(cfg: SimConfig) -> None:
    mults = build_mults(cfg.max_rounds, cfg.schedule)
    mult_sum = sum(mults)
    p50 = death_round_percentile(cfg, 0.5)
    p90 = death_round_percentile(cfg, 0.9)
    target = 0.66 * cfg.max_rounds

    print(f"mode={cfg.mode} n={cfg.n_players} scale={cfg.distance_scale}")
    print(f"  schedule={cfg.schedule} mult_sum={mult_sum:.1f} max_mult={max(mults)}")
    print(f"  P50 death round: {p50} (target ~{target:.1f})")
    print(f"  P90 death round: {p90} (want None or >{cfg.max_rounds})")
    print()


def main() -> None:
    base_schedule = ((11, 1.0), (3, 1.5), (999, 2.0))
    alt_schedule = ((11, 1.0), (3, 2.0), (999, 3.0))

    for schedule in (base_schedule, alt_schedule):
        for scale in (100.0, 85.0, 70.0):
            cfg = SimConfig(distance_scale=scale, schedule=schedule)
            report(cfg)

    print("=== ranking mode N=4 ===")
    for scale in (100.0, 85.0):
        cfg = SimConfig(
            distance_scale=scale,
            schedule=base_schedule,
            mode="ranking",
            n_players=4,
        )
        report(cfg)


if __name__ == "__main__":
    main()
