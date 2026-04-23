from enum import Enum
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
import json
import logging
import math

logger = logging.getLogger(__name__)


def advance_rng(rng_state: int) -> int:
    return ((rng_state * 1103515245) + 24691) & 0xFFFF_FFFF


class SafariStep(Enum):
    BAIT = 'b'
    BAIT_CRITICAL = 'B'
    MUD = 'm'
    MUD_CRITICAL = 'M'
    BALL_0 = '0'
    BALL_1 = '1'
    BALL_2 = '2'
    BALL_3 = '3'
    CAPTURED = 'C'
    FLED = 'F'

    @classmethod
    def from_char(cls, ch: str) -> 'SafariStep':
        for member in cls:
            if member.value == ch:
                return member
        raise ValueError(f"No SafariStep with character {ch!r}")


class SafariContextState(Enum):
    WATCHING_WONT_FLEE = 0
    WATCHING_WILL_FLEE = 1
    FLED = 2
    CAPTURED = 3


# Indexed by stage (-6 to 6).
STAGE_MULTIPLIERS: list[Fraction] = [
    Fraction(10, 10),  #  0
    Fraction(15, 10),  #  1
    Fraction(20, 10),  #  2
    Fraction(25, 10),  #  3
    Fraction(30, 10),  #  4
    Fraction(35, 10),  #  5
    Fraction(40, 10),  #  6
    Fraction(10, 40),  # -6
    Fraction(10, 35),  # -5
    Fraction(10, 30),  # -4
    Fraction(10, 25),  # -3
    Fraction(10, 20),  # -2
    Fraction(10, 15),  # -1
]


@dataclass(frozen=True)
class SafariPokemon:
    name: str
    base_catch_rate: int
    base_flee_rate: int
    adjusted_flee_rates: tuple[int, ...] = field(init=False)
    adjusted_catch_rates_b: tuple[int, ...] = field(init=False)

    def __adjusted_catch_rate_b(self, stage_modifier: int):
        species_mod = math.floor(STAGE_MULTIPLIERS[stage_modifier] * self.base_catch_rate)
        a = math.floor(math.floor(species_mod * 1.5) / 2)
        b_div = math.floor(math.sqrt(math.floor(math.sqrt(0xFF0000 / max(a, 1)))))
        return math.floor(0xFFFF0 / b_div)

    def __post_init__(self):
        object.__setattr__(self, 'adjusted_flee_rates', tuple(
            min(255, math.floor(STAGE_MULTIPLIERS[i] * self.base_flee_rate))
            for i in range(0, 13)
        ))
        object.__setattr__(self, 'adjusted_catch_rates_b', tuple(
            self.__adjusted_catch_rate_b(i)
            for i in range(0, 13)
        ))


@dataclass
class SafariContext:
    pokemon: SafariPokemon
    rng_state: int
    flee_rate_stages: int = 0
    capture_rate_stages: int = 0
    turn_count: int = 0
    balls_remaining: int = 30
    state: SafariContextState = field(default=SafariContextState.WATCHING_WONT_FLEE)

    def is_watching(self) -> bool:
        return self.state in (SafariContextState.WATCHING_WONT_FLEE, SafariContextState.WATCHING_WILL_FLEE)

    def has_fled(self) -> bool:
        return self.state == SafariContextState.FLED

    def captured(self) -> bool:
        return self.state == SafariContextState.CAPTURED

    def will_flee(self) -> bool:
        return self.state == SafariContextState.WATCHING_WILL_FLEE

    def __advance(self) -> int:
        self.rng_state = advance_rng(self.rng_state)
        return self.rng_state >> 16

    def __flee_check(self):
        match self.state:
            case SafariContextState.WATCHING_WONT_FLEE:
                rng = self.__advance() % 255;
                flee_rate = self.pokemon.adjusted_flee_rates[self.flee_rate_stages]
                if rng <= flee_rate:
                    self.state = SafariContextState.WATCHING_WILL_FLEE
            case SafariContextState.WATCHING_WILL_FLEE:
                self.state = SafariContextState.FLED
            case _:
                raise Exception("Cannot run flee check, pokemon has fled or been captured")

    def throw_bait(self) -> SafariStep:
        if not self.is_watching():
            raise Exception("Cannot throw bait, pokemon has fled or been captured")
        self.turn_count += 1
        # Before turn/Quick claw advances (4)
        self.__advance()
        self.__advance()
        self.__advance()
        self.__advance()
        critical = self.__advance() % 10 == 0
        if not critical:
            self.capture_rate_stages = max(-6, self.capture_rate_stages - 1)
        self.flee_rate_stages = max(-6, self.flee_rate_stages - 1)
        # Ability advances (2)
        self.__advance()
        self.__advance()
        self.__flee_check()
        result = SafariStep.BAIT_CRITICAL if critical else SafariStep.BAIT
        logger.debug("rng[0x%08X] throw_bait", self.rng_state)
        return result

    def throw_mud(self) -> SafariStep:
        if not self.is_watching():
            raise Exception("Cannot throw mud, pokemon has fled or been captured")
        self.turn_count += 1
        # Before turn/Quick claw advances (4)
        self.__advance()
        self.__advance()
        self.__advance()
        self.__advance()
        critical = self.__advance() % 10 == 0
        if not critical:
            self.flee_rate_stages = min(6, self.flee_rate_stages + 1)
        self.capture_rate_stages = min(6, self.capture_rate_stages + 1)
        # Ability advances (2)
        self.__advance()
        self.__advance()
        self.__flee_check()
        result = SafariStep.MUD_CRITICAL if critical else SafariStep.MUD
        logger.debug("rng[0x%08X] throw_mud", self.rng_state)
        return result

    def throw_ball(self) -> SafariStep:
        if not self.is_watching():
            raise Exception("Cannot throw ball, pokemon has fled or been captured")
        self.turn_count += 1
        # Before turn/Quick claw advances (4)
        self.__advance()
        self.__advance()
        self.__advance()
        self.__advance()
        shakes = 0
        b = self.pokemon.adjusted_catch_rates_b[self.capture_rate_stages]
        for _ in range(4):
            if self.__advance() >= b:
                break
            shakes += 1

        self.balls_remaining -= 1

        if shakes == 4:
            self.state = SafariContextState.CAPTURED
            result = SafariStep.CAPTURED
        elif self.balls_remaining == 0:
            self.state = SafariContextState.FLED
            result = [SafariStep.BALL_0, SafariStep.BALL_1, SafariStep.BALL_2, SafariStep.BALL_3][shakes]
        else:
            # Ability advances (2)
            self.__advance()
            self.__advance()
            self.__flee_check()
            result = [SafariStep.BALL_0, SafariStep.BALL_1, SafariStep.BALL_2, SafariStep.BALL_3][shakes]
        logger.debug("rng[0x%08X] throw_ball", self.rng_state)
        return result

    @classmethod
    def start_encounter(cls, seed: int, pokemon: SafariPokemon) -> 'SafariContext':
        ctx = cls(pokemon=pokemon, rng_state=seed)
        # "bellShimmerGraphics" advances (4)
        ctx.__advance()
        ctx.__advance()
        ctx.__advance()
        ctx.__advance()
        # Ability advances (2)
        ctx.__advance()
        ctx.__advance()
        ctx.__flee_check()
        logger.debug("rng[0x%08X] start_encounter", ctx.rng_state)
        return ctx


_safari_pokemon: dict[str, SafariPokemon] | None = None

def safari_pokemon_by_name(name: str) -> SafariPokemon:
    global _safari_pokemon
    if _safari_pokemon is None:
        path = Path(__file__).parent.parent / "safari_pokemon.json"
        with open(path) as f:
            data = json.load(f)
        _safari_pokemon = {n: SafariPokemon(n, entry["catch_rate"], entry["flee_rate"]) for n, entry in data.items()}
    return _safari_pokemon[name]
