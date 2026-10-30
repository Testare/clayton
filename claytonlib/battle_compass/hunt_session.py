"""One Battle Compass run, from the first turn to the capture.

The layer the app drives.  ``identify.Session`` narrows candidates and ``solver.solve`` steers
the RNG; this joins them into something with a single surface: take a snapshot, show it, accept
one reported turn, repeat.  Nothing here is interactive and nothing blocks -- the caller owns the
prompting, which is what lets the same object back a desktop UI, a test, and a replay of a
recorded battle.

Two design choices worth stating, because both differ from how the older tools work.

**Undo is replay, not rollback.**  The session keeps the candidate window and the list of
observations, and rewinding means rebuilding from the window and replaying one fewer turn.  No
``BattleState`` is ever snapshotted or mutated backwards.  Exact by construction, and cheap: a
few hundred candidates over a handful of turns.

**Phase 2 follows a cached plan and re-solves only on divergence.**  Sec 15.4.2 asked for two
undo operations -- rewind a misreport, but accept a *misplay* and re-solve, because the game has
already advanced and cannot be rewound.  The plan cache collapses those into one path: a misplay
diverges from the plan, which re-solves, and a misplay is then simply the next turn's starting
state.

It re-solved *unconditionally* at first, which was cheap (~0.2s) and still wrong twice over.  The
search collapses RNG offsets, so it is a heuristic over arrival order and two solves from
equivalent states can return different equally-priced paths -- the plan visibly changed under the
player turn to turn.  And a transient refusal threw away a plan that was still good, which is how
a woken target (clayton-agh.1) turned "here is your next move" into "there is no solution".

Keeping the suffix costs nothing, and for a reason rather than by luck: Dijkstra returns a
shortest path, and the suffix of a shortest path is a shortest path from the state it continues
at.  The licence is the exact token match -- the reported turn being identical to the plan's own
prediction is precisely the statement that we are in the state the plan continues from.  See
`HuntSession._follow_plan`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from claytonlib.battle.damage import (
    WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN, Attacker, Defender, damage_range,
    unsupported_reason,
)
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass import items
from claytonlib.battle_compass.candidates import CandidateWindow
from claytonlib.battle_compass.identify import AdviceAborted, Phase, Session
from claytonlib.battle_compass.sim import (
    ABILITY_BAD_DREAMS, EFFECT_FORESIGHT, EFFECT_NIGHTMARE, EFFECT_TAUNT, FLINCH_EFFECTS,
    HuntConfig,
    SLEEP_DURATION_MIN,
    SLEEP_DURATION_SPAN, _effective_accuracy, accuracy_net_stage, bad_dreams_tick, burn_tick,
    can_flinch, can_inflict, can_miss, could_vanish_before_us, deals_nothing,
    is_semi_invulnerable, pending_future_sight, starts_charge_turn,
    effective_speed, immune_to_status, nightmare_tick, primary_stat_drop, secondary_description,
    secondary_status,
    simulate_turn,
    status_applied_by, unselectable_reason, variable_base_power, weather_of,
    will_fail,
)
from claytonlib.battle_compass.solver import (
    Solution, SolverConfig, Unreachable, danger_floor_for, solve,
)
from claytonlib.battle_compass.state import Action, Battler, Status
from claytonlib.moves import CATEGORY_STATUS, resolve_move

#: How many candidate rows a snapshot carries. The full set can be 1,200 wide; the UI shows the
#: nearest few and a count, and the window is sorted centre-first so these are the likeliest.
CANDIDATE_PREVIEW = 12


def _item_name(code: str) -> str:
    """An item code as its name, for plain-language rendering. Falls back to the code."""
    try:
        return f"a {items.item(code).name}"
    except ValueError:
        return code


def _party_namer(state):
    """A lookup from party slot to Pokemon name, for plain-language rendering.

    Built off the state being described rather than held on the session, so a history row
    replayed from before a switch names the Pokemon who was in that slot then -- which, because
    slots are stable, is the same Pokemon either way. That is the point of making them stable.
    """
    by_slot = {state.ours.party_slot or 1: state.ours.name}
    for i, b in enumerate(state.bench):
        by_slot.setdefault(b.party_slot or i + 2, b.name)
    return by_slot.get


def reachable_weathers(target: Battler) -> tuple[str, ...]:
    """The weathers this target can put up, including none.

    Read off the moveset rather than off the current field, because `worst_incoming_hit` has to
    answer "what is the worst this battle can do to us" before any of it has happened.
    """
    from claytonlib.battle_compass.sim import EFFECT_RAIN_DANCE

    out = [WEATHER_NONE]
    for slot in range(len(target.moves)):
        move = target.move(slot)
        if move is not None and move.effect == EFFECT_RAIN_DANCE:
            out.append(WEATHER_RAIN)
            break
    return tuple(out)


def reachable_attack_stages(target: Battler) -> tuple[int, ...]:
    """Every Attack / Sp. Atk stage this target can reach, from its current one upward.

    The stage half of the same argument `reachable_weathers` already makes. A floor computed at
    the stages the target holds *now* is not a floor at all against a target holding Ancient
    Power, whose 10% secondary raises **every** stat: against Ampharos Lv93 a Sacred Fire crit is
    178-210 at +0 and 264-312 at +1, so a floor of 210 reports "safe" about a hit that kills.

    `readiness.speed_checks` has taken a `target_speed_stages` tuple for this reason since
    Ancient Power was modelled; this is the offensive side of it, and the two should agree about
    which moveset can boost.

    Downward stages are deliberately NOT enumerated: a crit discards the attacker's lowered
    Attack, so an Intimidated target still crits at full power and the floor must not fall below
    the current stage's crit. What Intimidate and Charm lower is the figure at the CURRENT stage,
    which is read straight off the Battler.

    **Two families of booster count, not one.** It used to ask only about Ancient Power's
    all-stats secondary, so Azelf's Nasty Plot went unseen -- and that one is worse than Ancient
    Power's in every respect: it is +2 rather than +1, it is a primary effect rather than a 10%
    secondary, and it raises the stat Azelf actually attacks off. At +2 its Swift roughly doubles,
    which is the difference between a party member surviving the chip phase and not.
    """
    from claytonlib.battle_compass.sim import (
        EFFECT_ALL_STATS_UP, PRIMARY_SELF_RAISES, STAT_STAGE_CEILING,
    )

    #: The two offensive stages. A self-raise of either is a booster here; Amnesia's Sp. Def and
    #: Double Team's evasion are not, because neither changes what the target DEALS -- they
    #: belong to `reachable_defensive_drops`'s question and to accuracy's respectively.
    offensive = ("atk_stage", "spatk_stage")
    boosts = any(
        (m := target.move(slot)) is not None
        and (m.effect == EFFECT_ALL_STATS_UP
             or any(field in offensive
                    for field, _ in PRIMARY_SELF_RAISES.get(m.effect) or ()))
        for slot in range(len(target.moves)))
    start = max(target.atk_stage, target.spatk_stage)
    if not boosts:
        return (start,)
    return tuple(range(start, STAT_STAGE_CEILING + 1))


#: `worst_incoming_hit` memo. Keyed on everything the figure depends on and nothing else, so two
#: states that differ only in RNG offset or PP share an entry.
#:
#: It exists because the floor moved from "once per session" to "per state"
#: (clayton-957.10.5) and `_legal_actions` asks for it at every node of a Dijkstra. Uncached that
#: is a nested loop over moves x weathers x stages x 16 rolls per node, which took the test suite
#: from ~50s to over two minutes on its own.
_WORST_HIT_CACHE: dict[tuple, int] = {}


def _worst_hit_key(ours: Battler, target: Battler, field) -> tuple:
    """Everything `worst_incoming_hit` reads, so the memo cannot serve a stale answer.

    **The weather belongs here**, and did not until clayton-5rz. It was safe to leave out only
    because the figure enumerated every reachable weather and so never looked at the field's --
    the moment the live figure started reading it, the first call cached its answer for every
    later one, and a rained-on state got the clear-weather number back. Caught by a test that
    asked both questions of the same state.
    """
    return (
        ours.stats["def"], ours.stats["spd"], ours.types,
        # OUR defensive stages, which the figure reads and the key used not to. A memo keyed
        # without them served the stage-0 answer for the rest of the run after one Metal Sound.
        ours.def_stage, ours.spdef_stage,
        target.level, target.stats["atk"], target.stats["spa"], target.types,
        target.ability, target.held_item, target.moves,
        target.atk_stage, target.spatk_stage,
        getattr(field, "reflect_turns", 0) > 0,
        getattr(field, "light_screen_turns", 0) > 0,
        weather_of(field),
    )


def survivability_warnings(party: "list[Battler]", target: Battler) -> list[str]:
    """Which party members cannot survive the target's worst hit, and under what conditions.

    The honest version of what `clayton-957.10.1` asked for. The danger floor is a *gate*: below
    it, the solver heals instead of playing. When the floor exceeds a Pokemon's max HP that gate
    can never open and the run reads as "Unreachable" for reasons that have nothing to do with
    capture windows -- so the answer is to say so BEFORE the encounter, in a sentence naming the
    move, rather than to let the search fail opaquely.

    Three tiers, because they call for different decisions:

    * **nothing survives it even now** -- a Sacred Fire crit is 573 against Smeargle's 153, and no
      amount of levelling closes that. This is a risk to accept knowingly, not a bug to fix.
    * **nothing survives it once the target has boosted** -- Ampharos takes 210 at +0 and 312 at
      +1, so one Ancient Power proc is the difference. Actionable: one more level closes it.
    * **safe at every stage** -- no warning.

    Advisory in all three cases. A Pokemon that cannot survive the worst hit is still the right
    one to bring most turns, because the worst hit needs a 1/4 move choice and a 1/16 crit, and
    `Flash` can cut the hit chance to a third on top of that.

    **Kept to one line each.** These are read on every readiness check, and the reasoning behind
    them belongs here rather than in the panel -- a warning that takes a paragraph to make its
    point trains the reader to skip the whole section, which costs more than the detail adds.
    What the solver does with a lethal hit is explained in `solver._legal_actions`.
    """
    out: list[str] = []
    ban = _sleep_ban_warning(target)
    if ban:
        out.append(ban)
    for mon in party:
        if not mon.stats:
            continue
        clock = _sleep_clock_warning(mon, target, party)
        if clock:
            out.append(clock)
        else:
            # Only when the sleep is not already the worse warning. A Darkrai sleep that kills
            # outright does not also need "and it costs you turns".
            cost = _sleep_turn_cost_warning(mon, target, party)
            if cost:
                out.append(cost)
        # `any_reachable_weather` on BOTH, because this is pre-hunt advice: the question is
        # "what can this battle ever do to me", and a Lugia that has not used Rain Dance yet
        # certainly will. The live indicator is the one that reads the current field
        # (`HuntSession.danger_floor`) -- see `worst_incoming_hit` for why those differ.
        now = worst_incoming_hit(mon, target, any_reachable_weather=True)
        boosted = worst_incoming_hit(mon, target, any_reachable_stage=True,
                                     any_reachable_weather=True)
        move = _worst_move_name(mon, target)
        if now >= mon.max_hp:
            out.append(
                f"{mon.name} ({mon.max_hp} HP) dies to a {move}, up to {now}. The "
                f"solver avoids lethal turns but cannot heal out of range.")
        elif boosted >= mon.max_hp:
            out.append(
                f"{mon.name} ({mon.max_hp} HP) survives a {move} at {now} now, but "
                f"{boosted} once the target has worked on you.")
    return out


#: The most turns a sleep can cost. A rolled duration of d leaves the sleeper acting on the turn
#: the counter reaches 1, so it loses d-1 turns -- and the residuals tick at the end of each of
#: those and not on the waking turn, whose status check has already cleared the sleep.
MAX_SLEEP_RESIDUAL_TURNS = SLEEP_DURATION_MIN + SLEEP_DURATION_SPAN - 2


def _sleep_clock_warning(mon: Battler, target: Battler,
                         party: "list[Battler] | None" = None) -> str:
    """Whether falling asleep is lethal to `mon`, as a sentence, or "".

    **A different shape of danger from every other warning here, and the reason this function
    exists at all.** The tiers above all ask "can one hit kill this", which is the only question
    a target without sleep can pose. Darkrai poses another: Hypnosis costs no HP, and then
    Nightmare takes a quarter of max HP and Bad Dreams an eighth at the end of every sleeping
    turn -- 37.5% a turn, so a four-turn sleep kills ANY party member outright, whatever its HP
    and whatever it would have survived as a hit. A warning table that only priced hits would
    call that party safe.

    Reported in turns rather than in HP because turns are what the player can act on: it says
    how much of a 2-5 turn sleep is survivable, which is the same thing as how many turns of
    healing the plan has to have in it.

    Reads the target's own ability and moveset rather than taking flags, so a target that has
    one mechanism and not the other (a sleep move but no Bad Dreams, or the reverse) gets a
    figure that is actually its own.

    **And it reads OUR ability too**, which it did not: a Noctowl cannot be put to sleep at all,
    so "keep it awake or heal every turn" was advice about a state it can never enter. Noticed
    because `_sleep_turn_cost_warning` is silent for the same Pokemon for the same reason, and
    the two sitting in one list would have contradicted each other.
    """
    if not can_inflict(target, Status.SLEEP):
        return ""
    if immune_to_status(mon, Status.SLEEP):
        return ""
    has_nightmare = any(
        (move := resolve_move(name)) is not None and move.effect == EFFECT_NIGHTMARE
        for name in target.moves)
    asleep = replace(mon, status=Status.SLEEP, sleep_turns=MAX_SLEEP_RESIDUAL_TURNS + 1,
                     nightmare=has_nightmare)
    per_turn = (nightmare_tick(asleep)
                + bad_dreams_tick(asleep, opponent_has_bad_dreams=_has_bad_dreams(target)))
    if per_turn <= 0:
        return ""
    survivable = (mon.max_hp - 1) // per_turn        # turns it can take and still be standing
    sources = " and ".join(
        [s for s in ("Nightmare" if has_nightmare else "",
                     "Bad Dreams" if _has_bad_dreams(target) else "") if s])
    # The holder's OWN figure, not the generic one: an Early Bird sleeper loses at most two turns,
    # so quoting four at it overstated the danger twofold (`max_sleep_turns_lost`).
    worst = max_sleep_turns_lost(mon)
    if survivable >= worst:
        return ""
    answer = _sleep_answer(party or [], mon)
    return (
        f"{mon.name} ({mon.max_hp} HP) loses {per_turn} a turn to {sources} while asleep, so it "
        f"survives {survivable} of a sleep that can last {worst}."
        + (answer if answer else " Keep it awake or heal every turn."))


def max_sleep_turns_lost(mon: Battler) -> int:
    """The most turns a sleep can cost `mon`, reading its OWN ability.

    `MAX_SLEEP_RESIDUAL_TURNS` is the figure for an ordinary Pokemon: a rolled duration of d
    leaves the sleeper acting on the turn the counter reaches 1, so it loses d-1 turns and the
    worst roll of 5 costs 4.

    **Early Bird halves it**, and the warnings were quoting the ordinary figure at an Early Bird
    holder. The counter drops by TWO (`state.SLEEP_DECREMENT_EARLY_BIRD`), so working the four
    rolls through `Battler.tick_sleep`: d=2 costs nothing at all, d=3 and d=4 cost one turn, and
    d=5 costs two. So the worst case is two, and telling a Xatu it "survives 2 of a sleep that
    can last 4" overstated the danger by a factor of two -- which for a residual that is priced
    per turn is the difference between "bring a healer" and "this is fine".
    """
    if mon.has_early_bird:
        return MAX_SLEEP_RESIDUAL_TURNS // 2
    return MAX_SLEEP_RESIDUAL_TURNS


def _sleep_answer(party: "list[Battler]", exclude: Battler) -> str:
    """"Honchkrow (Insomnia) is immune to it" for the first party member that is, or "".

    The one POSITIVE sentence in this table, and it replaces advice the player may already have
    taken. "Insomnia or Vital Spirit refuses it" is useful to somebody picking a party and useless
    to somebody who has picked one and brought the carrier -- what they need then is which
    Pokemon it is, so they can lead with it or switch to it when the sleep move comes out.

    `exclude` is the Pokemon the warning is ABOUT, so a Noctowl is never offered as its own
    answer. It cannot be, in practice -- an immune Pokemon produces no warning to append this to
    -- but the filter is here rather than relied upon, because the two callers reach it by
    different routes and only one of them has already checked.

    First match rather than a list: this is appended to a one-line warning, and naming three
    candidates would turn it into the paragraph `survivability_warnings` is explicitly not.
    Early Bird is named separately and last, because it HALVES the sleep rather than refusing it,
    and a reader who stops after the first clause should not come away thinking it is immune.
    """
    from claytonlib.battle_compass.sim import SLEEP_BLOCKING_ABILITIES

    def named(mon: Battler) -> str:
        return (mon.ability or "").strip().title()

    immune = next((mon for mon in party
                   if mon is not exclude and mon.stats
                   and (mon.ability or "").strip().lower() in SLEEP_BLOCKING_ABILITIES), None)
    if immune is not None:
        return (f" {immune.name} ({named(immune)}) is immune to it \u2014 lead with it or switch "
                f"when the move comes out.")
    early = next((mon for mon in party
                  if mon is not exclude and mon.stats and mon.has_early_bird), None)
    if early is not None:
        return (f" {early.name}'s Early Bird halves the counter, so it loses at most "
                f"{MAX_SLEEP_RESIDUAL_TURNS // 2}.")
    return ""


def _sleep_turn_cost_warning(mon: Battler, target: Battler,
                             party: "list[Battler] | None" = None) -> str:
    """Whether this target can cost `mon` turns by sleeping it, as a sentence, or "".

    The third shape of danger in this table, after "one hit kills" and "the sleep itself kills".
    Uxie poses it: there is no Nightmare and no Bad Dreams, so a sleep costs no HP at all and
    `_sleep_clock_warning` correctly says nothing -- but it costs **turns**, and Phase 2 runs a
    precomputed path, so a turn lost is a plan re-solved. A table that priced only HP called that
    free.

    Named in turns, and it names the three abilities that change the figure, because that is the
    only part a player can act on before the encounter: Insomnia and Vital Spirit refuse the
    sleep outright (`sim.SLEEP_BLOCKING_ABILITIES`), and Early Bird halves the counter, so a
    rolled 2 costs no turn at all (`state.SLEEP_DECREMENT_EARLY_BIRD`).

    Silent for a Pokemon that already has one of them, and silent for a target that cannot sleep
    us -- which for Uxie means Yawn, so `can_inflict` had to learn about it first.
    """
    from claytonlib.battle_compass.sim import SLEEP_BLOCKING_ABILITIES

    if not can_inflict(target, Status.SLEEP):
        return ""
    ability = (mon.ability or "").strip().lower()
    if ability in SLEEP_BLOCKING_ABILITIES:
        return ""
    if mon.has_early_bird:
        # Halved rather than refused, so it is still a cost -- but two turns against a target that
        # does no residual damage is not worth a line on every readiness check, and saying so
        # would crowd out the warnings that are.
        return ""
    answer = _sleep_answer(party or [], mon)
    return (
        f"{target.name} can put {mon.name} to sleep for up to {max_sleep_turns_lost(mon)} turns, "
        f"and nothing it holds resists that. The cost is turns rather than HP, so the plan "
        f"re-solves each time."
        + (answer if answer
           else " Insomnia or Vital Spirit refuses it; Early Bird halves it."))


def _sleep_ban_warning(target: Battler) -> str:
    """Whether this target can REFUSE to be slept, as a sentence, or "".

    About the target rather than about any one party member, which is why it is appended once
    instead of per Pokemon. Azelf is the case and Uproar is the mechanism: while it runs -- 3 to
    6 turns, and it re-picks it roughly one turn in four -- no sleep move of ours can land at all
    (`sim.will_fail`), and anything already asleep is woken. So a plan that uses SLEEP as its
    holding status is not merely risky against this target; the game refuses it.

    The counter is worth saying in the same breath, because it is cheap and total: Uproar is one
    of the twelve sound moves, so a Soundproof party member blanks the move whole -- damage, lock
    and ban together (`sim.soundproofed`).
    """
    from claytonlib.battle_compass.sim import EFFECT_UPROAR

    banner = next((move.name for slot in range(len(target.moves))
                   if (move := target.move(slot)) is not None
                   and move.effect == EFFECT_UPROAR), None)
    if banner is None:
        return ""
    return (
        f"{target.name}'s {banner} forbids sleep for 3-6 turns at a time and wakes anything "
        f"already asleep, so paralysis is the only holding status this target reliably allows. A "
        f"Soundproof party member blocks {banner} outright, lock and all.")


def _has_bad_dreams(target: Battler) -> bool:
    """Read off the target's own ability, which the facade now sets from the encounter row."""
    return (target.ability or "").strip().lower() == ABILITY_BAD_DREAMS


def banked_hit(move) -> bool:
    """Whether this move's damage is BANKED rather than dealt on the turn it is used.

    Future Sight, and it is the whole of the family. Pricing one as an ordinary hit overstates it
    by a factor of three against a neutral defender -- 2x for a critical it can never take, and
    1.5x for a STAB it never gets -- which is not a conservative error in a figure the solver uses
    as its heal threshold: it is a floor above every party member's max HP, so `in_danger` is
    permanently true and no plan can ever be reached (the shape of clayton-957.10.1's collapse).

    Both halves come from `BtlCmd_TryFutureSight`: it passes a critical multiplier of 1, and its
    effect script sets `SYSCTL_IGNORE_IMMUNITIES` so that `CheckTypeChart` -- which holds STAB,
    effectiveness and Levitate alike -- is skipped. See `sim._future_sight_damage`.

    Our Light Screen is the one modifier that DOES apply, and it is not a free discount either:
    with no crit to discard it, the halving is real, and `_worst_hit_key` already keys the memo
    on whether a screen is up.
    """
    from claytonlib.battle_compass.sim import EFFECT_FUTURE_SIGHT

    return move.effect == EFFECT_FUTURE_SIGHT


def _worst_move_name(ours: Battler, target: Battler) -> str:
    """Which of the target's moves produces `worst_incoming_hit`, for the warning text.

    **Named with its weather when the weather is what makes it worst.** `worst_incoming_hit`
    maximises over every weather the target can SET, so against Lugia the figure comes from a
    Hydro Pump under its own Rain Dance -- 172 against Smeargle, where a clear-weather one is 116
    and survivable. Reporting it as "a critical Hydro Pump" left no way to tell which of those
    two numbers the warning meant, and they call for different decisions: one is a reason to
    train, the other is a reason to not be out while it is raining.
    """
    from claytonlib.battle.damage import unsupported_reason
    from claytonlib.battle_compass.sim import variable_base_power

    best, name, worst_weather = -1, "critical hit", WEATHER_NONE
    defender = Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                        types=ours.types)
    for slot in range(len(target.moves)):
        move = target.move(slot)
        if move is None:
            continue
        base_power = variable_base_power(move, ours)
        if unsupported_reason(move, power_known=base_power is not None) is not None:
            continue
        attacker = Attacker(level=target.level, attack=target.stats["atk"],
                            special_attack=target.stats["spa"], types=target.types,
                            attack_stage=target.atk_stage,
                            special_attack_stage=target.spatk_stage,
                            ability=target.ability, held_item=target.held_item)
        banked = banked_hit(move)
        for weather in reachable_weathers(target):
            _, high = damage_range(move, attacker, defender, critical=not banked,
                                   weather=weather, base_power=base_power,
                                   type_chart=not banked)
            if high > best:
                # The word "critical" travels WITH the move rather than sitting in the warning
                # template, because it is not true of all of them: a Future Sight cannot crit, so
                # "dies to a critical Future Sight" named a hit that does not exist and quoted a
                # number three times too big.
                best, worst_weather = high, weather
                name = move.name if banked else f"critical {move.name}"
    if worst_weather == WEATHER_RAIN:
        return f"{name} in its own rain"
    if worst_weather == WEATHER_SUN:
        return f"{name} in its own sun"
    return name


#: Field conditions worth showing, as ``(state attribute, label, whose it is)``. Ordered by how
#: much each one changes play rather than alphabetically: weather first because it scales damage,
#: then the things that block an action outright, then the merely-defensive.
#:
#: "whose" is the side the condition belongs to, which matters for reading it: Mist and Safeguard
#: are the TARGET's and work against us, while Reflect and Light Screen are ours.
FIELD_CONDITIONS: tuple[tuple[str, str, str], ...] = (
    # First, because it is the only one of these that will take HP off us on a turn we can name.
    # A pending Future Sight is incoming damage already decided -- banked when the move was used,
    # so nothing we do between now and then changes the number -- and the player has no other way
    # to know it is coming: the turn that set it rendered as a bare `E3` with no hit marker.
    ("future_sight_turns", "Future Sight", "target"),
    ("rain_turns", "Rain", "field"),
    ("safeguard_turns", "Safeguard", "target"),
    # Ours, which a Wobbuffet trapper raises on the roamer plan. A separate row rather than one
    # ambiguous "Safeguard": the two block opposite things -- the target's refuses OUR sleep move,
    # and ours refuses a status the TARGET would inflict -- so a banner that could not say whose
    # it was would be worse than no banner.
    ("our_safeguard_turns", "Safeguard", "ours"),
    ("mist_turns", "Mist", "target"),
    # Mesprit's. Worth a row for the same reason Mist has one: it silently changes what a damaging
    # move of ours can do -- no crits while it is up -- and the turn that set it rendered as a bare
    # `E2` with nothing to show the player why their False Swipes stopped critting.
    ("target_lucky_chant_turns", "Lucky Chant", "target"),
    ("reflect_turns", "Reflect", "ours"),
    ("light_screen_turns", "Light Screen", "ours"),
)

#: The same, for conditions that are on or off rather than counted down.
FIELD_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("target_trapped", "Trapped", "target"),
    ("target_water_sport", "Water Sport", "target"),
)

#: Counters that live on a BATTLER rather than on the state, and still belong in this banner.
#:
#: ``(side, attribute, label)``. Sleep is the counter that does NOT appear here -- both sides
#: already render a status chip for it, so a second row would report it twice. These two have no
#: chip and no other way of being seen, and each one changes what the next turn can be:
#:
#: * **Uproar** is the target refusing to pick a move. While it runs it spends no selection roll,
#:   it attacks every turn, and no sleep move of ours can land at all -- so "3 turns of Uproar
#:   left" is also "3 turns before paralysis is your only option again".
#: * **Taunt** is the mirror of Uproar and ours to inflict: while it runs the target cannot select
#:   a move with no power at all, so the counter says how many more turns its Yawn, Amnesia,
#:   Nasty Plot or Metal Sound stays shut -- and when the modulus widens back out.
#: * **Drowsy** is a Yawn already landed. The sleep is not avoidable by anything except switching
#:   the Pokemon out, and a player who cannot see the counter finds out by losing a turn.
BATTLER_CONDITIONS: tuple[tuple[str, str, str], ...] = (
    ("target", "uproar_turns", "Uproar"),
    # Next to Uproar because they answer the same question -- what can the target pick next turn
    # -- from opposite directions. A Taunt we landed narrows it to the damaging moves, so the
    # remaining turns are exactly how long the status half of its moveset stays shut.
    ("target", "taunted_turns", "Taunt"),
    ("ours", "taunted_turns", "Taunt"),
    # Heal Block, which the target lands on us. In the banner because nothing else shows it and
    # because what it gates is invisible until you try: a Rest or Roost wall simply refuses to
    # heal for five turns. It blocks no ITEM, so the panel must not imply the bag is shut.
    ("ours", "heal_block_turns", "Heal Block"),
    ("target", "heal_block_turns", "Heal Block"),
    ("ours", "drowsy_turns", "Drowsy"),
    ("target", "drowsy_turns", "Drowsy"),
)


#: Battler-level flags that belong in the banner -- the mirror of `FIELD_FLAGS`, which holds the
#: state-level ones, and of `BATTLER_CONDITIONS`, which holds the battler-level *counters*.
#:
#: ``(side, attribute, label)``. One entry, and it earns the table: **Identified** is what makes a
#: Ghost target catchable, and it is invisible otherwise. The game announces it once ("Smeargle
#: identified Giratina!") and then never mentions it again, while every False Swipe afterwards
#: depends on it -- so a player who misses the message, or comes back to a run an hour later, has
#: no way to tell whether the chip phase will work. Both sides are listed because `act_target`
#: can set it on us, even though no configured encounter has the move.
BATTLER_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("target", "identified", "Identified"),
    ("ours", "identified", "Identified"),
    # Shaymin's Leech Seed. A flag with no counter, so it renders without a number -- and it is
    # the one condition in this banner that costs HP every turn on one side and GIVES it on the
    # other, which is exactly why a player needs to see it rather than infer it from the HP
    # dropping. Both sides listed for the usual symmetry; only ours is reachable, since no party
    # move has effect 84.
    ("ours", "seeded", "Leech Seed"),
    ("target", "seeded", "Leech Seed"),
)


def field_conditions(state) -> list[dict]:
    """What is currently up, newest-relevant first: ``{name, turns, whose}``.

    `turns` is None for a flag that does not count down, so the page can render "Trapped"
    without a number rather than inventing one. Only ACTIVE conditions are returned -- a banner
    listing six "inactive" rows is a banner nobody reads.

    Sleep is deliberately not here even though it is a counter: it belongs to a Pokemon rather
    than the field, and both sides already render their own status chip. Putting it in a field
    banner would report it twice and in the wrong place. Uproar and Drowsy are counters on a
    Pokemon too and ARE here, because neither has a chip -- see `BATTLER_CONDITIONS`.
    """
    out: list[dict] = []
    for attr, label, whose in FIELD_CONDITIONS:
        turns = getattr(state, attr, 0) or 0
        if turns > 0:
            out.append({"name": label, "turns": turns, "whose": whose})
    for side, attr, label in BATTLER_CONDITIONS:
        turns = getattr(getattr(state, side, None), attr, 0) or 0
        if turns > 0:
            out.append({"name": label, "turns": turns, "whose": side})
    for attr, label, whose in FIELD_FLAGS:
        if getattr(state, attr, False):
            out.append({"name": label, "turns": None, "whose": whose})
    for side, attr, label in BATTLER_FLAGS:
        if getattr(getattr(state, side, None), attr, False):
            out.append({"name": label, "turns": None, "whose": side})
    # Vanished, which is COMPUTED rather than stored -- `is_semi_invulnerable` reads the charging
    # slot and the move in it, so there is no field for `BATTLER_FLAGS` to name. Handled here
    # rather than given a field of its own, because a second copy of that state could drift from
    # the one `execute_move` reads.
    #
    # In the banner because the player asked for it and because it is the condition hardest to
    # keep in your head: it lasts exactly one turn, it is announced once ("Giratina vanished
    # instantly!"), and while it is up it changes both what the target can pick and whether your
    # move can reach it. Both sides are listed; only the target can reach it today.
    for side in ("target", "ours"):
        battler = getattr(state, side, None)
        if battler is not None and is_semi_invulnerable(battler):
            out.append({"name": "Vanished", "turns": None, "whose": side})
    return out


def _action_from_tokens(tokens: list[str]) -> tuple[Action, dict]:
    """``(action, kwargs)`` for `HuntSession.observe`, read off a turn's first token.

    The slot-bearing actions carry their argument in the same token, so a switch is ``S3`` and a
    revive ``R2``, and those have to be handed to `observe` separately.

    **Scanned rather than read off token zero**, because a turn does not always lead with our
    half. When the target moves first and faints us we never acted, so the turn is ``E3!X3`` --
    their hit, then our faint and replacement. Taking the first token called that "not one of our
    actions" and refused a turn the grammar explicitly allows.

    `Ic` before `I` matters: the prefixes are matched longest-first, or a cure would read as a
    plain item and the turn would be simulated with the wrong one. Same for `X` being tried after
    the moves, since nothing else starts with it.
    """
    if not tokens:
        raise ValueError("empty turn")
    ours = [Action.ITEM_CURE, Action.ITEM, Action.MOVE_1, Action.MOVE_2, Action.MOVE_3,
            Action.MOVE_4, Action.CAPTURE_BALL, Action.STANDARD_BALL, Action.SWITCH,
            Action.REVIVE, Action.FAINTED]
    first = next((t for t in tokens
                  if any(t.startswith(a.value) for a in ours)), None)
    if first is None:
        raise ValueError(f"no action of ours in {tokens}")
    for action in (Action.ITEM_CURE, Action.ITEM):
        if first.startswith(action.value):
            # The item CODE follows the prefix (`Ihp`, `Ifr`), and an `I` on its own is an
            # unspecified item -- legal in the grammar, so it must not be forced to a code here.
            code = first[len(action.value):] or None
            return action, ({"item_code": code} if code else {})
    for action in (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4,
                   Action.CAPTURE_BALL, Action.STANDARD_BALL):
        if first.startswith(action.value):
            return action, {}
    for action in (Action.SWITCH, Action.REVIVE):
        if first.startswith(action.value):
            digits = "".join(c for c in first[len(action.value):] if c.isdigit())
            if not digits:
                raise ValueError(f"{first!r} names no party slot")
            # `observe` takes a BENCH index for a switch and a PARTY SLOT for a revive, which is
            # the one asymmetry here; `replacement` is the party slot a faint switched in.
            key = "bench_slot" if action is Action.SWITCH else "replacement"
            return action, {key: int(digits)}
    if first.startswith(Action.FAINTED.value):
        digits = "".join(c for c in first[len(Action.FAINTED.value):] if c.isdigit())
        return Action.FAINTED, ({"replacement": int(digits)} if digits else {})
    raise ValueError(f"{first!r} is not one of our actions")


def reachable_defensive_drops(ours: Battler, target: Battler) -> tuple[int, int]:
    """The ``(def_stage, spdef_stage)`` worth pricing OUR side at, given what the target can do.

    The defensive mirror of `reachable_attack_stages`, and it closes the same hole on the other
    side: a floor computed at the stages we hold *now* is not a floor at all against a target
    that lowers them. Heatran is the case that forced it -- Metal Sound takes **two** Sp. Def
    stages at a time, and at -2 its Lava Plume one-shots a full-HP Smeargle where at 0 it does
    not. Latios's Luster Purge has had the same shape for longer, one stage at a time.

    Only the EXTREME is returned rather than every stage between, because the damage is monotone
    in each: a lower defence can only mean a bigger hit. And only downward, for the reason
    `reachable_attack_stages` gives for only going upward -- a crit discards a stage that would
    reduce its damage, so our raised defences cannot lower the floor and our lowered ones must
    raise it.

    Reads the target's moveset for drops aimed at `def` and `spd` specifically. The other three
    stages change what we DEAL, not what we take, so they belong to a different question.
    """
    from claytonlib.battle_compass.sim import (
        PRIMARY_STAT_DROPS, SECONDARY_STAT_DROPS, STAT_STAGE_FLOOR,
    )

    fields = set()
    for slot in range(len(target.moves)):
        move = target.move(slot)
        if move is None:
            continue
        for table in (PRIMARY_STAT_DROPS, SECONDARY_STAT_DROPS):
            # Every pair, not the first: a two-stat drop (Tickle) touches two stages, and reading
            # only `[0]` would have priced us at the wrong floor for the second one.
            for field, _ in table.get(move.effect) or ():
                if field in ("def_stage", "spdef_stage"):
                    fields.add(field)
    return (STAT_STAGE_FLOOR if "def_stage" in fields else ours.def_stage,
            STAT_STAGE_FLOOR if "spdef_stage" in fields else ours.spdef_stage)


def worst_incoming_hit(ours: Battler, target: Battler, *, field=None,
                       any_reachable_stage: bool = False,
                       any_reachable_weather: bool = False) -> int:
    """The largest single hit the target can land: max roll, critical, over all its moves.

    The solver's `danger_floor` -- heal at or below this and no single hit can faint us, without
    needing to know which move is coming (sec 11.2). Critical, because a crit ignores any stat
    change that would reduce the damage, so a Sp. Def boost cannot be relied on.

    **Weather comes from `field` unless `any_reachable_weather` asks otherwise**, and that
    default is a correction. This used to enumerate every weather the target could SET regardless
    of the field, justified as "the target can put it up on the turn it attacks, so there is no
    state in which we could have observed it first."

    That is not true. The target selects ONE move per turn: pick Rain Dance and it deals no
    damage, pick Hydro Pump and the weather is whatever was already up. So the weather at the
    start of a turn is fully observable -- exactly like the Ancient Power stat boost the old
    docstring contrasted it against, and the asymmetry it drew was unjustified. A Lv54 Magneton
    at 122/134 was reported in range of a single hit in clear weather, where Lugia's worst crit
    is 92 and only reaches 136 once it is raining (clayton-5rz).

    So there are two questions and they get two answers:

    * **What can hit me this turn** -- the default, read off `field`. This is what a live
      indicator must use, or it cries wolf for the whole run.
    * **What can this battle ever do to me** -- `any_reachable_weather=True`, which keeps the
      solver's heal decision conservative and is what the pre-hunt advice wants.

    `any_reachable_stage` is the same split for the target's Attack stages, and was already
    right; see the comment on `stages` below.
    """
    key = (_worst_hit_key(ours, target, field)
           + (any_reachable_stage, any_reachable_weather))
    cached = _WORST_HIT_CACHE.get(key)
    if cached is not None:
        return cached

    worst = 0
    # **Our own defensive stages are part of this**, and were missing. The figure was computed at
    # stage 0 whatever had been done to us, so every hit after a drop was under-predicted -- and
    # this figure IS the solver's heal threshold, so under-predicting it is how a run faints at a
    # number the plan called safe.
    #
    # Latios's Luster Purge has been able to drop our Sp. Def for as long as it has been a
    # configured target; `act_target` was fixed to apply the drop (clayton-957.26.1) while the
    # floor went on ignoring it. Heatran is what made it acute: Metal Sound is TWO stages at
    # once, and at -2 its Lava Plume one-shots a full-HP Smeargle (clayton-6xu.6).
    #
    # A crit ignores stages that would REDUCE its damage and respects those that raise it, which
    # is exactly the asymmetry we want here -- and `damage` already enforces it, so passing the
    # stages is safe for the critical hit this function measures.
    # `any_reachable_stage` means "every stage this battle can reach", and it used to look only
    # at the target's offensive ones -- so the question it answers was half-asked. Ours are the
    # other half, and against Heatran they are the bigger half.
    def_stage, spdef_stage = (reachable_defensive_drops(ours, target) if any_reachable_stage
                              else (ours.def_stage, ours.spdef_stage))
    defender = Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                        types=ours.types, defence_stage=def_stage,
                        special_defence_stage=spdef_stage)
    weathers = (reachable_weathers(target) if any_reachable_weather
                else (weather_of(field),))
    # **The target's CURRENT stages by default, not every stage it could ever reach.**
    #
    # Enumerating upward to +6 is the honest answer to "what is the worst this battle can ever
    # do", and it is the wrong question for a floor. Against Ampharos it returns 2274 -- a Sacred
    # Fire crit at +6 Atk -- which exceeds every party member's max HP and so makes `in_danger`
    # permanently true. That is clayton-957.10.1's collapse, made worse rather than fixed.
    #
    # What makes the current stage sufficient is the thing this change bought: the floor is now
    # recomputed per state. If Ancient Power procs, the stage is in the state on the next turn and
    # the floor moves with it -- so the model observes the boost instead of pre-paying for it. The
    # solver re-solves when a turn diverges, which is exactly when that happens.
    #
    # The enumeration still matters, as ADVICE: `readiness_warnings` asks with
    # `any_reachable_stage=True` to say "nothing in your party survives a Sacred Fire crit once
    # Ancient Power has boosted" before the run, which is a sentence the player can act on and a
    # gate they cannot.
    stages = (reachable_attack_stages(target) if any_reachable_stage
              else (max(target.atk_stage, target.spatk_stage),))
    # Our screens halve the hit, so a floor that ignored them would keep us healing to a number
    # far above what we need. They are skipped on a crit, which `damage` enforces -- so against
    # the crit this loop is measuring, a screen changes nothing and passing it is harmless
    # bookkeeping rather than an unsafe discount.
    reflect = getattr(field, "reflect_turns", 0) > 0
    light_screen = getattr(field, "light_screen_turns", 0) > 0
    for slot in range(len(target.moves)):
        move = target.move(slot)
        if move is None:
            continue
        # Punishment's power comes from OUR positive stages, so it has to be computed rather
        # than read -- and skipping it, as "no fixed base power" used to make us do, left one of
        # the target's attacks out of the floor entirely.
        #
        # Computed at the stages we hold NOW. An X Sp. Def later adds 20 power to it, and the
        # floor is only taken once per session, so this under-reports for a run that buffs.
        # Flagged on clayton-957.8 rather than papered over.
        base_power = variable_base_power(move, ours)
        if unsupported_reason(move, power_known=base_power is not None) is not None:
            continue
        for weather in weathers:
            for stage in stages:
                attacker = Attacker(
                    level=target.level, attack=target.stats["atk"],
                    special_attack=target.stats["spa"], types=target.types,
                    attack_stage=stage, special_attack_stage=stage,
                    ability=target.ability, held_item=target.held_item)
                # A banked hit takes neither the crit nor the type chart -- see `banked_hit`,
                # which is also why the warning text stops calling it "critical".
                banked = banked_hit(move)
                _, high = damage_range(move, attacker, defender, critical=not banked,
                                       weather=weather,
                                       base_power=base_power, reflect=reflect,
                                       light_screen=light_screen, type_chart=not banked)
                worst = max(worst, high)
    _WORST_HIT_CACHE[key] = worst
    return worst


#: Move slot -> Action, so slot order and token numbering cannot drift apart.
_MOVE_ACTIONS = (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4)


#: Status -> the marker that prevents a move because of it.
_PREVENTED_BY_STATUS = {Status.PARALYSIS: "par", Status.SLEEP: "slp", Status.FREEZE: "frz"}


def prevention_options(actor: Battler, other: Battler, *, actor_moves_first: bool) -> list[dict]:
    """What could legitimately have stopped `actor` from moving THIS turn.

    Derived from state rather than offered as a fixed menu. An unparalyzed Magneton cannot be
    fully paralyzed, and nothing in Suicune's moveset can make it flinch, so offering either as a
    possible outcome invites a report that no candidate could ever have predicted -- which looks
    exactly like a wrong model constant.

    Flinching needs the *other* side to move first, since a flinch is inflicted by a hit that has
    already landed.
    """
    options: list[dict] = []
    marker = _PREVENTED_BY_STATUS.get(actor.status)
    if marker:
        options.append({"code": marker, "label": {
            "par": "was fully paralyzed", "slp": "is asleep",
            "frz": "is frozen solid"}[marker]})
    if actor.confused:
        options.append({"code": "cfz", "label": "hurt itself in confusion"})
    if not actor_moves_first and can_flinch(other):
        options.append({"code": "fln", "label": "flinched"})
    return options


def flee_options(state, config) -> list[dict]:
    """The two roamer outcomes, when this turn could have produced one.

    Offered the same way `prevention_options` offers a paralysis: **only when the state allows
    it**. A roamer that was trapped at ACTION SELECTION never chose to escape, so offering "it
    fled" there invites a report no candidate can predict -- which looks exactly like a wrong
    model constant rather than like a mis-click.

    Both are offered together whenever it was untrapped, because the player can tell them apart
    off the screen ("The wild X fled!" against "The wild X can't escape!") and the simulator
    decides which one each candidate predicted. They are prevention-shaped -- no move happened --
    so they ride in the same list and the page's ``"E" + code`` assembly renders them without
    knowing they exist.

    Returns ``[]`` for a static target, which cannot leave at all.
    """
    from claytonlib.battle_compass.sim import roamer_trapped_at_selection

    if not getattr(config, "target_is_roamer", False):
        return []
    if roamer_trapped_at_selection(state):
        return []
    return [
        {"code": tok.ESCAPED, "label": "fled — the run is over"},
        {"code": tok.ESCAPE_FAILED, "label": "tried to flee and couldn't"},
    ]


def resolution_options(actor: Battler) -> list[dict]:
    """Status changes that let the move through and so must be reported explicitly.

    Only confusion: for sleep and freeze the move happening at all proves the status ended, but a
    confused Pokemon can attack perfectly normally (sec 13.4).
    """
    if actor.confused:
        return [{"code": "scfz", "label": "snapped out of confusion"}]
    return []


#: The seven stages a `Battler` carries, in the order a player reads a summary screen plus the
#: two that have no stat behind them. Named here so the snapshot and the page agree on order.
STAGE_FIELDS: tuple[tuple[str, str], ...] = (
    ("atk", "atk_stage"), ("def", "def_stage"), ("spa", "spatk_stage"),
    ("spd", "spdef_stage"), ("spe", "speed_stage"),
    ("accuracy", "accuracy_stage"), ("evasion", "evasion_stage"),
)


def stat_stages(battler: Battler) -> dict[str, int]:
    """Every non-neutral stat stage on `battler`, keyed as the UI labels them.

    **Nothing published these before**, for either side, and it stopped mattering the moment our
    own stat-change moves started working (clayton-957.10.2). Against Suicune there were two
    stages in the whole run -- our Attack from Aurora Beam and our Sp. Def from Luster Purge --
    and both were inferable from the damage. The Ho-Oh plan is built on *tracking* three of the
    target's at once: accuracy down six from Flash, Attack down from Intimidate and Charm, Defence
    down six from Screech. A player cannot run that from memory, and an Ancient Power proc
    silently cancels an Intimidate, so the number has to be on screen.

    Only the non-zero ones, so the page shows nothing at all in the ordinary case rather than a
    row of seven dashes.
    """
    return {label: getattr(battler, field)
            for label, field in STAGE_FIELDS if getattr(battler, field) != 0}


#: `STAGE_FIELDS` the other way round, so a `Battler` field name can be rendered with the label
#: the page already uses for that stage.
STAGE_LABELS: dict[str, str] = {field: label for label, field in STAGE_FIELDS}


def _stat_drops_info(move) -> list[dict] | None:
    """A move's primary stat drops as ``[{"stat": label, "stages": n}, ...]``, or None.

    A LIST rather than one pair, because Tickle drops two stats. The page reads it by searching
    for the stage it cares about (accuracy, for the mid-turn question a Flash raises) rather than
    by indexing, so a two-stat move needs no second field and no second code path there.
    """
    drops = primary_stat_drop(move)
    if drops is None:
        return None
    return [{"stat": STAGE_LABELS.get(field, field), "stages": stages}
            for field, stages in drops]


def _self_raises_info(move) -> list[dict] | None:
    """The stage raises a move puts on its own user, same shape as `_stat_drops_info`.

    New alongside the rest of the stat family. Nothing in the page needed it while the only
    self-raise our side could carry was Double Team, which no party has -- and it is published
    now because Swords Dance, Dragon Dance, Bulk Up and Calm Mind are moves a player really does
    bring, and a run page that showed a drop but not a boost would be describing half the turn.
    """
    from claytonlib.battle_compass.sim import primary_self_raise

    raises = primary_self_raise(move)
    if raises is None:
        return None
    return [{"stat": STAGE_LABELS.get(field, field), "stages": stages}
            for field, stages in raises]


def _burn_tick_of(battler: Battler) -> int:
    """What burn would take off `battler` at end of turn, or 0 if it is not burned.

    Published per Pokemon rather than once for whoever is out, because the question it answers --
    "could this Pokemon have fainted to something the turn's tokens do not mention?" -- is about
    whoever is out when the turn ENDS. On a switch turn that is the Pokemon coming in.
    """
    return burn_tick(battler) if battler.status is Status.BURN else 0


def _no_effect_hint(move, battler: Battler, defender: Battler | None) -> str | None:
    """Why this move does nothing to `defender`, and what would change it — or None if it does.

    The page cannot work this out for itself, which is why it is computed here. "Deals nothing"
    has three causes that look identical from the outside and call for completely different
    decisions: a plain bad matchup (bring something else), Levitate (nothing in a party fixes it),
    and the Ghost immunity to Normal and Fighting (**one turn fixes it, permanently**). Naming the
    wrong one is worse than saying nothing, because the third is the whole of why Giratina is
    catchable.

    The three are told apart by asking the simulator rather than by reasoning about types: if the
    same move against the same defender *identified* still deals nothing, no Foresight was ever
    going to help. That stays correct for a target whose typing nobody has thought about yet.

    Named for a move in `battler`'s own set when there is one with PP left, because "use Odor
    Sleuth" is actionable where "use a Foresight-type move" is a puzzle.
    """
    if defender is None or not deals_nothing(move, defender, battler):
        return None
    named = defender.name or "the target"
    if deals_nothing(move, replace(defender, identified=True), battler):
        # Levitate, or an ordinary immunity. Nothing to offer, so nothing is offered -- and the
        # ability is named when it is the cause, since that is not readable off the type chart.
        why = (f"{defender.ability} blocks it" if defender.ability and move.type_name == "Ground"
               else "its typing blocks it outright")
        return f"{move.name} does nothing to {named}: {why}."
    fix = next((candidate for slot in range(len(battler.moves))
                if (candidate := battler.move(slot)) is not None
                and candidate.effect == EFFECT_FORESIGHT and battler.pp_left(slot) > 0), None)
    tail = (f"{fix.name} removes it for the rest of the battle."
            if fix is not None else
            "A Foresight or Odor Sleuth removes it for the rest of the battle.")
    return (f"{move.name} does nothing while {named} is unidentified: Ghost is immune to Normal "
            f"and Fighting. {tail}")


def move_info(battler: Battler, defender: Battler | None = None) -> list[dict]:
    """Per slot: what the UI must know to ask the right questions about this move.

    A damaging move renders a hit marker (``h``/``!``); a status move that lands renders the bare
    slot, so asking "did it crit?" about Mean Look would be nonsense. Deriving this here rather
    than in the page keeps one source of truth for it.

    Two flags exist to stop the interview offering impossible outcomes:

    * ``can_miss`` -- only when an accuracy roll can actually fail. Accuracy 0 skips the check and
      accuracy 100 always passes it, so Spore, False Swipe and Sweet Scent cannot miss.
    * ``guaranteed_fail`` -- the move is certain to do nothing given `defender`'s state, and
      renders as the bare slot rather than as a miss. Spore against an already-paralyzed Suicune
      is the case: statuses are mutually exclusive, so it rolls accuracy and then fails.

    * ``selectable`` -- whether this battler could PICK the move at all right now: PP, a Choice
      lock, and Taunt narrowing a target to its damaging moves. The interview must filter on it,
      because an answer the game could not have produced eliminates every candidate rather than
      contradicting one.

    And a third that stops it offering the move at all: ``unselectable_reason``. Note how
    differently that sits from `guaranteed_fail` -- a guaranteed failure is a perfectly good turn
    to report, and a failing Sing is one of the best identification probes there is, whereas an
    unselectable move makes the run unrecoverable the moment it is used.
    """
    out: list[dict] = []
    for slot in range(len(battler.moves)):
        move = battler.move(slot)
        if move is None:
            out.append({"slot": slot, "name": "", "known": False, "damaging": False,
                        "selectable": False, "taunt_refusable": False, "applies_taunt": False,
                        "can_miss": False, "guaranteed_fail": False, "has_secondary": False,
                        "flinch_secondary": False, "applies_status": None,
                        "secondary_status": None, "secondary_label": None,
                        "secondary_side": None, "stat_drop": None, "self_raise": None,
                        "deals_nothing": False, "applies_foresight": False,
                        "no_effect_hint": None, "charges": False,
                        "makes_contact": False,
                        "effect_chance": 0, "priority": 0, "pp": 0,
                        "unselectable_reason": None})
            continue
        #: Whether picking this slot now is the CHARGE turn of a two-turn move. Computed once
        #: and read by four of the fields below, because every one of them is a question about a
        #: particular TURN rather than about the move: Shadow Force is physical, 100-accuracy and
        #: damaging on its second turn, and none of those is true of its first.
        charging = starts_charge_turn(battler, slot)
        out.append({
            "slot": slot,
            "name": move.name,
            "known": True,
            # Whether this battler could actually PICK this move right now, which is a different
            # question from whether the move would do anything (`guaranteed_fail`) or whether we
            # can model it (`unselectable_reason`). Read off `usable_slots`, the one function that
            # knows -- so it covers PP, a Choice lock and, newly, Taunt narrowing the target's
            # selection to its damaging moves.
            #
            # The interview has to filter on it or it offers an answer no candidate can render: a
            # taunted Uxie cannot pick Yawn, so reporting Yawn would eliminate every seed. The
            # 0-PP case was already wrong in the same way and is fixed by the same flag.
            "selectable": slot in battler.usable_slots(),
            # A BANKED move is not "damaging" for the purpose this flag serves -- which is
            # "does the turn it is used render a hit marker". Future Sight is a special move by
            # category and renders the bare slot, because on its use turn it neither hits nor
            # misses nor crits: the damage is banked and the accuracy check is deferred two turns
            # (`banked_hit`). Reporting it as damaging put "Hit us" and "Critical hit" in the
            # interview for a turn that can render neither.
            "damaging": (move.category != CATEGORY_STATUS and not banked_hit(move)
                         and not charging),
            # Stage-dependent: a 100%-accuracy move becomes missable under an accuracy drop or
            # a raised evasion, so this is computed against the real defender, not assumed.
            # The HELD ITEMS go in too, not just the stage: a Brightpowder on the defender makes
            # a 100-accuracy Spore missable at a neutral stage, and an interview that did not know
            # would refuse to let the player report a miss that really happened.
            "can_miss": can_miss(move, accuracy_net_stage(battler, defender)
                                 if defender is not None else 0,
                                 attacker=battler, defender=defender,
                                 charge_turn=charging),
            # The stage's CONSEQUENCE, not the stage. "Sacred Fire 31" is what a player wants off
            # six Flashes; "accuracy_stage -6" makes them do the arithmetic. 0 means the move
            # bypasses the check entirely (Mean Look, Light Screen), which is not the same as 0%.
            "effective_accuracy": _effective_accuracy(
                move, accuracy_net_stage(battler, defender) if defender is not None else 0,
                attacker=battler, defender=defender, charge_turn=charging),
            "guaranteed_fail": defender is not None and will_fail(move, defender),
            # A secondary effect is observable ("Smeargle's Attack fell!") and renders its own
            # `~` token, so the interview has to ask about it or such a turn is unreportable.
            "has_secondary": move.effect_chance > 0,
            # ...with one exception, which is why this flag exists. A flinch is announced on the
            # VICTIM's turn, so a flinching move that goes SECOND leaves no trace at all: there
            # is nothing to ask and nothing to report. See `sim.flinch_visible`.
            "flinch_secondary": move.effect in FLINCH_EFFECTS,
            "effect_chance": move.effect_chance,
            # The non-volatile status this move inflicts, as its token marker, or None. The
            # interview needs it because a status WE apply lands before the target's turn: once
            # Spore connects, "is asleep" is the only thing the target can have done, and it was
            # not on offer because the snapshot's options are read off the turn's OPENING state.
            "applies_status": (st.value if (st := status_applied_by(move)) else None),
            # The same thing for a status the SECONDARY inflicts, which is live mid-turn for the
            # same reason: a Discharge proc paralyzes before the target's half of the turn, so
            # "was fully paralyzed" becomes possible on a turn that opened with it unstatused.
            "secondary_status": (sec.value if (sec := secondary_status(move)) else None),
            # What the secondary looks like to the player, so the interview can name it. None
            # means "not described" and the page says something generic -- see
            # `sim.SECONDARY_DESCRIPTIONS` for why a wrong name is worse than a vague one.
            "secondary_side": (desc[0] if (desc := secondary_description(move)) else None),
            "secondary_label": (desc[1] if desc else None),
            # Whether a Taunt refuses this move at EXECUTION time, which is a different question
            # from `selectable` and the two have to be published separately. `selectable` is read
            # off the opening state, so on the turn a Taunt LANDS it still offers the status
            # moves -- correctly, because the target had already chosen when the Taunt hit. This
            # flag is what lets the page then offer "refused by the taunt" as that slot's
            # outcome. The ROM's own test is on POWER (`sim.taunt_refuses`), so a 0-power move is
            # refusable whether or not anything is taunted yet; the page combines it with
            # `applies_taunt` below (clayton-6xu.7.6).
            "taunt_refusable": not move.power,
            # ...and whether THIS move is the one that lands the Taunt. The mirror of
            # `applies_status`, and live on the same turn for the same reason: a Taunt we land
            # resolves before the target's half of the turn.
            "applies_taunt": move.effect == EFFECT_TAUNT,
            # Whether this turn is a two-turn move's charge turn, so the page can say what the
            # player just watched ("it vanished") instead of leaving a turn with nothing asked
            # about it looking like a question that failed to render. The three flags above
            # already carry the CONSEQUENCES; this one carries the reason.
            "charges": charging,
            # Contact, which decides whether a Static holder's ability could have fired. The
            # page needs it because Static's paralysis is announced by no move at all, so the
            # interview has to ask for it or the roll goes unreported (clayton-957.10.13).
            "makes_contact": move.makes_contact,
            # The move's PRIMARY stat drop on its target, as the UI labels the stage. The page
            # needs it because a drop we land resolves before the target's half of the turn:
            # one Flash makes Punishment missable on the very turn the Flash is used, and the
            # snapshot's `can_miss` is read off the turn's OPENING state (clayton-957.10.8).
            "stat_drop": _stat_drops_info(move),
            "self_raise": _self_raises_info(move),
            # Whether the type chart (or Levitate) zeroes this move outright. Distinct from all
            # three flags above it: the move is selectable, it is modellable, and it does not
            # FAIL -- it connects, spends every roll and renders its hit marker, and only the HP
            # stays put. Against a Ghost target half of a chipper's moveset reads like a bug
            # without it, and it is also how the page can say what a Foresight would buy.
            "deals_nothing": (defender is not None
                              and deals_nothing(move, defender, battler)),
            # ...and WHY, in words, with the fix named when there is one. The bool is for logic
            # and this is for the player; see `_no_effect_hint` for why the page cannot derive it.
            "no_effect_hint": _no_effect_hint(move, battler, defender),
            # ...and whether THIS move is the one that lands the Foresight. The mirror of
            # `applies_taunt`, and live on the same turn for the same reason: a Foresight of ours
            # resolves before the target's half of the turn, so the immunity is gone by the time
            # anything else is asked about that turn.
            "applies_foresight": move.effect == EFFECT_FORESIGHT,
            #: Priority decides turn order before Speed does, so the page needs it to know
            #: which side's tokens come first.
            "priority": move.priority,
            "pp": battler.pp_left(slot),
            # Why the interview must not OFFER this move, or None. Distinct from
            # `guaranteed_fail`, which is a move that may be used and will do nothing: this is a
            # move that must not be used at all, because using it makes the run unrecoverable
            # rather than merely wasted. See `sim.unselectable_reason` -- an effect the simulator
            # cannot model, or one that ends the battle.
            #
            # Reported rather than omitted, so the page can show it disabled with the reason: a
            # move that silently vanishes from the chip row reads as a bug, and a mule is
            # carrying Whirlpool on purpose (`targets.ENCOUNTER_ACCESS`).
            "unselectable_reason": unselectable_reason(move, defender),
        })
    return out


@dataclass
class TurnLog:
    """One accepted turn, kept for display and for replay-based undo."""
    action: Action
    tokens: tuple[str, ...]
    survivors_before: int
    survivors_after: int
    #: Which item, or which bench slot -- part of the action, so replay needs them.
    item_code: str | None = None
    bench_slot: int | None = None
    #: Which party member came in after a faint. Not part of the action -- a faint is something
    #: the turn did to us -- but replay needs it just the same, since it decides who is out next.
    replacement: int | None = None

    @property
    def extra(self) -> dict:
        out = {}
        if self.item_code is not None:
            out["item_code"] = self.item_code
        if self.bench_slot is not None:
            out["bench_slot"] = self.bench_slot
        if self.replacement is not None:
            out["replacement"] = self.replacement
        return out

    @property
    def rendered(self) -> str:
        return tok.render_turn(tok.normalise(self.tokens))


class HuntSession:
    """A run in progress: candidates, phase, history, and the current solver advice."""

    def __init__(self, window: CandidateWindow, ours: Battler, target: Battler,
                 config: HuntConfig, *, solver_config: SolverConfig | None = None,
                 capture_ball: str = "", bench: tuple[Battler, ...] = (),
                 target_nature: str = "", target_ivs: dict | None = None,
                 game: str = ""):
        if not window.candidates:
            raise ValueError("no candidate seeds: widen the window or check the seed targeting")
        self.window = window
        # Party slots are assigned here when the caller did not set them, so every S/X/R token a
        # run emits names a STABLE position: the lead is slot 1 and the bench follows it in
        # order, exactly as the hunt configuration lists them. The app sets them explicitly from
        # `hunt.party` (which is more accurate, since a missing member leaves a gap); this is the
        # fallback that keeps a directly-constructed party sane.
        self.ours = ours if ours.party_slot else replace(ours, party_slot=1)
        self.bench = tuple(b if b.party_slot else replace(b, party_slot=i + 2)
                           for i, b in enumerate(bench))
        self.target = target
        # The nature and IVs the target's stats were DERIVED from. Carried so the spread popup
        # can show them: the derived numbers are what the player checks against the summary
        # screen, and when one disagrees the next question is always "which input was wrong",
        # which the popup could not answer (clayton-1jd). Not used by the simulation -- the
        # stats on `target` are already final.
        self.target_nature = target_nature
        self.target_ivs = dict(target_ivs or {})
        self.config = config
        self.capture_ball = capture_ball
        #: Which game, for the one thing in this class that differs between them: the wording of
        #: the shake-count ladder ("Shoot!" in Platinum, "Gah!" in HGSS). Nothing in the
        #: simulation reads it -- every mechanic Battle Compass models is shared.
        self.game = game
        #: One list of sentences per reported turn, accumulated at report time. See
        #: `explain_history` for why this is not derived from the current state.
        self._explanations: list[list[str]] = []
        # NOT `SolverConfig(danger_floor=...)`. The floor is per-Pokemon -- it reads the
        # DEFENDER's Def and Sp. Def -- and per-stage, so a figure taken here describes the LEAD
        # for the rest of the run. `SolverConfig.danger_floor` is a LOWER bound, so seeding it
        # from the lead also silently defeated clayton-957.10.5's live recomputation:
        # max(the lead's figure, the live one) never reaches the live one when the lead is the
        # squishier Pokemon. With the shiny-seed plan's sacrificial Lv23 Natu leading that figure
        # is 1584, against a 314 HP Ampharos (clayton-957.10.17). It stays a deliberate override
        # for a caller that really does want a minimum.
        self.solver_config = solver_config or SolverConfig()
        self.turns: list[TurnLog] = []
        #: Phase transitions as (turns taken before it, phase), in order. A list rather than a
        #: dict keyed by turn index because two transitions can share an index -- declaring 1 HP
        #: and starting the solver on the same turn boundary is normal -- and a dict would silently
        #: keep only the last.
        self.transitions: list[tuple[int, Phase]] = []
        self.contradiction: dict | None = None
        self.solution: Solution | Unreachable | None = None
        #: Why a forced Phase 2 could not produce a path, if it could not.
        self.forced_reason: str | None = None
        #: How many times the plan has been thrown away and recomputed, and whether the LAST
        #: reported turn did it. Phase 2 follows a cached path and only re-solves on divergence
        #: (:meth:`_follow_plan`), so a run that never diverges replans never -- and a count that
        #: climbs is the player's signal that the game and the model keep disagreeing.
        self.replans = 0
        self.last_turn_replanned = False
        #: Each mid-run widening, so a run record says the window was not what it started as.
        self.widenings: list[dict] = []
        #: Bumped by anything that moves the run forward or sideways -- an accepted turn, an undo,
        #: a rebase, a phase change. It exists for one purpose: a ranking sweep captures it at
        #: entry and aborts the moment it no longer matches, because advice is about ONE position
        #: and finishing it for a position that has been played is pure waste (see `advice`).
        self.position = 0
        self._session = self._fresh()

    # -- construction / replay ------------------------------------------

    def _moved(self) -> None:
        """Record that the position changed, which aborts any ranking sweep still running."""
        self.position += 1

    def _fresh(self) -> Session:
        session = Session(list(self.window.candidates), self.ours, self.target, self.config,
                          phase=Phase.SETUP)
        if self.bench:
            session.states = {seed: replace(state, bench=self.bench)
                              for seed, state in session.states.items()}
        return session

    def _apply_transitions_at(self, boundary: int) -> None:
        """Re-enter any phase recorded at this turn boundary, in the order it happened."""
        for at, phase in self.transitions:
            if at != boundary:
                continue
            if phase is Phase.PINNING and self._session.phase is Phase.SETUP:
                self._session.enter_pinning()
            elif phase is Phase.SOLVING and self._session.phase is not Phase.SOLVING:
                self._session.enter_solving()

    def _replay(self, turns: list[TurnLog]) -> None:
        """Rebuild from the window and re-apply `turns`. The only way state moves backwards."""
        self._moved()
        self._session = self._fresh()
        self.contradiction = None
        # A widen or an undo changes which turns exist, so the accumulated explanations no longer
        # line up. Cleared rather than recomputed here; `explain_history` refills it once.
        self._explanations = []
        # A cached plan belongs to the state it was computed from, and a replay has just moved
        # that state. Dropping it here is what stops `_follow_plan` ticking forward a path that
        # describes a run which no longer exists.
        self.solution = None
        replayed: list[TurnLog] = []
        for index, turn in enumerate(turns):
            self._apply_transitions_at(index)
            before = len(self._session.survivors)
            result = self._session.observe(turn.action, turn.tokens, **turn.extra)
            if result.contradiction:
                # Only reachable if the model changed under us; a turn that was accepted once
                # must be accepted again. Stop rather than silently dropping it.
                raise ValueError(
                    f"replaying turn {index + 1} ({turn.rendered}) no longer matches any "
                    f"candidate; the simulation has changed since it was recorded")
            replayed.append(TurnLog(action=turn.action, tokens=turn.tokens,
                                    survivors_before=before,
                                    survivors_after=len(self._session.survivors),
                                    item_code=turn.item_code, bench_slot=turn.bench_slot,
                                    replacement=turn.replacement))
        self.turns = replayed
        # A transition recorded after the last surviving turn has not happened yet.
        self.transitions = [(at, p) for at, p in self.transitions if at <= len(replayed)]
        self._apply_transitions_at(len(replayed))

    def rebase(self, window: CandidateWindow) -> dict:
        """Swap in a wider candidate window and replay the run against it.

        Recovery for the case that matters: the reported turn matched nothing because the true
        seed was never in the window. Restarting would throw away every turn already reported,
        which is the expensive half of a run -- and those turns are exactly what filters the newly
        admitted candidates, so replaying them costs nothing in information.

        `window` must be a SUPERSET of the current one. A turn that was accepted once has to stay
        accepted, or the history becomes unexplainable and `_replay` would (correctly) refuse; and
        narrowing here would silently discard candidates the player never ruled out.
        """
        missing = {c.seed for c in self.window.candidates} - {c.seed for c in window.candidates}
        if missing:
            raise ValueError(
                f"a wider window must still contain the current candidates; {len(missing)} of "
                f"{len(self.window.candidates)} would be dropped. Widen the frame or second "
                f"range rather than moving the centre.")
        before = len(self.survivors)
        self.window = window
        self._replay(self.turns)
        if self.phase is Phase.SOLVING and self.identified is not None:
            # `_replay` drops the plan, so without this a widening left the page with none at
            # all. It never re-solved before either; the plan simply went stale unnoticed.
            self.solve()
        self.widenings.append({
            "frame_window": window.frame_window,
            "second_window": window.second_window,
            "candidates": len(window.candidates),
            "survivors_before": before,
            "survivors_after": len(self.survivors),
            "after_turn": len(self.turns),
        })
        return self.snapshot()

    # -- read-only state ------------------------------------------------

    @property
    def danger_floor(self) -> int:
        """The worst single hit the target can land **right now**, on whoever is out.

        Derived, not stored. Two things move it and both move during an ordinary run: *who* is
        out (it reads that Pokemon's Def and Sp. Def) and the target's Attack stages (Intimidate
        and Charm roughly halve every physical hit, an Ancient Power proc raises them all).

        Taken once at construction it described the lead forever -- and the Ho-Oh plan leads with
        a sacrificial Lv23 Natu, whose figure is **1584**. Every party member was then reported as
        one hit from fainting at full health for the whole run, which is what the player saw: a
        marker that never cleared because it was never about the Pokemon it was next to.

        **Current weather only.** The solver's `danger_floor_for` enumerates every weather the
        target could set, which is right for a heal decision and wrong for a live indicator: a
        Lv54 Magneton at 122/134 was reported in range of a single hit in clear weather, where
        the worst crit is 92 and only reaches 136 once it is raining (clayton-5rz). So this
        reads the field, and `danger_floor_if_weather` below is the other half -- the two
        numbers answer two different questions and the page shows which is which.
        """
        state = next(iter(self._session.states.values()), None)
        if state is None:
            return worst_incoming_hit(self.ours, self.target)
        # A banked Future Sight is ADDED, not maxed in, and it is added HERE as well as in the
        # solver's figure -- which is the opposite of how the weather is treated two paragraphs
        # up. The difference is that it is not a hypothesis: the hit lands at the end of THIS turn
        # for a number the target fixed two turns ago, so a live indicator that left it out would
        # understate what the turn can cost (clayton-6xu.7.3).
        return max(self.solver_config.danger_floor,
                   worst_incoming_hit(state.ours, state.target,
                                      field=state)) + pending_future_sight(state)

    @property
    def danger_floor_if_weather(self) -> int:
        """`danger_floor`, but counting weather the target can still put up.

        The other half of clayton-5rz. Equal to `danger_floor` when the worst weather is already
        up, or when the target has no weather move -- so the page can compare the two and say
        "in range if it rains" only when that is actually a different answer, rather than
        attaching a hypothetical to every hit.

        This is the figure the solver heals against (`solver.danger_floor_for`), so showing it
        also explains why a plan heals earlier than the live number seems to require.
        """
        state = next(iter(self._session.states.values()), None)
        if state is None:
            return worst_incoming_hit(self.ours, self.target, any_reachable_weather=True)
        return danger_floor_for(state, self.solver_config)

    @property
    def phase(self) -> Phase:
        return self._session.phase

    @property
    def survivors(self) -> tuple[int, ...]:
        return self._session.survivors

    @property
    def identified(self) -> int | None:
        return self._session.identified

    def legal_actions(self) -> list[Action]:
        """Actions the player could report this turn, in slot order.

        Move slots are filtered to those with PP left in *every* surviving candidate, since PP is
        not a thing candidates can disagree about.

        Both balls are legal in every PHASE -- see `Phase`. A standard ball's danger is reported
        by `standard_ball_risk` rather than removed from the list, because the risk is small,
        quantified, and the player's to weigh; and the capture ball never carried one.

        **Neither is legal while the target is away mid-charge**, and that is a stronger
        restriction than a phase: you cannot throw the ball AT ALL [verified in game by Testare].
        It is not a throw that fails -- the ball is never selected and no turn happens -- so this
        is not a risk to disclose but an action that does not exist, and offering it invites a
        report no candidate can render. This project believed the opposite until it was tried
        (clayton-6xu.3.13).

        ``REVIVE`` appears only while somebody is actually down to revive, and ``FAINTED`` only
        while the target could move before us -- otherwise we always got our move off, so being
        fainted before moving is not a thing that can have happened.
        """
        state = next(iter(self._session.states.values()))
        statused = state.ours.status is not Status.NONE
        actions = [_MOVE_ACTIONS[slot] for slot in state.ours.usable_slots()]
        # An item action is only legal while SOME item is selectable, and a status cure only
        # while there is a status to cure. The game refuses a Potion at full HP and a Full Heal
        # on a healthy Pokemon, so offering either is offering a turn that cannot happen.
        if any(items.unusable_reason(i.code, hp=state.ours.hp, max_hp=state.ours.max_hp,
                                     statused=statused) is None
               for i in items.ITEMS):
            actions.append(Action.ITEM)
        if statused:
            actions.append(Action.ITEM_CURE)
        if not is_semi_invulnerable(state.target):
            actions.extend([Action.CAPTURE_BALL, Action.STANDARD_BALL])
        if self.phase is Phase.SETUP and state.healthy_bench:
            actions.append(Action.SWITCH)
        if any(b.fainted for b in state.bench):
            actions.append(Action.REVIVE)
        if self.target_can_move_first():
            actions.append(Action.FAINTED)
        return actions

    def target_can_move_first(self) -> bool:
        """Whether the target could take its turn before ours, by Speed or by priority.

        The gate on reporting "fainted before moving": if we always move first, we always got the
        move off, and offering the option would invite a report no candidate can predict.

        Three ways it is true, which is how the feedback put it: the target outspeeds us, the
        target has a raised-priority move, or one of ours has a lowered-priority move. Checked
        against the moves both sides actually have rather than on Speed alone.
        """
        state = next(iter(self._session.states.values()))
        if effective_speed(state.target) > effective_speed(state.ours):
            return True
        theirs = [m.priority for slot in range(len(state.target.moves))
                  if (m := state.target.move(slot)) is not None]
        ours = [m.priority for slot in range(len(state.ours.moves))
                if (m := state.ours.move(slot)) is not None]
        return max(theirs, default=0) > min(ours, default=0)

    def predict(self, action: Action, **extra) -> dict[int, str]:
        return self._session.predict(action, **extra)

    def action_label(self, action: Action, item_code: str | None = None) -> str:
        """What the action is, in words. "Use False Swipe", not "M1".

        Built from the same move names the interview's chips use, because a ranking nobody can
        read is a ranking nobody acts on -- and worse than unread, a code the player has to
        translate under time pressure is a code they translate wrongly. "M1" and "M4" differ by
        one character and name two completely different moves.

        `item_code` names the actual item when there is one, so a solver step reads "Use a Hyper
        Potion" rather than the bare "Use an item" it would otherwise share with every other
        bag action in the path.
        """
        state = next(iter(self._session.states.values()))
        slot = action.move_slot
        if slot is not None:
            move = state.ours.move(slot)
            return f"Use {move.name}" if move else f"Use move {slot + 1}"
        if action in (Action.ITEM, Action.ITEM_CURE) and item_code:
            try:
                return f"Use a {items.item(item_code).name}"
            except ValueError:
                pass                      # an unknown code falls back to the generic wording
        return {
            Action.ITEM: "Use an item",
            Action.ITEM_CURE: "Use a status cure",
            Action.CAPTURE_BALL: f"Throw the {self.capture_ball or 'capture ball'}",
            Action.STANDARD_BALL: "Throw a Poke Ball",
            Action.SWITCH: "Switch Pokemon",
            Action.REVIVE: "Use a Revive",
            Action.FAINTED: "Fainted before moving",
        }.get(action, action.value)

    def standard_ball_risk(self) -> dict | None:
        """How dangerous it is to throw a plain Poke Ball right now.

        The fraction of surviving candidates on which a standard ball would **capture** -- which
        loses the run, because the target ends up in the wrong ball (sec 2.3). So this is a risk
        gauge, not a progress one: 0% means the throw is free information, and anything above that
        is the chance of throwing the hunt away.

        Reported in every phase, including Phase 1 and including a pinned seed. With one
        candidate it is no longer a percentage but a verdict -- 0% or 100%, "free information" or
        "this throw ends the run" -- which is the most actionable it ever gets, so suppressing it
        there would hide the answer exactly when it is certain.

        `matches_capture_ball` says whether the risk is the harsh kind. On Suicune both balls are
        a flat x1 so a landing is a lost run; where the capture ball actually matches, a standard
        ball is far weaker and a probe is cheap.

        None only when there are no candidates left to measure.
        """
        states = list(self._session.states.values())
        if not states:
            return None
        keep_going = self._still_at(self.position)
        caught = 0
        for state in states:
            # The same sweep cost as one ranked action, and computed for the same position, so it
            # abandons itself on the same terms. See `advice`.
            if not keep_going():
                raise AdviceAborted("the position this risk figure described has been left behind")
            nxt = simulate_turn(state, Action.STANDARD_BALL, self.config)
            caught += bool(nxt.captured_in_wrong_ball)
        return {
            "candidates": len(states),
            "would_catch": caught,
            "percent": round(100.0 * caught / len(states), 1),
            "safe": caught == 0,
            "matches_capture_ball": self.config.standard_ball_matches_capture_ball(),
        }

    def advice(self) -> list[dict]:
        """Actions ranked by how much they would narrow the set, best first (Phase 1.5).

        Empty once the seed is pinned -- there is nothing left to learn, and Phase 2 optimises
        distance instead.

        **Raises `AdviceAborted`** if the run moves on while this is computing. It is the only
        slow call in the tool -- every candidate simulated against every legal action -- and it
        describes one position, so a turn reported underneath it makes the rest of the sweep
        waste that competes with the report for the interpreter (clayton-957.10.11).
        """
        if self.identified is not None:
            return []
        # Only actions the player can CHOOSE. A Revive needs a target this does not know, and
        # being fainted before moving is not a choice at all -- ranking either would offer advice
        # nobody can act on.
        choosable = [a for a in self.legal_actions()
                     if a not in (Action.REVIVE, Action.FAINTED)]
        keep_going = self._still_at(self.position)
        total = len(self.survivors)
        # ONE partition per action. This used to call `rank_actions` and then `partition` again
        # for the group count, sweeping the whole candidate set twice for the same answer -- half
        # of the wait the player was being asked to sit through.
        rows = []
        for action in self._session.rankable(choosable):
            groups = self._session.partition(action, keep_going=keep_going)
            expected = (sum(len(g) ** 2 for g in groups.values()) / total) if total else 0.0
            rows.append({"action": action.value, "label": self.action_label(action),
                         "expected_survivors": round(expected, 2),
                         "groups": len(groups), "_sort": (expected, action.value)})
        rows.sort(key=lambda row: row.pop("_sort"))
        return rows

    def _still_at(self, position: int):
        """A predicate a long sweep can poll: has the run stayed where it was?

        Returned as a closure rather than exposing `position` to the sweep so that there is
        exactly one place that decides what "the same position" means.
        """
        return lambda: self.position == position

    # -- the loop -------------------------------------------------------

    def replay_path(self, path: str) -> dict:
        """Report every turn of a rendered `path` in order. Returns the final snapshot.

        For recovering a run rather than playing one. A code error or a missed frame on a
        not-shiny run is sometimes only discovered later, when the damage numbers stop matching
        -- and re-entering thirty turns by hand to get back to where you were is the kind of
        friction that makes people give up on the tool (clayton-fag).

        **Stops at the first turn that does not fit**, leaving the session exactly where that
        turn began and the contradiction on the snapshot. Pressing on would report later turns
        against a state the game never reached, and the resulting candidate set would be
        confidently wrong rather than visibly stuck -- which is the failure this whole tool is
        built to avoid.

        The action is derived from the turn's own first token rather than passed in, because a
        rendered path already carries it: that is what makes a path round-trip at all.
        """
        turns = tok.split_turns(path)
        if not turns:
            self.contradiction = {"kind": "grammar", "problems": ["no turns in that path"],
                                  "observed": path.strip()[:80]}
            return self.snapshot()
        replayed = 0
        for turn in turns:
            try:
                tokens = tok.tokenise(turn)
            except ValueError as exc:
                self.contradiction = {
                    "kind": "grammar",
                    "problems": [f"turn {replayed + 1} ({turn!r}) is not a turn: {exc}"],
                    "observed": turn}
                return self.snapshot()
            try:
                action, extra = _action_from_tokens(tokens)
            except ValueError as exc:
                self.contradiction = {
                    "kind": "grammar",
                    "problems": [f"turn {replayed + 1} ({turn!r}): {exc}"],
                    "observed": turn}
                return self.snapshot()
            self.observe(action, tokens, **extra)
            if self.contradiction:
                problems = list(self.contradiction.get("problems", []))
                self.contradiction = dict(
                    self.contradiction,
                    problems=[f"stopped at turn {replayed + 1} of {len(turns)} ({turn})"]
                             + problems)
                return self.snapshot()
            replayed += 1
        return self.snapshot()

    def observe(self, action: Action, tokens: tuple[str, ...] | list[str],
                item_code: str | None = None, bench_slot: int | None = None,
                replacement: int | None = None) -> dict:
        """Accept one reported turn. Returns the new snapshot.

        A contradiction does **not** advance the turn or shrink the set: it is surfaced on the
        snapshot so the player can fix a typo or widen the window, because an impossible
        observation almost always means one of those rather than a genuinely excluded set
        (sec 15.5).
        """
        problems = tok.validate_turn(list(tokens))
        if problems:
            self.contradiction = {"kind": "grammar", "problems": problems,
                                  "observed": tok.render_turn(tok.normalise(list(tokens)))}
            return self.snapshot()

        # Explained BEFORE the turn is applied, which is the only moment "who was out" is both
        # live and correct -- and the reason `explain_history` no longer replays the whole run to
        # recover it. Captured here, appended only if the turn is accepted.
        explanation = self._explain_one(tokens)

        extra = {}
        if item_code is not None:
            extra["item_code"] = item_code
        if bench_slot is not None:
            extra["bench_slot"] = bench_slot
        if replacement is not None:
            extra["replacement"] = replacement
        before = len(self._session.survivors)
        result = self._session.observe(action, tokens, **extra)
        if result.contradiction:
            self.contradiction = {
                "kind": "no_match",
                "observed": tok.render_turn(tok.normalise(list(tokens))),
                "predicted": _preview(result.rejected),
                "problems": [
                    "No candidate seed predicted that turn, so the set was left untouched.",
                    "Most likely: a mistyped token, or the true seed is outside the window.",
                ],
            }
            return self.snapshot()

        self.contradiction = None
        # The run has moved: abandon any ranking sweep still describing the turn just played.
        # Deliberately NOT bumped on a contradiction above -- the position is unchanged there, and
        # the advice on screen is still the advice for it.
        self._moved()
        self.turns.append(TurnLog(action=action, tokens=tuple(tokens),
                                  survivors_before=before,
                                  survivors_after=len(self._session.survivors),
                                  item_code=item_code, bench_slot=bench_slot,
                                  replacement=replacement))
        self._explanations.append(explanation)
        if self.phase is Phase.SOLVING:
            # Keep the plan when the turn went to plan; re-solve only on divergence. The path the
            # player is reading off the screen then stops changing under them turn to turn.
            if not self._follow_plan(action, tokens, item_code):
                self.solve()
        return self.snapshot()

    def undo(self) -> dict:
        """Rewind one reported turn and re-widen the set (sec 15.4.2, the misreport case).

        A *misplay* is not undone -- the game has advanced, so there is nothing to rewind. Report
        what actually happened with :meth:`observe` and Phase 2 re-solves from there.
        """
        self.contradiction = None
        if not self.turns:
            return self.snapshot()
        self._replay(self.turns[:-1])
        if self.phase is Phase.SOLVING:
            self.solve()
        return self.snapshot()

    # -- phases ---------------------------------------------------------

    def enter_pinning(self, declared_hp: int | None = 1) -> dict:
        """`declared_hp=None` trusts the simulation; a number is the player's word for it.

        The default stays 1 for the callers that mean it (the chip-to-1 flow and the force path);
        the app passes `None` explicitly now that any HP solves. See `Session.enter_pinning`.
        """
        self._moved()
        self._session.enter_pinning(declared_hp=declared_hp)
        self.transitions.append((len(self.turns), Phase.PINNING))
        return self.snapshot()

    def solver_blockers(self, *, assume_past_setup: bool = False) -> list[str]:
        return self._session.solver_blockers(assume_past_setup=assume_past_setup)

    @property
    def ready_to_solve(self) -> bool:
        """Whether one click could start solving right now.

        Phrased as "ignoring the phase", because entering Phase 1.5 is no longer something the
        player does -- the 1 HP declaration rides along with the single "Start solving" click.
        So the question the page asks is "is the target at 1 HP and the seed pinned", and the
        setup phase itself is not an obstacle to report.
        """
        return not self._session.solver_blockers(assume_past_setup=True)

    def enter_solving(self, *, force: bool = False) -> dict:
        """Move to Phase 2 and solve.

        `force` proceeds despite `solver_blockers`. The blockers are what the SIMULATION believes,
        and it can be wrong in ways the player can see and it cannot -- an unmodelled damage
        modifier, say, leaves the simulated target above 1 HP when the real one is there. The
        player is looking at the game; refusing outright would make the tool unusable precisely
        when its model is the thing at fault. The caller is expected to confirm first.
        """
        self._moved()
        if force:
            # Forcing means "trust the game over the model", so it has to actually do that. It
            # used to only skip the blocker LIST, leaving the simulated HP untouched -- and then
            # `solve` refused on its own precondition about that same number, which is the tool
            # arguing with an answer the player had already given twice.
            self._session.declare_target_at_one_hp()
            self._session.phase = Phase.SOLVING
        else:
            self._session.enter_solving()
        self.transitions.append((len(self.turns), Phase.SOLVING))
        try:
            self.solve()
        except ValueError as exc:
            # Forced past an unpinned seed: there is no single state to solve from. Say so
            # instead of failing the transition the player asked for.
            self.solution = None
            self.forced_reason = str(exc)
        return self.snapshot()

    def solve(self) -> Solution | Unreachable:
        """Re-solve from the current state, discarding any cached plan."""
        seed = self.identified
        if seed is None:
            raise ValueError("cannot solve until the seed is pinned")
        self.replans += 1
        self.last_turn_replanned = True
        self.solution = solve(self._session.state_of(seed), self.config, self.solver_config)
        return self.solution

    def _follow_plan(self, action: Action, tokens, item_code: str | None) -> bool:
        """Tick the cached plan forward if the reported turn is exactly the one it predicted.

        **Why keeping it is not a shortcut.** Dijkstra returns a shortest path, and the suffix of
        a shortest path is a shortest path from the state it continues at -- so when the reported
        turn matches the plan's own prediction *token for token*, the remaining steps are still
        the best answer and re-solving can only reproduce them. The match is what licenses it: the
        tokens being identical is precisely the statement that the state the plan continues from
        is the state we are now in.

        **Why re-solving every turn was worse than redundant.** With `collapse_offsets` the
        search is a heuristic over arrival order, so two solves from equivalent states can return
        *different* equally-priced paths -- and the plan visibly changed under the player
        mid-run, which is what prompted this. It also made a transient refusal (a woken target,
        before clayton-agh.1) destroy a plan that was still perfectly good.

        Anything else re-solves: a different action, a different item, a different token stream,
        a faint (which the solver never plans), or a plan that has run out of steps.
        """
        plan = self.solution
        if not isinstance(plan, Solution) or not plan.steps:
            return False
        step = plan.steps[0]
        if step.action is not action or (step.item or None) != (item_code or None):
            return False
        if step.rendered != tok.render_turn(tok.normalise(list(tokens))):
            return False
        self.solution = replace(plan, steps=plan.steps[1:],
                                total_distance=plan.total_distance - step.distance)
        self.last_turn_replanned = False
        return True

    # -- output ---------------------------------------------------------

    def run_record(self) -> dict:
        """This attempt as a saveable record (sec 15.4).

        Assembled here rather than in the page so the stored shape is decided by the thing that
        knows the run, not by whatever the UI happened to have in hand. Diagnostic only: nothing
        feeds it back into calibration.

        The two fields that make it worth keeping are `path` and `target_spread` -- together they
        are enough to replay the attempt. A record without the spread is unreproducible whenever
        Seed A was not the key seed, which is most runs.
        """
        return {
            "outcome": self.outcome(),
            "turns": len(self.turns),
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "b_seed": self._candidate_row(self.identified) if self.identified else {},
            "items": self.items_spent(),
            "capture_ball": self.capture_ball,
            "window": {"frame_centre": self.window.frame_centre,
                       "second_centre": self.window.second_centre,
                       "frame_window": self.window.frame_window,
                       "second_window": self.window.second_window,
                       "size": len(self.window.candidates)},
            "widenings": list(self.widenings),
        }

    def outcome(self) -> str:
        """How the run ended, as one word -- or "" while it is still going.

        `all`, for the same reason the snapshot's flags use it: a candidate set that disagrees
        about whether the ball landed has not finished.
        """
        states = list(self._session.states.values())
        if not states:
            return ""
        if all(st.captured for st in states):
            return "caught"
        if all(st.captured_in_wrong_ball for st in states):
            return "wrong_ball"
        # A ROAMER got away, which is a lost run and not a lost turn: the battle is over and the
        # roamer has been relocated, so the next attempt starts by finding it again
        # (notes/roamers.md sec 3). `all`, like every other ending here -- a candidate set that
        # disagrees about whether it fled has not finished, and disagreement is possible: the
        # escape is speed-ordered, so two candidates can differ on whether our trap landed first.
        if all(st.target_fled for st in states):
            return "fled"
        # The WIPE, not a faint: a faint with a replacement left is a turn, not an ending.
        if all(st.party_wiped for st in states):
            return "wiped"
        return ""

    def items_spent(self) -> dict[str, int]:
        """Items actually used, code -> count, from the reported turns.

        Read off the history rather than off the solver's plan: the plan is what was advised and
        the history is what happened, and the difference is exactly what a diagnostic record
        exists to show.
        """
        spent: dict[str, int] = {}
        for turn in self.turns:
            if turn.item_code:
                spent[turn.item_code] = spent.get(turn.item_code, 0) + 1
            elif turn.action is Action.REVIVE:
                # A Revive carries no item code -- it is its own action, with a party slot
                # instead -- but it is still something the run spent money on.
                spent["rev"] = spent.get("rev", 0) + 1
        return spent

    def explain(self, tokens) -> list[str]:
        """One turn's tokens as plain sentences, with this battle's names filled in.

        The grammar is dense on purpose and the interview exists so the player never types one --
        but tokens still surface where they have to be understood: the solver's recommended turn,
        the turns-so-far table, and a contradiction report. Same renderer for all three, so they
        cannot describe the same turn differently.

        Names come from the CURRENT active Pokemon, which is right for a recommendation and wrong
        for a history row played before a switch. `explain_history` handles that; this does not.
        """
        state = next(iter(self._session.states.values()))
        return tok.explain_turn(
            tokens, ours=state.ours.name, ours_moves=tuple(state.ours.moves),
            target=state.target.name, target_moves=tuple(state.target.moves),
            capture_ball=self.capture_ball or "capture ball",
            item_name=_item_name, party_name=_party_namer(state), game=self.game)

    def _explain_one(self, tokens) -> list[str]:
        """One turn explained against the CURRENT state -- i.e. the state it is about to leave.

        Separate from `explain_history` so a turn can be explained once, at the moment it is
        reported, instead of being recovered by replaying the run.
        """
        state = next(iter(self._session.states.values()), None)
        if state is None:
            return []
        return tok.explain_turn(
            tuple(tokens), ours=state.ours.name, ours_moves=tuple(state.ours.moves),
            target=state.target.name, target_moves=tuple(state.target.moves),
            capture_ball=self.capture_ball or "capture ball", item_name=_item_name,
            party_name=_party_namer(state), game=self.game)

    def explain_history(self) -> list[list[str]]:
        """Every reported turn explained, one list of sentences per turn.

        **Accumulated as turns are reported, not replayed.** The correctness requirement is
        unchanged and is the reason this is not simply read off the current state: a turn played
        before a switch belongs to a different Pokemon with a different moveset, so naming its
        moves from whoever is out NOW would confidently describe the wrong move. That is the same
        hazard which keeps the turn table's action column in codes.
        
        What changed is WHEN the right state is consulted. A turn's explanation cannot change once
        the turn is reported -- who was out and what they knew is history -- so it is computed at
        report time, when that state is live, and kept.
        
        It used to rebuild a session over every ORIGINAL candidate and re-observe the whole run,
        on every snapshot, purely for these tooltips. That is the full identification sweep
        repeated per turn: measured at **6.2 seconds for one reported turn** against a
        6,000-candidate window, with 7,456 `simulate_turn` calls, *and the set already narrowed to
        a single survivor*. The cost tracked the original window rather than what was left, which
        is why narrowing the pool never made the run feel faster.
        
        The replay survives as the rebuild path: `_replay` clears the cache (a widen or an undo
        genuinely does change which turns exist), and the next call refills it once.
        """
        if len(self._explanations) == len(self.turns):
            return list(self._explanations)
        session = self._fresh()
        out: list[list[str]] = []
        for turn in self.turns:
            state = next(iter(session.states.values()))
            out.append(tok.explain_turn(
                turn.tokens, ours=state.ours.name, ours_moves=tuple(state.ours.moves),
                target=state.target.name, target_moves=tuple(state.target.moves),
                capture_ball=self.capture_ball or "capture ball", item_name=_item_name,
                party_name=_party_namer(state), game=self.game))
            session.observe(turn.action, turn.tokens, **turn.extra)
        self._explanations = list(out)
        return out

    def _candidate_row(self, seed: int) -> dict:
        """One candidate as the page shows it: where it sits, and how far that is from the aim.

        The deltas are computed against the LIVE window centre rather than stored on the
        candidate, so a mid-run `rebase` cannot leave them describing a window that no longer
        exists.
        """
        import datetime as _dt
        info = self._session.candidate_info[seed]
        return {
            "seed": f"{seed:#010x}",
            "frame": info.frame,
            "second": info.second,
            "frame_delta": info.frame_delta(self.window.frame_centre),
            "second_delta": info.second_delta(self.window.second_centre),
            # The same two values again, in the spelling the calibration fit reads -- `delay` is
            # the frame (one physical quantity, two historical names) and `time` is the absolute
            # clock time this seed was generated at. Both are exact rather than reconstructed:
            # `candidates.generate` builds the seed as
            # `calculate_seed(initial_time + second, frame)`, so this is that expression read
            # back. Carried on the row so a saved run is self-describing and does not depend on
            # the hunt's configuration still saying what it said during the run (clayton-6xu.3.6).
            "delay": info.frame,
            "time": (self.window.initial_time
                     + _dt.timedelta(seconds=info.second)).strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def hp_range(self, side: str) -> dict:
        """(low, high) HP across every surviving candidate, for one side.

        The snapshot used to publish whichever candidate came first out of the dict, which showed
        one guess as though it were fact -- and candidates genuinely disagree, because they
        predict different damage rolls and different critical hits. A range says what is actually
        known: HP is at least `low`, at most `high`, and equal to one of them only once the seed
        is pinned.
        """
        values = [getattr(state, side).hp for state in self._session.states.values()]
        return {"low": min(values), "high": max(values), "certain": min(values) == max(values)}

    def snapshot(self, *, include_advice: bool = False) -> dict:
        """Everything the UI needs, as plain JSON-safe data.

        One method rather than several so a caller cannot render a half-updated view, and so a
        recorded snapshot is a complete regression fixture.

        `include_advice` is off by default because ranking actions simulates every candidate
        against every action -- 8s at 6,000 candidates, and the *only* slow part of a snapshot.
        The page renders without it and fetches it separately, so a turn is never waiting on
        advice the player may not read.
        """
        state = next(iter(self._session.states.values()))
        we_first = effective_speed(state.ours) > effective_speed(state.target)
        floor = self.danger_floor
        floor_weather = self.danger_floor_if_weather
        seed = self.identified
        # How the run ENDED, which the snapshot never said. Its absence is why the capture bug
        # was reachable at all: with no terminal flag the page had no reason to stop asking for
        # turns, so the only thing between a landed ball and a fresh question was the solver
        # crashing. `all`, not `any`: a candidate set that disagrees about whether the ball
        # landed has not finished, and reporting a win on one member of it would be a lie.
        states = list(self._session.states.values())
        out = {
            "phase": int(self.phase),
            "phase_label": self.phase.label,
            "captured": all(st.captured for st in states),
            "captured_in_wrong_ball": all(st.captured_in_wrong_ball for st in states),
            # The run-ending kind: our Pokemon is down and there is nobody to replace it. A faint
            # with a replacement left is a reported TURN, not an ending, so this stayed false
            # through it -- which is the whole point of the distinction.
            "we_fainted": all(st.party_wiped for st in states),
            "party_wiped": all(st.party_wiped for st in states),
            # The roamer's version of a wipe: terminal, and only ever true with a roamer target.
            "target_fled": all(st.target_fled for st in states),
            # ...and this one says somebody went down *this* turn, replacement or not, so the
            # page can say so without claiming the run is over.
            "active_fainted": all(st.ours.fainted for st in states),
            "over": all(st.over for st in states),
            # Whether a plain Poke Ball is exactly as catchable as the capture ball here, which
            # is what decides how harshly to word a standard-ball throw. Replaces the old
            # `balls_allowed` flag: balls are always allowed now, so a key that was always true
            # told the page nothing, while this tells it which warning to show. Cheap -- config
            # arithmetic, not a candidate sweep, so it belongs on the snapshot where
            # `standard_ball_risk` does not.
            "standard_ball_matches_capture_ball":
                self.config.standard_ball_matches_capture_ball(),
            "survivors": len(self.survivors),
            "identified": None if seed is None else f"{seed:#010x}",
            "candidates": [self._candidate_row(s)
                           for s in self.survivors[:CANDIDATE_PREVIEW]],
            # Where the pinned seed actually landed, relative to where it was aimed. This is the
            # run's only feedback on its own timing: the seed alone says nothing about whether
            # the window was centred well, and the two axes miss near-independently, so a run
            # that was 30 frames late but dead-on the second is a different problem from one
            # that was a second out.
            "identified_at": None if seed is None else self._candidate_row(seed),
            "candidates_truncated": max(0, len(self.survivors) - CANDIDATE_PREVIEW),
            "window": {
                "frame_centre": self.window.frame_centre,
                "second_centre": self.window.second_centre,
                "frame_window": self.window.frame_window,
                "second_window": self.window.second_window,
                "size": len(self.window.candidates),
            },
            # Who acts first when we use a MOVE. A bag action or switch always resolves before
            # any move, so the page ignores this for those (sec 12.1).
            "we_move_first": we_first,
            "prevention": {
                "ours": prevention_options(state.ours, state.target,
                                           actor_moves_first=we_first),
                "target": (prevention_options(state.target, state.ours,
                                              actor_moves_first=not we_first)
                           + flee_options(state, self.config)),
            },
            "resolution": {
                "ours": resolution_options(state.ours),
                "target": resolution_options(state.target),
            },
            "ours": {"name": state.ours.name, "hp": state.ours.hp,
                     "max_hp": state.ours.max_hp,
                     "status": state.ours.status.value,
                     "confused": state.ours.confused,
                     "hp_range": self.hp_range("ours"),
                     "ability": state.ours.ability,
                     "held_item": state.ours.held_item,
                     "burn_tick": _burn_tick_of(state.ours),
                     "effective_speed": effective_speed(state.ours),
                     "level": state.ours.level,
                     "types": list(state.ours.types),
                     "stats": dict(state.ours.stats),
                     "pp": [state.ours.pp_left(i) for i in range(len(state.ours.moves))],
                     "moves": list(state.ours.moves),
                     "stages": stat_stages(state.ours),
                     "move_info": move_info(state.ours, state.target)},
            "target": {"name": state.target.name, "hp": state.target.hp,
                       "max_hp": state.target.max_hp,
                       "status": state.target.status.value,
                       "confused": state.target.confused,
                       "hp_range": self.hp_range("target"),
                       "ability": state.target.ability,
                       "held_item": state.target.held_item,
                       "effective_speed": effective_speed(state.target),
                       "level": state.target.level,
                       "types": list(state.target.types),
                       # The full spread, for the popup that lets the player check it against the
                       # Pokemon once they have it. The run page shows HP and Speed inline, but
                       # the rest is only verifiable AFTER the catch -- so it is offered where
                       # that check happens rather than buried back in the search screen.
                       "stats": dict(state.target.stats),
                       "pp": [state.target.pp_left(i) for i in range(len(state.target.moves))],
                       "moves": list(state.target.moves),
                       # What the stats were derived FROM, so a mismatch against the summary
                       # screen points at the input that is wrong rather than just at the output.
                       "nature": self.target_nature,
                       "ivs": dict(self.target_ivs),
                       # The three the Ho-Oh plan spends most of its turns moving.
                       "stages": stat_stages(state.target),
                       # Away mid-charge, so **nothing we do can reach it this turn** -- Shadow
                       # Force's charge turn. Reported rather than left to be inferred, because
                       # the alternative is a player watching four moves miss in a row with no
                       # explanation and reasonably concluding the tool is broken. Our move still
                       # spends its rolls, so the candidate filtering is unaffected; what the
                       # page does with this is say why.
                       "vanished": is_semi_invulnerable(state.target),
                       # **Whether our move can reach it THIS turn, which is not the same
                       # question** -- and the page used to conflate them, asserting a miss and
                       # removing the question whenever `vanished` was true. That is right only
                       # when we move FIRST. When the target moves first, a turn that opens with
                       # it away is its FIRE turn: it reappears to attack, clearing the vanish
                       # (`effect_script_0272.s` `_055`), and our move lands. Forcing a miss
                       # there made a Screech the player had watched connect unreportable.
                       #
                       # Only ever true of a certainty, so the page may still assert on it.
                       "unreachable_now": (we_first
                                           and is_semi_invulnerable(state.target)),
                       # ...and the mirror: the target moves first and might vanish before we
                       # act, so even an accuracy-0 move of ours can miss. A MAY, because which
                       # move it picks is per-candidate -- so this widens what the interview will
                       # accept rather than narrowing it.
                       "may_vanish_first": (not we_first
                                            and could_vanish_before_us(state.target)),
                       "move_info": move_info(state.target, state.ours)},
            # Every field condition the simulator tracks, with its remaining turns. None of it
            # was shown, so the player was holding counters in their head -- and several of these
            # change the ADVANCE COUNT of a turn (a Rain Dance into standing rain fails and so
            # costs two fewer advances), which makes them exactly the sort of thing worth seeing
            # rather than remembering. Built from the state rather than from the turn log so it
            # cannot drift from what the simulation believes (clayton-gni).
            "field": field_conditions(state),
            # Whether a banked Future Sight lands at the END of this turn, which makes its hit
            # check a question the interview has to ask: it is a real 90% roll and its verdict is
            # the only sub-100 event either Uxie's or Azelf's moveset produces, so an unasked one
            # is an unfilterable one on the single roll those targets offer
            # (notes/seed_separation.md).
            #
            # Deliberately not "is one pending": the counter reaching 1 is what means "this
            # turn". Asking a turn early would invite a report of something the player has not
            # seen yet, which is how a candidate set gets filtered on a guess.
            #
            # It can still fail to fire -- a capture ends the turn before the end-of-turn block
            # runs, and a faint from any cause stops it (`sim._roll_future_sight`) -- so the page
            # drops the question in both cases rather than this flag trying to predict them.
            "future_sight_due": state.future_sight_turns == 1,
            # `slot` is the BENCH index, which is what every call back into the session takes;
            # `party_slot` is the stable number the player sees in-game and the one the S/X/R
            # tokens name. Both, because they are not the same once anybody has switched.
            "bench": [{"slot": i, "name": b.name,
                       "party_slot": b.party_slot or i + 2,
                       "hp": b.hp, "max_hp": b.max_hp,
                       "fainted": b.fainted,
                       "status": b.status.value,
                       # Per Pokemon, because on a SWITCH turn the tick lands on the INCOMING
                       # one -- a switch resolves before any move. One figure for the lead had
                       # the interview asking whether Granbull fainted to a burn Ampharos was
                       # carrying (clayton-957.10.16).
                       "burn_tick": _burn_tick_of(b),
                       # The INCOMING Pokemon is the one a switch turn asks about, so its ability
                       # has to be here: a switch resolves before any move, so the target's
                       # contact move lands on the newcomer and it is the newcomer's Static that
                       # could fire. Without this the question was silently skipped on exactly
                       # the turn the plan brings Ampharos in on.
                       "ability": b.ability,
                       "moves": list(b.moves),
                       # **The target's moves as they would land on THIS Pokemon**, for the same
                       # reason `burn_tick` and `ability` above are per-bench-member: a switch
                       # resolves before any move, so the newcomer is who the target's attack
                       # hits. The top-level `target.move_info` is computed against whoever was
                       # out when the turn OPENED, which on a switch turn is the Pokemon leaving.
                       #
                       # The case that found it: Giratina used Ominous Wind on the turn a
                       # Smeargle came in. Ghost does nothing to a Normal type, so the turn
                       # renders a bare `E1` with no HP -- but the outgoing Magneton is
                       # Electric/Steel, which merely RESISTS it, so the interview asked whether
                       # it hit and for how much (clayton-6xu.3.11).
                       #
                       # Every field that depends on the defender moves with it, not just the
                       # immunity: `can_miss` and `effective_accuracy` read the defender's evasion
                       # and its held item, and `deals_nothing` reads its types and ability. So
                       # the whole row is recomputed rather than one flag being patched.
                       "incoming_move_info": move_info(state.target, b)}
                      for i, b in enumerate(state.bench)],
            "ours_party_slot": state.ours.party_slot or 1,
            # Whether "fainted before moving" is a reportable outcome at all.
            "target_can_move_first": self.target_can_move_first(),
            "revive_price": items.REVIVE_PRICE,
            # `unusable` is why the game would refuse this item right now, or null. The page
            # offers only the usable ones: a Potion at full HP cannot be selected in-game, and a
            # turn reporting one renders without an HP token while the grammar demands one.
            "items": [{"code": i.code, "name": i.name, "price": i.price,
                       "heals": i.heals, "cures_status": i.cures_status,
                       "heal": i.heal,
                       "unusable": items.unusable_reason(
                           i.code, hp=state.ours.hp, max_hp=state.ours.max_hp,
                           statused=state.ours.status is not Status.NONE)}
                      for i in items.ITEMS],
            "capture_ball": self.capture_ball,
            # Both describe whoever is out NOW, at the target's current stages -- see the
            # `danger_floor` property. Computed once here rather than twice so the number the
            # page prints and the flag it colours cannot disagree.
            "danger_floor": floor,
            "in_danger": state.ours.hp is not None and state.ours.hp <= floor,
            # The same question asked of weather the target has not put up yet. Separate from
            # `in_danger` so the page can distinguish "one hit kills you" from "one hit kills you
            # once it rains" -- conflating them reported a Magneton at 122/134 as in range in
            # clear weather, where the worst hit was 92 (clayton-5rz).
            "danger_floor_if_weather": floor_weather,
            "in_danger_if_weather": (state.ours.hp is not None
                                     and floor_weather > floor
                                     and state.ours.hp <= floor_weather),
            # The action column stays a CODE: `action_label` names a move from the currently
            # active Pokemon, so labelling a turn played before a switch would name the wrong
            # move, and the column pairs with `path` below, which is in codes anyway. `explain`
            # is the plain-language version and is safe because `explain_history` replays the
            # run, so each turn is described by whoever was actually out for it.
            "turns": [{"n": i + 1, "action": t.action.value, "rendered": t.rendered,
                       "explain": explanation,
                       "survivors_before": t.survivors_before,
                       "survivors_after": t.survivors_after}
                      for i, (t, explanation) in enumerate(
                          zip(self.turns, self.explain_history()))],
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "legal_actions": [a.value for a in self.legal_actions()],
            "advice": self.advice() if include_advice else None,
            # True when advice exists to be fetched but was not computed here.
            "advice_pending": not include_advice and self.identified is None,
            "ambiguity": self._session.ambiguity(),
            # Ignoring the phase, because one click now clears it: the 1 HP declaration rides
            # along with "Start solving" instead of being its own button (clayton-pv0).
            "solver_blockers": self.solver_blockers(assume_past_setup=True),
            "ready_to_solve": self.ready_to_solve,
            "contradiction": self.contradiction,
            "forced_reason": self.forced_reason,
            "widenings": list(self.widenings),
            "solution": None,
        }
        if isinstance(self.solution, Solution):
            steps = self.solution.steps
            out["solution"] = {
                "found": True,
                # Whether the last reported turn kept this plan or threw it away. Phase 2
                # follows a cached path and re-solves only on divergence, so "replanned" is the
                # interesting event: it says the game and the model disagreed about that turn.
                "replanned": self.last_turn_replanned,
                "replans": self.replans,
                # Zero steps is a real and good answer: the solver was asked for a path from a
                # state that is ALREADY captured, so the path is empty. `steps[0]` was taken
                # unconditionally, and the one turn a run exists to reach -- the capture landing
                # -- raised "list index out of range" the moment it was reported. The solver
                # re-runs after every Phase 2 turn, so the winning turn was guaranteed to hit it.
                "done": not steps,
                "turns": self.solution.turns,
                "distance": self.solution.total_distance,
                "rendered": self.solution.rendered(),
                "items": self.solution.item_bill(),
                "next": None if not steps else {
                    "action": steps[0].action.value,
                    "label": self.action_label(steps[0].action, steps[0].item),
                    "item": steps[0].item,
                    "expect": steps[0].rendered,
                    "explain": self.explain(steps[0].tokens)},
                "steps": [{"n": i + 1, "action": s.action.value,
                           "label": self.action_label(s.action, s.item), "item": s.item,
                           "expect": s.rendered, "distance": s.distance}
                          for i, s in enumerate(steps)],
            }
        elif isinstance(self.solution, Unreachable):
            out["solution"] = {
                "found": False,
                "reason": self.solution.reason,
                "proven": self.solution.proven,
                # Targets, not reachable ones -- see Unreachable's docstring.
                "capture_windows": self.solution.capture_windows,
                "searched_turns": self.solution.searched_turns,
            }
        return out


def _preview(predictions: dict[int, str], limit: int = 6) -> list[dict]:
    """A few of what candidates predicted, for explaining a contradiction."""
    return [{"seed": f"{s:#010x}", "predicted": p}
            for s, p in list(predictions.items())[:limit]]
