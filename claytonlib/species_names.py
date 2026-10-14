"""species_names.py — one spelling for a species, whatever the source called it.

Clayton joins species across data sets that each spell them differently:

* ``basedata/base_stats.json`` keys come from the decompilation's own ``SPECIES_*`` constants
  (``SPECIES_NIDORAN_F`` -> ``nidoran-f``, ``SPECIES_MR_MIME`` -> ``mr-mime``).
* ``basedata/safari_pokemon.json`` uses the same slugs, by hand.
* ``basedata/safari_zones.json`` is generated from a veekun species list, which offers both
  display names (``Nidoran♀``, ``Farfetch’d``, ``Mr. Mime``) and slug *identifiers*.

Joining a display name against a slug silently produced nothing, which is how four Gen-1
species became unhuntable in the app (clayton-69n): the Safari area tables said ``nidoran♀``
while every target list said ``nidoran-f``, so ``areas_for_species`` returned no areas at all
and no error said why. The fix is this module plus naming the generated data by identifier;
the normalizer stays because it costs nothing and means a name typed or pasted from anywhere
— a Pokedex page, Pokefinder, a spreadsheet — resolves.

The rule reproduces veekun's ``identifier`` column from its display name for **all 493** Gen 4
species, which is also what ``base_stats.json`` keys on (see tests/test_species_names.py; the
single divergence is Giratina, filed as ``giratina-altered`` because the file keys on PokeAPI's
default-form name).

This normalizes **spelling**, not **forms**: ``canonical_species_name("Giratina")`` is
``"giratina"``, and finding ``giratina-altered`` from that is the lookup's job (see
``claytonlib.battle.stats.species``, which falls back to a unique form-suffixed match).
"""
import re

#: Gender symbols the Pokedex uses where a slug carries a suffix.
_GENDER = {"♀": "-f", "♂": "-m"}
#: Punctuation a slug simply drops: apostrophes (straight and curly), periods, colons and
#: brackets. "Farfetch'd" -> farfetchd, "Mr. Mime" -> mr-mime, "Nidoran (F)" -> nidoran-f.
_DROP = re.compile(r"[.'’:()\[\]]")
_SEPARATORS = re.compile(r"[\s_]+")
_DASHES = re.compile(r"-{2,}")

#: Spellings no rule reaches, applied after the transform below.  ``farfetch-d`` renders the
#: apostrophe as a dash rather than dropping it, which is what safari_pokemon.json used to key
#: on before clayton-69n; it stays here so an expedition saved under the old spelling, or a
#: name copied out of older notes, still resolves.  Farfetch'd is the only Gen 4 species with
#: an apostrophe, so this is a list of one rather than a rule.
_ALIASES = {"farfetch-d": "farfetchd"}


def canonical_species_name(name) -> str:
    """The project's canonical slug for a species name, however it was spelled.

    Lower-cases, turns ``♀``/``♂`` into the ``-f``/``-m`` suffix the slugs use, drops
    apostrophes, periods, colons and brackets, collapses whitespace and underscores to single
    dashes, then applies ``_ALIASES`` for the one spelling no rule reaches. An already-canonical
    name is returned unchanged, so this is safe to apply at every lookup rather than only at
    the boundary.

        >>> canonical_species_name("Nidoran♀")
        'nidoran-f'
        >>> canonical_species_name("Farfetch’d")
        'farfetchd'
        >>> canonical_species_name("Mr. Mime")
        'mr-mime'
        >>> canonical_species_name("porygon-z")
        'porygon-z'
        >>> canonical_species_name("farfetch-d")   # the retired safari_pokemon.json key
        'farfetchd'
    """
    text = str(name).strip().lower()
    for symbol, suffix in _GENDER.items():
        text = text.replace(symbol, suffix)
    text = _DROP.sub("", text)
    text = _SEPARATORS.sub("-", text)
    text = _DASHES.sub("-", text).strip("-")
    return _ALIASES.get(text, text)


def species_names_equal(a, b) -> bool:
    """Whether two spellings name the same species (``"Nidoran♀"`` == ``"nidoran-f"``)."""
    return canonical_species_name(a) == canonical_species_name(b)


#: Slug -> Pokedex display name, for the five species dash-capitalising a slug gets wrong.
#: Checked exhaustively: for every other one of the 493, capitalising each dash-separated word
#: reproduces the display name exactly (tests/test_species_names.py).  The app's `capName`
#: mirrors this map, and a test asserts the two stay in step.
DISPLAY_OVERRIDES = {
    "nidoran-f": "Nidoran♀",
    "nidoran-m": "Nidoran♂",
    "farfetchd": "Farfetch’d",
    "mr-mime": "Mr. Mime",
    "mime-jr": "Mime Jr.",
}


def display_species_name(name) -> str:
    """The Pokedex spelling of a species, for showing a slug to a person.

    The inverse of ``canonical_species_name`` wherever one exists: ``"nidoran-f"`` ->
    ``"Nidoran♀"``, ``"metang"`` -> ``"Metang"``, ``"porygon-z"`` -> ``"Porygon-Z"``.  Round
    trips -- ``canonical_species_name(display_species_name(x)) == x`` for every species we
    carry.
    """
    key = canonical_species_name(name)
    if key in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[key]
    return "-".join(word[:1].upper() + word[1:] for word in key.split("-"))
