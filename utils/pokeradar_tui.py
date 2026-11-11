#!/usr/bin/env python3
"""Poke Radar patch viewer (DPPt) -- a TUI for one radar wave off a given seed.

Reads a seed, applies N LCRNG advances, then replays the ROM's patch generation:
`RadarSpawnPatches` (4 rolls, one per concentric ring of the 9x9 box) followed by
`SetupGrassPatches` (per live patch: a continue-the-chain roll, then either a
shake-type roll or a shiny roll).  Verified against pret/pokeplatinum
`src/pokeradar.c:91-164,399-423,466-481`.

The encounter-slot overlay (tab) answers the routing question: how many advances
to perform BEFORE the final step into the patch, so that step lands on a given
slot.  The step table beside it gives the cumulative cost of the walk itself, so
the difference is what you still owe the journal or Chatot.

Nothing here touches claytonlib -- the Poke Radar is a DPPt mechanic and this
project is HGSS.  Standalone, stdlib only.

    utils/pokeradar_tui.py 0xED0203EF
    utils/pokeradar_tui.py 0xEE0203EF --advances 99 --chain 1 --hard --source capture
    utils/pokeradar_tui.py 0xED0203EF --print --slots   # one frame to stdout, no TTY

Keys
    0-3            toggle whether that patch's tile is grass
    left/down/h/j  advances - 1          right/up/k/l   advances + 1
                   (while the overlay is up, these page through it instead)
    enter          type a new advance count, enter again to set
    -/+            chain count - 1 / + 1
    c              chain's shake type: hard <-> soft (inert at chain 0)
    r              what set this wave up: capture (default) -> item -> faint;
                   forced to a radar use at chain 0
    s              lead ability: none <-> Static/Magnet Pull (one extra roll before
                   the slot roll, on a breaking patch only)
    a              frame numbers: relative to the wave <-> ABSOLUTE from the seed
    tab            overlay: advances before stepping in, per encounter slot
    P              prompt for a target PID; adds a row of the advances that hit it
                   (searches 0-999; empty entry clears it)
    q / esc        quit

Walk model assumptions (see --rate / --attempts / --battle-gap):
    Repel blocks every non-patch encounter, no roamer is on the route, and the
    lead has none of Magnet Pull / Static / Synchronize / Cute Charm / Keen Eye /
    Intimidate.  Each of those adds rolls this tool does not model.
"""

import argparse
import curses

# --- LCRNG ------------------------------------------------------------------
# include/math_util.h:8-9, src/math_util.c:80
MULTIPLIER = 1103515245
INCREMENT = 24691
MASK = 0xFFFFFFFF


def scale(value16, bound):
    """LCRNG_RandMod's arithmetic -- a scaled division, NOT a modulo (include/inlines.h:156)."""
    if bound <= 1:
        return 0
    return value16 // ((0xFFFF // bound) + 1)


class Lcrng:
    """The overworld LCRNG.  `calls` counts rolls drawn, not raw advances."""

    def __init__(self, seed):
        self.state = seed & MASK
        self.calls = 0

    def step(self):
        self.state = (self.state * MULTIPLIER + INCREMENT) & MASK
        return self.state

    def next16(self):
        self.step()
        self.calls += 1
        return self.state >> 16

    def rand_mod(self, bound):
        return scale(self.next16(), bound)


# --- the ROM's patch generation --------------------------------------------
RING_PERIMETER = (32, 24, 16, 8)       # src/pokeradar.c:97-102, ring 0 is outermost
RATES_FAINTED = (88, 68, 48, 28)       # src/pokeradar.c:401 ratesNormal
RATES_CAPTURED = (98, 78, 58, 38)      # src/pokeradar.c:402 ratesBoosted
CENTRE = 4                             # the player, at local (4,4)

SOFT, HARD = "soft", "hard"
ITEM, FAINT, CAPTURE = "item", "faint", "capture"
SOURCES = (FAINT, CAPTURE, ITEM)

# A post-battle wave rolls its patch positions BEFORE the battle
# (wild_encounters.c:714-717) and its shake/continue/shiny flags AFTER it
# (encounter.c:425-430).  In between, RoamerAfterBattle_UpdateRoamers draws one
# unconditional RandMod(100) -- the 30% "roamers leave anyway" check at
# src/overlay006/roamer_after_battle.c:55 -- so the two halves are not
# contiguous.  Only a battle-driven wave pays it; the item does both halves
# back to back inside RefreshRadarChain.  Verified against two hardware runs
# (notes/pokeradar.md attempt 2); a roamer actually sitting on the route costs
# more, via MoveRoamersOffMap.
ROAMER_CHECK_ADVANCES = 1

# GetGroundEncounterSlot, src/overlay006/wild_encounters.c:820-849
SLOT_CUTS = ((20, 0), (40, 1), (50, 2), (60, 3), (70, 4), (80, 5),
             (85, 6), (90, 7), (94, 8), (98, 9), (99, 10), (100, 11))
# Slots overwritten with the map's radar-exclusive species, but only when the
# patch shook hard (src/overlay006/wild_encounters.c:695-700).
RADAR_SLOTS = (4, 5, 10, 11)

# ShouldGetRandomEncounter, src/overlay006/wild_encounters.c:750-779
FLAT_RATE = 40                         # +30 cycling or in very tall grass
GRACE_PASS = 5                         # the grace roll must land under this to go on
# Platinum's land_rate is one of 5 / 10 / 15 / 30 / 35 (res/field/encounters/*.json):
# 30 for almost every route, 10 for Routes 227 and 228, 35 for the Great Marsh, the
# rest caves and interiors.  Abilities, flutes and a Cleanse Tag scale it further, and
# the scaled value drives both the rate roll and the grace threshold.
DEFAULT_RATE = 30


def slot_for_roll(roll):
    for cut, slot in SLOT_CUTS:
        if roll < cut:
            return slot
    return 11


def grace_threshold(rate):
    """GracePeriodStepsUsed, src/overlay006/wild_encounters.c:798-809."""
    return 8 - min(((rate << 8) // 10) >> 8, 8)


def ring_tile(ring, roll):
    """Index `roll` into ring `ring`'s perimeter -> local (x, z).  src/pokeradar.c:104-129."""
    side = 9 - ring * 2
    band = roll // side
    if band == 0:                                   # top row, left to right
        return ring + roll % side, ring
    if band == 1:                                   # bottom row, left to right
        return ring + roll % side, ring + side - 1
    rest = roll - side * 2                          # the side columns, descending
    z = ring + rest // 2 + 1
    x = ring if rest % 2 == 0 else ring + side - 1
    return x, z


def shiny_rate(chain_count):
    """src/pokeradar.c:466-481.  A chain of 0 never rolls at all."""
    return max(200, 8200 - chain_count * 200)


# --- the walk ---------------------------------------------------------------
# One field input -- a step OR a turn, since Field_CheckWildEncounter hangs off
# input->endMovement (field_control.c:227), which a turn sets too
# (player_move.c:386-396).  The encounter check's verdict is irrelevant on a
# patch tile: PokeRadar_ShouldDoRadarEncounter forces the encounter either way
# (wild_encounters.c:279-285), so only the short-circuits decide how many rolls
# get drawn before the slot roll.
PLAIN, BREAK, CONTINUE = None, "break", "continue"


def field_input(rng, attempts, rate, flat=FLAT_RATE, patch=PLAIN, static=False):
    """Draws one input's rolls.  Returns (attempts, slot or None).

    patch=PLAIN     plain grass: the slot roll happens only if the check passed, and
                    Repel is assumed to block the battle it would have started.
    patch=BREAK     a chain-breaking patch: the slot roll always happens.
    patch=CONTINUE  a chain-continuing patch: no slot roll at all, since
                    CreateWildMon_FromRadarKeepChain copies the chain's species.

    An input that gets as far as `gettingEncounter` -- the check passed, or you are on a
    patch -- falls through to `encounterAttempts = 0` at wild_encounters.c:375, which is
    NOT inside the `if`, so even a Repel-blocked encounter re-arms the grace period.  An
    input whose check failed returns early at :287-289 and leaves the counter alone."""
    passed = True
    if attempts < grace_threshold(rate):
        attempts += 1
        if rng.rand_mod(100) >= GRACE_PASS:
            passed = False
    if passed:
        if rng.rand_mod(100) >= flat:
            passed = False
        elif rng.rand_mod(100) >= rate:
            passed = False
    if patch is CONTINUE:
        return 0, None
    if passed or patch is BREAK:
        # A lead with Static (or Magnet Pull) makes TryGetSlotForTypeMatchAbility roll a
        # RandMod(2) before the slot roll (wild_encounters.c:1319).  On a table with no
        # matching type -- Route 226 has no Electric or Steel -- ForceMatchingTypeEncounterSlot
        # returns at :1308 without rolling, so the cost is exactly one advance and the slot
        # is unaffected.  KeepChain never reaches this, so a continuing patch pays nothing.
        if static:
            rng.rand_mod(2)
        return 0, slot_for_roll(rng.rand_mod(100))
    return attempts, None


def generate_pid(rng):
    """GetNatureForWildMon, then sub_02074044's rejection loop (src/pokemon.c:497-499).
    Species-independent: the loop only compares against the nature it just rolled."""
    nature = rng.rand_mod(25)
    while True:
        pid = rng.next16() | (rng.next16() << 16)
        if pid % 25 == nature:
            return pid


WALK_STEPS = 12
STEP_GROUP = 3


def walk_cumulative(state, attempts, rate, static=False, steps=WALK_STEPS):
    """Advances consumed after each of the first `steps` inputs, cumulative."""
    rng = Lcrng(state)
    totals = []
    for _ in range(steps):
        attempts, _ = field_input(rng, attempts, rate, static=static)
        totals.append(rng.calls)
    return totals


def walk_text(totals, group=STEP_GROUP, offset=0):
    parts = [" ".join(str(n + offset) for n in totals[i:i + group])
             for i in range(0, len(totals), group)]
    return " | ".join(parts)


def slot_on_entry(state, attempts, rate, static=False):
    """Stepping onto the patch from `state`: (slot, advances that step spends).

    The cost is never 1 -- the flat roll (or the grace roll that short-circuits it) is
    unconditional and the forced slot roll follows it -- so it is 2 or 3 past the grace
    period, and up to 4 inside it."""
    rng = Lcrng(state)
    _, slot = field_input(rng, attempts, rate, patch=BREAK, static=static)
    return slot, rng.calls


SLOT_PAGES = 5
_SLOT_CACHE = {}


def slot_entries(state, attempts, rate, static=False, count=SLOT_PAGES, limit=1 << 16):
    """For each encounter slot, the first `count` advance counts X such that
    performing X advances and then stepping onto the patch yields that slot.  The
    final step draws its own 1-2 encounter-check rolls before the slot roll, which
    is why this is a forward simulation rather than a search for a roll value.  Each hit
    is (advances before the step, advances the step itself spends)."""
    found = {slot: [] for slot in range(len(SLOT_CUTS))}
    wanted = len(found) * count
    current = state & MASK
    for x in range(limit):
        slot, cost = slot_on_entry(current, attempts, rate, static)
        hits = found[slot]
        if len(hits) < count:
            hits.append((x, cost))
            wanted -= 1
            if not wanted:
                break
        current = (current * MULTIPLIER + INCREMENT) & MASK
    return found


def slot_entries_cached(state, attempts, rate, static=False, count=SLOT_PAGES):
    """Redraws re-ask for the same state constantly; the scan is not free."""
    key = (state, attempts, rate, static, count)
    if key not in _SLOT_CACHE:
        if len(_SLOT_CACHE) > 256:
            _SLOT_CACHE.clear()
        _SLOT_CACHE[key] = slot_entries(state, attempts, rate, static, count)
    return _SLOT_CACHE[key]


PID_LIMIT = 1000                       # X in 0..999, per the tool's brief


def pid_hits(state, attempts, rate, target, static=False, limit=PID_LIMIT, most=6):
    """Advance counts X within `limit` where stepping onto the patch generates `target`.

    Tagged by which patch you step into, because that changes the roll sequence: "c" for
    a chain-continuing patch (check rolls, then straight to the nature roll) and "/N" for
    a chain-breaking one (check rolls, slot roll N, then the nature roll)."""
    hits = []
    current = state & MASK
    for x in range(limit):
        for patch in (CONTINUE, BREAK):
            rng = Lcrng(current)
            _, slot = field_input(rng, attempts, rate, patch=patch, static=static)
            if generate_pid(rng) == target:
                hits.append((x, "c" if patch is CONTINUE else "/%d" % slot))
                if len(hits) >= most:
                    return hits
        current = (current * MULTIPLIER + INCREMENT) & MASK
    return hits


class Patch:
    def __init__(self, ring, roll, x, z, active):
        self.ring = ring
        self.roll = roll
        self.x = x
        self.z = z
        self.active = active
        self.continues = None
        self.continue_roll = None
        self.shake = None
        self.shake_roll = None
        self.shiny = False
        self.shiny_roll = None

    @property
    def offset(self):
        return self.x - CENTRE, self.z - CENTRE

    @property
    def distance(self):
        dx, dz = self.offset
        return max(abs(dx), abs(dz))


class Wave:
    def __init__(self, seed, advances, chain_count, on_grass, source=CAPTURE,
                 chain_hard=True, battle_gap=ROAMER_CHECK_ADVANCES):
        rng = Lcrng(seed)
        for _ in range(advances):
            rng.step()
        self.start_state = rng.state

        # RadarSpawnPatches: one roll per ring whether or not the tile is grass.
        self.patches = []
        for ring in range(4):
            roll = rng.rand_mod(RING_PERIMETER[ring])
            x, z = ring_tile(ring, roll)
            self.patches.append(Patch(ring, roll, x, z, on_grass[ring]))

        # A wave at chain 0 can only come from the radar item, and that path hardcodes
        # BATTLE_RESULT_WIN (src/pokeradar.c:437) -- the capture boost is unreachable.
        if chain_count == 0:
            source = ITEM
        self.source = source
        self.gap = battle_gap if source in (FAINT, CAPTURE) else 0
        for _ in range(self.gap):
            rng.next16()

        rates = RATES_CAPTURED if source == CAPTURE else RATES_FAINTED
        # RadarChain_Clear leaves a fresh chain shaking soft (src/pokeradar.c:78).
        chain_shake = HARD if (chain_hard and chain_count) else SOFT

        # SetupGrassPatches: live patches only, in ring order.
        for patch in self.patches:
            if not patch.active:
                continue
            patch.continue_roll = rng.rand_mod(100)
            patch.continues = patch.continue_roll < rates[patch.ring]
            if patch.continues:
                patch.shake = chain_shake          # copied from the chain, no roll
                if chain_count:
                    rate = shiny_rate(chain_count)
                    patch.shiny_roll = (rate, rng.rand_mod(rate))
                    patch.shiny = patch.shiny_roll[1] == 0
            else:
                patch.shake_roll = rng.rand_mod(100)
                patch.shake = SOFT if patch.shake_roll < 50 else HARD

        self.end_state = rng.state
        self.calls = rng.calls
        self.end_advance = advances + rng.calls   # every advance past the prefix is a roll
        self.rates = rates
        self.chain_count = chain_count
        self.chain_shake = chain_shake
        self.live = [p for p in self.patches if p.active]


# --- rendering --------------------------------------------------------------
GRID_LEFT = 4
GRID_TOP = 3
CELL = 3
PANEL = GRID_LEFT + 4 + 9 * CELL + 3
CELL_WIDTH = 19                        # "slot  0     8 (+2)"
SLOT_COLUMN = CELL_WIDTH + 2           # one slot cell, plus a gap

(PAIR_SOFT, PAIR_HARD, PAIR_SHINY, PAIR_OFF, PAIR_PLAYER, PAIR_DIM, PAIR_RADAR,
 PAIR_TOGGLE) = range(1, 9)


def cell_for(patch):
    """Three characters, so the glyph alone carries the state without colour."""
    if not patch.active:
        return "(%d)" % patch.ring, PAIR_OFF
    if patch.shiny:
        return "*%d*" % patch.ring, PAIR_SHINY
    pair = PAIR_HARD if patch.shake == HARD else PAIR_SOFT
    return " %d " % patch.ring, pair


def describe(patch):
    if not patch.active:
        return "not grass -- no patch (its spawn roll is still spent)"
    shake = "SHINY, shakes %s" % patch.shake if patch.shiny else "shakes %s" % patch.shake
    return "%s -- %s" % (shake, "continues the chain" if patch.continues else "BREAKS the chain")


def source_label(wave):
    if wave.source == ITEM:
        return "radar use"
    return "a %s" % wave.source


def roll_log(patch, wave):
    """The rolls that produced this patch, in the order the ROM drew them."""
    bits = ["spawn %d/%d" % (patch.roll, RING_PERIMETER[patch.ring])]
    if patch.active:
        bits.append("cont %d%s%d" % (
            patch.continue_roll, "<" if patch.continues else ">=", wave.rates[patch.ring]))
        if patch.shake_roll is not None:
            bits.append("shake %d" % patch.shake_roll)
        if patch.shiny_roll is not None:
            bits.append("shiny %d/%d" % (patch.shiny_roll[1], patch.shiny_roll[0]))
    return "  ".join(bits)


def slot_rows(wave, page, attempts, rate, static=False):
    """Six rows of two (slot, advances) pairs each, for one page of the overlay."""
    reach = slot_entries_cached(wave.end_state, attempts, rate, static)

    def hit(slot):
        hits = reach[slot]
        return (slot,) + (hits[page] if page < len(hits) else (None, None))

    return [(hit(n), hit(n + 6)) for n in range(6)]


def page_header(page, absolute=False):
    left = "<--" if page > 0 else "   "
    right = "-->" if page < SLOT_PAGES - 1 else "   "
    return "%s  %s %d/%d %s" % (
        "frame to step in at" if absolute else "advances before stepping in",
        left, page + 1, SLOT_PAGES, right)


def pid_text(wave, target, attempts, rate, static=False, offset=0):
    hits = pid_hits(wave.end_state, attempts, rate, target, static)
    found = "  ".join("%d%s" % (x + offset, tag) for x, tag in hits) if hits else (
        "none within %d" % PID_LIMIT)
    return "PID %#010x  %s" % (target, found)


def slot_cell(slot, advances, cost, offset=0):
    """`cost - 1` is the step's advances past the first, shown as (+N)."""
    if advances is None:
        return "slot %2d%s %5s     " % (slot, "*" if slot in RADAR_SLOTS else " ", "--")
    return "slot %2d%s %5d (+%d)" % (slot, "*" if slot in RADAR_SLOTS else " ",
                                     advances + offset, cost - 1)


class Ui:
    def __init__(self, seed, advances, chain, on_grass, source=CAPTURE, chain_hard=True,
                 overlay=False, rate=DEFAULT_RATE, attempts=0,
                 battle_gap=ROAMER_CHECK_ADVANCES, static=False):
        self.seed = seed
        self.advances = advances
        self.chain = chain
        self.on_grass = list(on_grass)
        self.source = source
        self.chain_hard = chain_hard
        self.overlay = overlay
        self.rate = rate
        self.attempts = grace_threshold(rate) if attempts is None else attempts
        self.battle_gap = battle_gap
        self.static = static
        self.page = 0               # which of the SLOT_PAGES hits the overlay shows
        self.target_pid = None      # None, or a PID the overlay hunts for
        self.absolute = False       # frame numbers absolute from the seed, not from the wave
        self.prompt = None          # None, or the digits typed so far
        self.prompt_kind = "advance"
        self.message = ""

    def offset(self, wave):
        """What to add to a relative advance count to make it an absolute frame."""
        return wave.end_advance if self.absolute else 0

    def wave(self):
        return Wave(self.seed, self.advances, self.chain, self.on_grass,
                    self.source, self.chain_hard, self.battle_gap)

    # -- drawing
    def draw(self, scr):
        scr.erase()
        height, width = scr.getmaxyx()
        if height < 24 or width < 64:
            self._put(scr, 0, 0, "need a terminal of at least 64x24 (have %dx%d)" % (width, height))
            scr.refresh()
            return

        wave = self.wave()
        self._header(scr, wave)
        self._grid(scr, wave)
        if self.overlay:
            self._slots(scr, wave)
        else:
            self._legend(scr, wave)
        self._footer(scr, wave, height)
        scr.refresh()

    def _put(self, scr, y, x, text, attr=0):
        height, width = scr.getmaxyx()
        if not 0 <= y < height or x >= width:
            return
        scr.addnstr(y, x, text, max(0, width - x - 1), attr)

    def _header(self, scr, wave):
        self._put(scr, 0, 0, "Poke Radar patches -- seed %#010x" % self.seed, curses.A_BOLD)
        # Values a keypress changes are drawn in PAIR_TOGGLE; the rest is dim.
        live = self._pair(PAIR_TOGGLE) | curses.A_BOLD
        dim = self._pair(PAIR_DIM)
        grace = ("used" if self.attempts >= grace_threshold(self.rate)
                 else "%d left" % (grace_threshold(self.rate) - self.attempts))
        self._row(scr, 1, 0, [
            ("advance ", dim), ("%-6d" % self.advances, live),
            ("  state %#010x    chain " % wave.start_state, dim),
            ("%-4d" % self.chain, live), ("%-5s" % wave.chain_shake, live),
            (" after ", dim), ("%-10s" % source_label(wave), live),
            ("  rate %d  grace %s  lead " % (self.rate, grace), dim),
            ("%-11s" % ("Static" if self.static else "no ability"), live),
            (" frames ", dim), ("%-8s" % ("ABSOLUTE" if self.absolute else "relative"), live),
        ])

    def _row(self, scr, y, x, parts):
        for text, attr in parts:
            self._put(scr, y, x, text, attr)
            x += len(text)

    def _grid(self, scr, wave):
        by_tile = {(p.x, p.z): p for p in wave.patches}
        header = "".join("%3s" % ("%+d" % (x - CENTRE)) for x in range(9))
        self._put(scr, GRID_TOP - 1, GRID_LEFT + 4, header, self._pair(PAIR_DIM))
        for z in range(9):
            row = GRID_TOP + z
            self._put(scr, row, GRID_LEFT, "%3s " % ("%+d" % (z - CENTRE)), self._pair(PAIR_DIM))
            for x in range(9):
                col = GRID_LEFT + 4 + x * CELL
                if (x, z) == (CENTRE, CENTRE):
                    self._put(scr, row, col, " P ", self._pair(PAIR_PLAYER) | curses.A_BOLD)
                elif (x, z) in by_tile:
                    text, pair = cell_for(by_tile[(x, z)])
                    self._put(scr, row, col, text, self._pair(pair) | curses.A_BOLD)
                else:
                    self._put(scr, row, col, " . ", self._pair(PAIR_DIM))

    def _legend(self, scr, wave):
        self._put(scr, GRID_TOP - 1, PANEL, "patch  tile    d  cont%  state", self._pair(PAIR_DIM))
        for patch in wave.patches:
            dx, dz = patch.offset
            text, pair = cell_for(patch)
            row = GRID_TOP + patch.ring * 2
            self._put(scr, row, PANEL, "%s  %+d,%+d  %d  %3d%%  " % (
                text, dx, dz, patch.distance, wave.rates[patch.ring]),
                self._pair(pair) | curses.A_BOLD)
            self._put(scr, row, PANEL + 22, describe(patch), self._pair(pair))
            self._put(scr, row + 1, PANEL + 4, roll_log(patch, wave), self._pair(PAIR_DIM))

    def _slots(self, scr, wave):
        self._put(scr, GRID_TOP - 1, PANEL, page_header(self.page, self.absolute),
                  self._pair(PAIR_DIM))
        for offset, row_slots in enumerate(
                slot_rows(wave, self.page, self.attempts, self.rate, self.static)):
            for column, entry in enumerate(row_slots):
                pair = PAIR_RADAR if entry[0] in RADAR_SLOTS else PAIR_SOFT
                self._put(scr, GRID_TOP + offset, PANEL + column * SLOT_COLUMN,
                          slot_cell(*entry, offset=self.offset(wave)), self._pair(pair))
        if self.target_pid is not None:
            self._put(scr, GRID_TOP + 6, PANEL, pid_text(
                wave, self.target_pid, self.attempts, self.rate, self.static,
                self.offset(wave)),
                self._pair(PAIR_TOGGLE) | curses.A_BOLD)

    def _footer(self, scr, wave, height):
        row = GRID_TOP + 9 + 1
        if not wave.live:
            self._put(scr, row, GRID_LEFT, "no live patches -- the radar fails and clears the chain",
                      self._pair(PAIR_HARD) | curses.A_BOLD)
        else:
            self._put(scr, row, GRID_LEFT, ("landed on frame %d (%d rolls), state %#010x" % (
                wave.end_advance, wave.calls, wave.end_state)) if self.absolute else (
                "%d roll%s consumed, state %#010x" % (
                    wave.calls, "" if wave.calls == 1 else "s", wave.end_state)))
        row += 1
        if self.chain == 0:
            self._put(scr, row, GRID_LEFT,
                      "chain 0: no shiny rolls, the item's fixed rates, a soft chain, and the first "
                      "encounter starts a chain whichever patch you enter", self._pair(PAIR_DIM))
        else:
            self._put(scr, row, GRID_LEFT,
                      "shiny odds on a continuing patch: 1/%d" % shiny_rate(self.chain),
                      self._pair(PAIR_DIM))
        if self.overlay:
            row += 1
            totals = walk_cumulative(wave.end_state, self.attempts, self.rate, self.static)
            self._put(scr, row, GRID_LEFT, "steps  " + walk_text(
                totals, offset=self.offset(wave)), self._pair(PAIR_PLAYER))
            row += 1
            self._put(scr, row, GRID_LEFT,
                      ("frame you are on after each input; a turn counts" if self.absolute
                       else "cumulative advances per input; a turn counts; journal the rest, "
                            "then step in"), self._pair(PAIR_DIM))
            row += 1
            self._put(scr, row, GRID_LEFT,
                      "(+N) = the step into the patch spends N advances past the first, so "
                      "(+1) = 2 in total", self._pair(PAIR_DIM))
            row += 1
            self._put(scr, row, GRID_LEFT,
                      "the slot roll only happens on a chain-BREAKING patch, and * slots need "
                      "a hard one", self._pair(PAIR_DIM))
            if self.target_pid is not None:
                row += 1
                self._put(scr, row, GRID_LEFT,
                          "PID row: advances to perform, c = stepping onto a continuing patch, "
                          "/N = onto a breaking patch that rolls slot N", self._pair(PAIR_DIM))

        if self.prompt is not None:
            self._put(scr, height - 3, GRID_LEFT, "%s: %s_  (enter to %s, esc to cancel)" % (
                "target PID (hex)" if self.prompt_kind == "pid" else "advance count",
                self.prompt, "search, empty to clear" if self.prompt_kind == "pid" else "set"),
                curses.A_BOLD)
        elif self.message:
            self._put(scr, height - 3, GRID_LEFT, self.message, self._pair(PAIR_DIM))
        moves = ("h/j/left/down prev page   k/l/right/up next page" if self.overlay
                 else "h/j/left/down -1   k/l/right/up +1")
        self._put(scr, height - 2, GRID_LEFT,
                  "0-3 grass   %s   enter set   -/+ chain   c type   r source   s lead   "
                  "a frames   tab slots   P pid   q quit" % moves, self._pair(PAIR_DIM))

    def _pair(self, index):
        return curses.color_pair(index) if curses.has_colors() else 0

    # -- input
    def handle(self, key):
        """Returns False to quit."""
        if self.prompt is not None:
            return self._handle_prompt(key)

        if key in (ord("q"), ord("Q"), 27):
            return False
        if key in (curses.KEY_LEFT, curses.KEY_DOWN, ord("h"), ord("H"), ord("j"), ord("J")):
            if self.overlay:
                self.page = max(0, self.page - 1)
            else:
                self.advances = max(0, self.advances - 1)
        elif key in (curses.KEY_RIGHT, curses.KEY_UP, ord("k"), ord("K"), ord("l"), ord("L")):
            if self.overlay:
                self.page = min(SLOT_PAGES - 1, self.page + 1)
            else:
                self.advances += 1
        elif key in (curses.KEY_ENTER, 10, 13):
            self.prompt, self.prompt_kind = "", "advance"
        elif key in (ord("p"), ord("P")):
            self.prompt, self.prompt_kind = "", "pid"
            if not self.overlay:
                self.overlay = True
        elif key in (ord("-"), ord("_")):
            self.chain = max(0, self.chain - 1)
        elif key in (ord("+"), ord("=")):
            self.chain = min(999, self.chain + 1)
        elif key in (ord("c"), ord("C")):
            self.chain_hard = not self.chain_hard
            if self.chain == 0:
                self.message = ("a chain of 0 always shakes soft: RadarChain_Clear resets the "
                                "type, so this takes effect from chain 1")
                return True
        elif key in (ord("r"), ord("R")):
            self.source = SOURCES[(SOURCES.index(self.source) + 1) % len(SOURCES)]
            if self.chain == 0:
                self.message = ("only the radar item can set up a chain-0 wave, so it hardcodes "
                                "the faint rates and skips the roamer roll")
                return True
        elif key in (ord("s"), ord("S")):
            self.static = not self.static
        elif key in (ord("a"), ord("A")):
            self.absolute = not self.absolute
        elif key == ord("\t"):
            self.overlay = not self.overlay
        elif ord("0") <= key <= ord("3"):
            ring = key - ord("0")
            self.on_grass[ring] = not self.on_grass[ring]
        else:
            return True
        self.message = ""
        return True

    def _handle_prompt(self, key):
        pid_mode = self.prompt_kind == "pid"
        if key == 27:
            self.prompt = None
        elif key in (curses.KEY_ENTER, 10, 13):
            if pid_mode:
                # An empty entry clears the target rather than searching for nothing.
                self.target_pid = int(self.prompt, 16) & MASK if self.prompt.strip("xX") else None
            elif self.prompt:
                self.advances = int(self.prompt)
            self.prompt = None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.prompt = self.prompt[:-1]
        elif len(self.prompt) < 10 and chr(key) in (
                "0123456789abcdefABCDEFxX" if pid_mode else "0123456789"):
            self.prompt += chr(key)
        return True


def run(scr, ui):
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(PAIR_SOFT, curses.COLOR_CYAN, -1)
        curses.init_pair(PAIR_HARD, curses.COLOR_RED, -1)
        curses.init_pair(PAIR_SHINY, curses.COLOR_MAGENTA, -1)
        curses.init_pair(PAIR_OFF, curses.COLOR_BLUE, -1)
        curses.init_pair(PAIR_PLAYER, curses.COLOR_GREEN, -1)
        curses.init_pair(PAIR_DIM, curses.COLOR_WHITE, -1)
        curses.init_pair(PAIR_RADAR, curses.COLOR_YELLOW, -1)
        curses.init_pair(PAIR_TOGGLE, curses.COLOR_YELLOW, -1)
    scr.keypad(True)
    while True:
        ui.draw(scr)
        try:
            key = scr.getch()
        except KeyboardInterrupt:
            return
        if key == curses.KEY_RESIZE:
            continue
        if not ui.handle(key):
            return


def render_plain(ui):
    """One frame as plain text -- for testing without a terminal."""
    wave = ui.wave()
    out = ["seed %#010x  advance %d  state %#010x  chain %d %s  after %s  rate %d  grace %s" % (
        ui.seed, ui.advances, wave.start_state, ui.chain, wave.chain_shake,
        source_label(wave), ui.rate,
        "used" if ui.attempts >= grace_threshold(ui.rate) else "%d left" % (
            grace_threshold(ui.rate) - ui.attempts)), ""]
    out[0] += "  lead %s  frames %s" % (
        "Static" if ui.static else "no ability", "ABSOLUTE" if ui.absolute else "relative")
    by_tile = {(p.x, p.z): p for p in wave.patches}
    out.append("    " + "".join("%3s" % ("%+d" % (x - CENTRE)) for x in range(9)))
    for z in range(9):
        row = "%3s " % ("%+d" % (z - CENTRE))
        for x in range(9):
            if (x, z) == (CENTRE, CENTRE):
                row += " P "
            elif (x, z) in by_tile:
                row += cell_for(by_tile[(x, z)])[0]
            else:
                row += " . "
        out.append(row)
    out.append("")
    for patch in wave.patches:
        dx, dz = patch.offset
        out.append("%s %+d,%+d  d%d  %3d%%  %s" % (
            cell_for(patch)[0], dx, dz, patch.distance,
            wave.rates[patch.ring], describe(patch)))
        out.append("        " + roll_log(patch, wave))
    out.append("")
    if not wave.live:
        out.append("no live patches -- the radar fails and clears the chain")
    else:
        out.append(("landed on frame %d (%d rolls), state %#010x" % (
            wave.end_advance, wave.calls, wave.end_state)) if ui.absolute else (
            "%d rolls consumed, state %#010x" % (wave.calls, wave.end_state)))
    if ui.overlay:
        off = ui.offset(wave)
        out += ["", "%s   * = radar-exclusive" % page_header(ui.page, ui.absolute)]
        for left, right in slot_rows(wave, ui.page, ui.attempts, ui.rate, ui.static):
            out.append("    %s  %s" % (slot_cell(*left, offset=off),
                                       slot_cell(*right, offset=off)))
        out.append("    (+N) = the step into the patch spends N advances past the first")
        if ui.target_pid is not None:
            out.append("    " + pid_text(
                wave, ui.target_pid, ui.attempts, ui.rate, ui.static, off))
        out += ["", "steps  " + walk_text(
            walk_cumulative(wave.end_state, ui.attempts, ui.rate, ui.static), offset=off)]
    return "\n".join(out)


def parse_seed(text):
    try:
        return int(text, 0) & MASK
    except ValueError:
        return int(text, 16) & MASK


def main():
    parser = argparse.ArgumentParser(
        description="Poke Radar patch viewer for DPPt.",
        epilog="keys: 0-3 toggle grass, h/j/left/down -1 advance, k/l/right/up +1 "
               "(they page the overlay while it is up), enter to type an advance count, "
               "-/+ chain count, c chain shake type, r wave source, tab slot overlay, q quit")
    parser.add_argument("seed", type=parse_seed, help="seed, e.g. 0xED0203EF")
    parser.add_argument("--advances", type=int, default=0, help="LCRNG advances before generation")
    parser.add_argument("--chain", type=int, default=0, help="current chain count (default 0)")
    shake = parser.add_mutually_exclusive_group()
    shake.add_argument("--hard", dest="soft", action="store_false", default=False,
                       help="the chain shakes hard (the default; only applies at chain 1+)")
    shake.add_argument("--soft", dest="soft", action="store_true",
                       help="the chain shakes soft instead")
    parser.add_argument("--source", choices=SOURCES, default=CAPTURE,
                        help="what set this wave up: a capture (the default: boosted rates), "
                             "a battle you won (faint), or the radar item (no roamer roll). "
                             "Forced to item at chain 0")
    parser.add_argument("--no-grass", default="", metavar="RINGS",
                        help="rings whose tile is not grass, e.g. 23")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, metavar="N",
                        help="the map's land encounter rate (default %d, Route 226)" % DEFAULT_RATE)
    parser.add_argument("--attempts", type=int, default=0, metavar="N",
                        help="encounterAttempts at the start of the walk; default 0, a fresh "
                             "grace period, which is what field_map_change.c:301 leaves on a "
                             "load and what all five recorded encounters show")
    parser.add_argument("--static", action="store_true",
                        help="the lead has Static or Magnet Pull: one extra roll before the "
                             "slot roll on a chain-breaking patch")
    parser.add_argument("--battle-gap", type=int, default=ROAMER_CHECK_ADVANCES, metavar="N",
                        help="advances between a battle-driven wave's spawn and setup rolls "
                             "(default %d, the roamer check)" % ROAMER_CHECK_ADVANCES)
    parser.add_argument("--absolute", action="store_true",
                        help="show frame numbers absolute from the seed, not relative to "
                             "the end of the wave")
    parser.add_argument("--slots", action="store_true",
                        help="start with the encounter-slot overlay showing")
    parser.add_argument("--page", type=int, default=1, metavar="N",
                        help="which overlay page (1-%d) to start on" % SLOT_PAGES)
    parser.add_argument("--pid", type=lambda t: int(t, 16) & MASK, default=None, metavar="HEX",
                        help="target PID for the overlay's search row, e.g. E9375A48")
    parser.add_argument("--print", action="store_true", dest="plain",
                        help="print one frame and exit instead of starting the TUI")
    args = parser.parse_args()

    on_grass = [str(ring) not in args.no_grass for ring in range(4)]
    ui = Ui(args.seed, max(0, args.advances), max(0, min(999, args.chain)), on_grass,
            args.source, not args.soft, args.slots, max(1, args.rate),
            args.attempts, max(0, args.battle_gap), args.static)
    ui.page = max(0, min(SLOT_PAGES - 1, args.page - 1))
    ui.target_pid = args.pid
    ui.absolute = args.absolute

    if args.plain:
        print(render_plain(ui))
        return
    curses.wrapper(run, ui)


if __name__ == "__main__":
    main()
