"""
chart.py — Target seed charting tool.

Given a Pokemon and a strategy, evaluates seeds derived from candidate
datetimes to find optimal target times. Aggregates per-seed capture
probability across neighboring frames and ranks results so the player
knows the best datetime to aim for.
"""
import logging
from typing import Callable
from claytonlib.safari import SafariContext, SafariPokemon, SafariStep

logger = logging.getLogger(__name__)


class Strategy:
    def __init__(self, name: str, fn: Callable[[SafariContext], SafariStep]):
        self.name = name
        self._fn = fn

    def take_action(self, ctx: SafariContext) -> None:
        result = self._fn(ctx)
        logger.debug("turn[%d] strategy[%s] %s", ctx.turn_count, self.name, result.name)


class SuccessCriteria:
    def __init__(self, name: str, fn: Callable[[SafariContext], bool]):
        self.name = name
        self._fn = fn

    def met(self, ctx: SafariContext) -> bool:
        result = self._fn(ctx)
        logger.debug("turn[%d] criteria[%s] %s", ctx.turn_count, self.name, result)
        return result


STRATEGY_ONLY_BALLS = Strategy(
    "Only balls",
    lambda ctx: ctx.throw_ball()
)

STRATEGY_ONE_MUD = Strategy(
    "One mud then balls",
    lambda ctx: ctx.throw_mud() if ctx.turn_count == 0 else ctx.throw_ball()
)

STRATEGY_SIX_BAIT = Strategy(
    "Six bait then balls",
    lambda ctx: ctx.throw_bait() if ctx.turn_count < 6 else ctx.throw_ball()
)

CRITERIA_CAPTURE = SuccessCriteria(
    "Capture",
    lambda ctx: ctx.captured()
)

CRITERIA_WONT_FLEE_10_TURNS = SuccessCriteria(
    "Survived 10 turns without fleeing",
    lambda ctx: ctx.turn_count >= 10 and ctx.is_watching()
)

def evaluate_seed(seed: int, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> bool:
    ctx = SafariContext.start_encounter(seed, pokemon)
    while ctx.is_watching():
        strategy.take_action(ctx)
        if criteria.met(ctx):
            return True
    return False


CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS = SuccessCriteria(
    "Capture via machete after 3 balls",
    lambda ctx: True  # TODO: implement
)
