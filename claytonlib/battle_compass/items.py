"""The bag items a run can use, in one place.

Three consumers need to agree about these and used to disagree: the solver priced them, the
simulator hardcoded two token codes, and the run page offered none at all. A single table is the
only way "use a Hyper Potion" means the same thing to all three.

**Items cost zero RNG advances** (verified, sec 12.1), which is what makes them the cheapest entry
in the action alphabet. But they are not inert: a potion changes our HP, and the simulator has to
apply that or its predicted HP diverges from the real one and every candidate is contradicted on
the next report. That divergence was a real bug -- the simulator appended an item token and
healed nothing.

`heal` is in HP; ``None`` means "to full". `cures_status` clears a non-volatile status.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    price: int
    #: HP restored. 0 for a non-healing item, None for a full heal.
    heal: int | None = 0
    cures_status: bool = False
    #: Stat this raises, if any, as a (stat key, stages) pair.
    raises: tuple[str, int] | None = None

    @property
    def heals(self) -> bool:
        return self.heal is None or self.heal > 0


ITEMS: tuple[Item, ...] = (
    Item("p",   "Potion",        300,  heal=20),
    Item("sp",  "Super Potion",  700,  heal=50),
    Item("hp",  "Hyper Potion",  1200, heal=200),
    Item("mp",  "Max Potion",    2500, heal=None),
    Item("fh",  "Full Heal",     600,  cures_status=True),
    Item("fr",  "Full Restore",  3000, heal=None, cures_status=True),
    Item("xsd", "X Sp. Def",     350,  raises=("spd", 1)),
    Item("xd",  "X Defend",      550,  raises=("def", 1)),
    Item("gs",  "Guard Spec.",   700),
)

#: A Revive is deliberately NOT in `ITEMS`. Everything in that table is used on whoever is out
#: and is priced by the solver as a filler action; a Revive is used on a party member who is
#: *not* out, has its own ``R<slot>`` token, and the solver never plans one -- so putting it in
#: the table would offer it as a heal for the active Pokemon. The price is here because the run
#: record still totals what a run cost.
REVIVE_PRICE = 1500
#: A Revive restores half of max HP, rounded DOWN on an odd maximum. Not a Max Revive: a run
#: never needs one, and the two differ in exactly this number.
REVIVE_DIVISOR = 2


def revive_amount(max_hp: int) -> int:
    """The HP a Revive brings a fainted party member back on."""
    return max(1, max_hp // REVIVE_DIVISOR)


BY_CODE: dict[str, Item] = {item.code: item for item in ITEMS}
#: Prices only, for the solver's distance function.
PRICES: dict[str, int] = {item.code: item.price for item in ITEMS}


def item(code: str) -> Item:
    try:
        return BY_CODE[code]
    except KeyError:
        raise ValueError(f"unknown item code {code!r}; known: {sorted(BY_CODE)}") from None


def healing() -> tuple[Item, ...]:
    """The potions, weakest first — the order a heal tier is chosen in."""
    return tuple(i for i in ITEMS if i.heals and not i.cures_status) + (BY_CODE["fr"],)


def heal_amount(code: str, current_hp: int, max_hp: int) -> int:
    """HP this item actually restores, capped at the missing amount.

    Capped because over-healing is what the *player* sees: a Hyper Potion on a Pokemon missing
    30 HP restores 30, and a simulator that added 200 would predict an impossible HP.
    """
    entry = item(code)
    missing = max(0, max_hp - current_hp)
    if entry.heal is None:
        return missing
    return min(entry.heal, missing)


def smallest_heal_covering(missing: int) -> Item | None:
    """The cheapest potion that fully restores `missing` HP, or the largest if none does.

    The policy the design settled on: heal enough to be out of danger, without buying a Max
    Potion to top off 20 HP.
    """
    if missing <= 0:
        return None
    for entry in healing():
        if entry.heal is None or entry.heal >= missing:
            return entry
    return BY_CODE["mp"]
