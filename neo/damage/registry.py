"""Backward-compatible re-exports; prefer neo.settlement.damage.registry."""
from neo.settlement.context import SettlementContext as DamageContext
from neo.settlement.damage.registry import ffa as ffa_hp
from neo.settlement.damage.registry import get_damage_fn, ranking

__all__ = ["DamageContext", "ffa_hp", "get_damage_fn", "ranking"]
