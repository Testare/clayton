"""metronome_abilities.py — what each metronome-user ability does to THIS battle.

Metronome Compass simulates one specific fight: the user, holding a Lagging Tail so it always
moves second, calling Metronome every turn against a wild Magikarp. An ability only matters
here if it can change something that fight actually observes — which is a much smaller
question than what the ability does in general.

The registry below answers it per ability, so nothing is left permitted-but-ignored. Before
this existed, `user_ability` was never even read (clayton-2ae.1), so every ability was
silently treated as "no ability"; an unmodelled ability that DOES change the battle produced
quietly wrong paths, and a wrong path means a wrong seed, which means a wrong calibration.

THE FACTS THE "no effect" VERDICTS REST ON, all checked against the simulation itself and
pinned by tests/test_metronome_abilities.py, so a change that invalidates one fails loudly:

* Magikarp only ever uses Splash or Tackle (context.py's magikarp_move_select: Splash below
  level 15, Splash-or-Tackle at 15+). It therefore cannot inflict any status, and the only
  damage it deals is physical Normal.
* The battle state has no burn / poison / paralysis / freeze for the USER at all. The only
  user-side conditions are `user_sleep_turns`, set solely by its own Rest, and
  `user_confusion_turns` from Rampage backlash.
* The user always moves second because of the Lagging Tail, so its Speed never decides
  anything.

Support levels feed app.models: UNSUPPORTED is what blocks SELECTION in Metronome Compass.
It never blocks CREATING the user — people must still be able to record the Pokemon they own
(clayton-b42.10.2).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AbilitySupport(Enum):
    """How well the simulation handles a metronome user with this ability."""

    MODELLED = "modelled"
    """The simulation implements it. Safe to calibrate with."""

    NO_EFFECT = "no_effect"
    """It provably cannot change THIS battle, so there is nothing to implement. Safe to
    calibrate with — the simulation being silent about it is correct, not a gap."""

    UNSUPPORTED = "unsupported"
    """It WOULD change this battle and is not implemented. Blocks selection, because a
    silently-wrong path is worse than a refusal: it yields a wrong seed and a wrong model."""


@dataclass(frozen=True)
class AbilityInfo:
    name: str
    support: AbilitySupport
    reason: str

    @property
    def is_supported(self) -> bool:
        return self.support is not AbilitySupport.UNSUPPORTED


def _info(name, support, reason):
    return AbilityInfo(name=name, support=support, reason=reason)


_M, _N, _U = AbilitySupport.MODELLED, AbilitySupport.NO_EFFECT, AbilitySupport.UNSUPPORTED

# Every ability reachable from the 14 metronome-capable species (basedata/metronome_species.json).
METRONOME_ABILITIES: dict[str, AbilityInfo] = {info.name: info for info in (
    _info("Natural Cure", _N,
          "Cures status on switch out. Nothing switches during this battle, so it never "
          "fires. This is why it is the verified, recommended ability."),
    _info("Pickup", _N,
          "Gen 4 Pickup only picks up an item after the battle ends. It has no in-battle "
          "effect at all."),
    _info("Run Away", _N,
          "Guarantees escape from a wild battle. Fleeing is not part of the simulated "
          "fight, which runs a fixed number of turns."),
    _info("Quick Feet", _N,
          "Raises Speed while statused. The Lagging Tail already makes the user move second "
          "every turn, so its Speed never decides anything."),
    _info("Thick Fat", _N,
          "Halves damage taken from Fire and Ice moves. Magikarp only uses Splash or "
          "Tackle, so every hit it lands is physical Normal — there is no Fire or Ice damage "
          "to halve. Nor does the battle track HP totals, only whether the user is provably "
          "below full, which a halved hit does not change."),
    _info("Immunity", _N,
          "Prevents poison. Magikarp has no move that poisons, and the battle state carries "
          "no poison for the user to begin with."),
    _info("Synchronize", _N,
          "Passes burn / paralysis / poison back to whatever inflicted it. Magikarp can "
          "inflict none of those with Splash or Tackle, and a self-inflicted status (Rest) "
          "never triggers Synchronize."),

    _info("Serene Grace", _M,
          "Doubles every secondary-effect chance. Implemented in "
          "BattleContext.secondary_effect_chance: the threshold doubles, clamped at 100, "
          "while the roll itself is unchanged, so RNG consumption is identical and only the "
          "outcome moves. Changes roughly a fifth of paths."),
    _info("Cute Charm", _U,
          "30% chance to infatuate an attacker that makes contact, adding a conditional roll "
          "and then a per-turn immobilise roll. Not implemented (clayton-2ae.3)."),
    _info("Magic Guard", _M,
          "Prevents indirect damage, including recoil, so the user stays provably at full HP "
          "where it otherwise would not and a recovery move fails for want of anything to "
          "heal — Take Down then Milk Drink. A failed move skips the post-success advances, "
          "desyncing every later turn. Implemented in _mark_user_recoil. Note it is often "
          "masked: any Tackle Magikarp lands damages the user directly, which Magic Guard "
          "does not prevent, so it only decides anything while Magikarp has not connected — "
          "always, below level 15, where Magikarp can only Splash."),
    _info("Hustle", _U,
          "Cuts the accuracy of physical moves to 80%, changing hit/miss and therefore every "
          "roll that follows. Not implemented (clayton-2ae.8)."),
    _info("Intimidate", _M,
          "Lowers Magikarp's Attack a stage on entry. Implemented in apply_entry_ability. "
          "Currently changes no observed path: damage magnitude is invisible, and the only "
          "way a stage is observable today is the floor check in _target_stat_applier, which "
          "needs six lowering effects in one battle to reach — and which clayton-eaj says is "
          "wrong anyway. Modelled regardless, because the stage is real state that Psych Up, "
          "Power Swap and Heart Swap read and move around."),
)}


def ability_info(name: str | None) -> AbilityInfo:
    """The registry entry for `name`.

    An unknown ability is reported UNSUPPORTED rather than waved through: the whole point of
    this registry is that nothing is silently ignored, and the UI only ever offers abilities
    the chosen species actually has, so an unrecognised one means the data moved under us.
    `None` (no ability recorded) is treated as no effect, matching the historical default.
    """
    if name is None or name == "":
        return _info("", AbilitySupport.NO_EFFECT, "No ability recorded.")
    known = METRONOME_ABILITIES.get(name)
    if known is not None:
        return known
    return _info(name, AbilitySupport.UNSUPPORTED,
                 f"{name} is not in the metronome-ability registry, so its effect on this "
                 f"battle is unknown and cannot be assumed to be nothing.")


def unsupported_abilities() -> frozenset[str]:
    """Names that block selection in Metronome Compass."""
    return frozenset(n for n, i in METRONOME_ABILITIES.items()
                     if i.support is AbilitySupport.UNSUPPORTED)
