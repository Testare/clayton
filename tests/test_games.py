"""Which game a profile is, and the gating that finally follows from it.

Before Platinum, `Profile.version` was a free-text display name that nothing branched on, while
`battle_compass/targets.py` hardcoded SoulSilver's rows for the two version-split encounters — so
a HeartGold player was silently simulated against the wrong four moves. These tests pin the two
things that stops happening by accident again:

* the field stores a **key**, not a display name, so it is branchable;
* every stored spelling of the old field still resolves, so no profile needs rewriting.
"""
import unittest

from app.models import Profile
from claytonlib.games import (
    ALL_TOOLS, GAMES, SIGNAL_FLIPS_PITCH, SIGNAL_ROAMERS_ELM, TOOL_EXPEDITIONS, TOOL_GLASS,
    TOOL_HUNTS, canonical_game_key, game, game_keys, game_name, tool_refusal,
)


class TestRegistry(unittest.TestCase):

    def test_the_five_gen_four_games_are_present(self):
        self.assertEqual(game_keys(),
                         ("heartgold", "soulsilver", "platinum", "diamond", "pearl"))

    def test_hgss_identifies_seed_a_by_roamers_and_elm(self):
        for key in ("heartgold", "soulsilver"):
            self.assertEqual(game(key).seed_a_signal, SIGNAL_ROAMERS_ELM)
            self.assertFalse(game(key).uses_coin_flips)

    def test_platinum_and_dp_identify_seed_a_by_coin_flips(self):
        """DP share Platinum's RNG, which is why they are listed at all — the gap is data."""
        for key in ("platinum", "diamond", "pearl"):
            self.assertEqual(game(key).seed_a_signal, SIGNAL_FLIPS_PITCH)
            self.assertTrue(game(key).uses_coin_flips)

    def test_hgss_supports_every_tool(self):
        for key in ("heartgold", "soulsilver"):
            for tool in ALL_TOOLS:
                self.assertTrue(game(key).supports(tool), f"{key} / {tool}")

    def test_platinum_supports_glass_and_hunts_but_not_expeditions(self):
        platinum = game("platinum")
        self.assertTrue(platinum.supports(TOOL_GLASS))
        self.assertTrue(platinum.supports(TOOL_HUNTS))
        self.assertFalse(platinum.supports(TOOL_EXPEDITIONS))

    def test_diamond_and_pearl_support_nothing(self):
        for key in ("diamond", "pearl"):
            self.assertFalse(game(key).is_supported)
            self.assertEqual(game(key).tools, frozenset())
            self.assertTrue(game(key).unsupported_reason)

    def test_advance_actions_differ_and_both_bulk_units_are_two_advances(self):
        """Both games route the same way -- a blind 2-advance bulk action then a readable
        1-advance margin -- which is why `plan_advances`' arithmetic needed no change. Only the
        names differ (clayton-6xu.1.4, notes/platinum.md section 3.3)."""
        hgss, platinum = game("soulsilver"), game("platinum")
        self.assertEqual((hgss.bulk_action, hgss.margin_action), ("Chatot flip", "Elm call"))
        self.assertEqual((platinum.bulk_action, platinum.margin_action),
                         ("Journal flip", "Chatot cry"))
        self.assertEqual(hgss.bulk_advances, platinum.bulk_advances)
        self.assertEqual(platinum.bulk_advances, 2)


class TestCanonicalGameKey(unittest.TestCase):

    def test_keys_pass_through(self):
        for key in game_keys():
            self.assertEqual(canonical_game_key(key), key)

    def test_old_version_display_names_resolve(self):
        """The migration: `version` held a display name, and every stored one must still read."""
        self.assertEqual(canonical_game_key("HeartGold"), "heartgold")
        self.assertEqual(canonical_game_key("SoulSilver"), "soulsilver")

    def test_case_and_spacing_are_forgiven(self):
        for spelling in ("HEARTGOLD", "heart gold", "Heart-Gold", " heartgold "):
            self.assertEqual(canonical_game_key(spelling), "heartgold", spelling)

    def test_unset_is_empty_string(self):
        for blank in (None, "", "   "):
            self.assertEqual(canonical_game_key(blank), "")

    def test_an_unknown_game_raises_rather_than_reading_as_unset(self):
        """Treating a typo as "unset" is how a HeartGold profile ends up with SoulSilver's rows."""
        with self.assertRaises(ValueError):
            canonical_game_key("Crystal")

    def test_game_name_is_the_inverse(self):
        self.assertEqual(game_name("platinum"), "Platinum")
        self.assertEqual(game_name("HeartGold"), "HeartGold")
        self.assertEqual(game_name(""), "")


class TestToolRefusal(unittest.TestCase):

    def test_no_refusal_for_a_supported_pairing(self):
        self.assertEqual(tool_refusal("platinum", TOOL_GLASS), "")
        self.assertEqual(tool_refusal("soulsilver", TOOL_EXPEDITIONS), "")

    def test_expeditions_on_platinum_explains_why(self):
        reason = tool_refusal("platinum", TOOL_EXPEDITIONS)
        self.assertIn("Safari Zone", reason)
        self.assertIn("Glass and Hunts", reason)

    def test_diamond_gets_its_own_reason_for_every_tool(self):
        for tool in ALL_TOOLS:
            self.assertIn("not supported yet", tool_refusal("diamond", tool))

    def test_an_unset_game_refuses_nothing(self):
        """Every profile that predates the field has one, and they are all HGSS. Refusing them
        would lock existing players out of tools they were already using, to enforce a field they
        never filled in -- so the field is worth prompting for, not blocking on."""
        for tool in ALL_TOOLS:
            self.assertEqual(tool_refusal("", tool), "")
            self.assertEqual(tool_refusal(None, tool), "")

    def test_an_unknown_tool_raises(self):
        with self.assertRaises(ValueError):
            tool_refusal("platinum", "safari")


class TestProfileGame(unittest.TestCase):

    def test_profile_stores_the_key_and_renders_the_name(self):
        p = Profile(name="Plat", game="platinum")
        self.assertEqual(p.game, "platinum")
        self.assertEqual(p.game_name, "Platinum")

    def test_profile_round_trips_the_game(self):
        p = Profile(name="Plat", game="platinum")
        self.assertEqual(Profile.from_dict(p.to_dict()).game, "platinum")

    def test_a_profile_stored_with_the_old_version_field_migrates_on_read(self):
        """No data migration: the old spelling resolves at load, which is the whole point of
        `canonical_game_key` accepting display names."""
        legacy = {"name": "Old", "id": "abc", "version": "SoulSilver"}
        restored = Profile.from_dict(legacy)
        self.assertEqual(restored.game, "soulsilver")
        self.assertEqual(restored.game_name, "SoulSilver")

    def test_game_wins_over_version_when_both_are_present(self):
        """`to_dict` writes both (so an older build still names the game), so reads must prefer
        the key -- otherwise the display name would quietly win."""
        doc = {"name": "Both", "game": "platinum", "version": "SoulSilver"}
        self.assertEqual(Profile.from_dict(doc).game, "platinum")

    def test_to_dict_also_writes_the_display_name_for_older_builds(self):
        p = Profile(name="Plat", game="platinum")
        self.assertEqual(p.to_dict()["version"], "Platinum")

    def test_a_profile_with_no_game_round_trips_as_unset(self):
        p = Profile(name="Nothing set")
        self.assertEqual(p.game, "")
        self.assertEqual(p.game_name, "")
        self.assertEqual(Profile.from_dict(p.to_dict()).game, "")

    def test_an_unset_profile_defaults_to_the_hgss_signal_with_a_visible_hint(self):
        import tempfile
        from app.facade import Facade
        from app.store import FileStore
        api = Facade(FileStore(tempfile.mkdtemp()))
        created = api.create_profile({"name": "Legacy, no game"})
        signal = api.get_profile(created["id"])["seed_a_signal"]
        self.assertEqual(signal["kind"], SIGNAL_ROAMERS_ELM)
        self.assertIn("HeartGold/SoulSilver", signal["unset_hint"])

    def test_tool_refusal_reaches_the_registry(self):
        self.assertEqual(Profile(name="P", game="platinum").tool_refusal(TOOL_HUNTS), "")
        self.assertTrue(Profile(name="P", game="platinum").tool_refusal(TOOL_EXPEDITIONS))
        self.assertTrue(Profile(name="P", game="diamond").tool_refusal(TOOL_GLASS))


class TestGameThroughTheFacade(unittest.TestCase):
    """The surface the page actually calls."""

    def setUp(self):
        import tempfile
        from app.facade import Facade
        from app.store import FileStore
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_list_games_offers_all_five_with_their_support(self):
        rows = self.api.list_games()
        self.assertEqual([r["name"] for r in rows],
                         ["HeartGold", "SoulSilver", "Platinum", "Diamond", "Pearl"])
        by_key = {r["key"]: r for r in rows}
        self.assertTrue(by_key["platinum"]["is_supported"])
        self.assertEqual(by_key["platinum"]["tools"], ["glass", "hunts"])
        self.assertFalse(by_key["diamond"]["is_supported"])
        self.assertTrue(by_key["diamond"]["unsupported_reason"])

    def test_unsupported_games_are_listed_not_hidden(self):
        """A player who owns Diamond should be told why it is not ready, not left wondering
        whether the app has heard of it."""
        self.assertIn("diamond", [r["key"] for r in self.api.list_games()])

    def test_create_and_read_back_a_platinum_profile(self):
        created = self.api.create_profile({"name": "Plat", "game": "platinum"})
        self.assertEqual(created["game"], "platinum")
        self.assertEqual(created["game_name"], "Platinum")
        fetched = self.api.get_profile(created["id"])
        self.assertEqual(fetched["game"], "platinum")

    def test_create_accepts_a_display_name_too(self):
        created = self.api.create_profile({"name": "SS", "game": "SoulSilver"})
        self.assertEqual(created["game"], "soulsilver")

    def test_create_still_accepts_the_old_version_key(self):
        created = self.api.create_profile({"name": "Legacy", "version": "HeartGold"})
        self.assertEqual(created["game"], "heartgold")

    def test_update_changes_the_game(self):
        created = self.api.create_profile({"name": "P", "game": "soulsilver"})
        updated = self.api.update_profile(created["id"], {"name": "P", "game": "platinum"})
        self.assertEqual(updated["game"], "platinum")

    def test_get_profile_carries_tool_refusals_and_the_signal_descriptor(self):
        created = self.api.create_profile({"name": "Plat", "game": "platinum"})
        doc = self.api.get_profile(created["id"])
        self.assertEqual(doc["tool_refusals"]["glass"], "")
        self.assertEqual(doc["tool_refusals"]["hunts"], "")
        self.assertTrue(doc["tool_refusals"]["expeditions"])
        signal = doc["seed_a_signal"]
        self.assertEqual(signal["kind"], SIGNAL_FLIPS_PITCH)
        self.assertEqual(signal["bulk_action"], "Journal flip")
        self.assertEqual(signal["margin_action"], "Chatot cry")
        # The hygiene note is Platinum-only, and it is the one instruction a player cannot
        # recover from forgetting: a randomly-moving NPC spends an advance of its own.
        self.assertIn("menu", signal["hygiene_note"])
        self.assertIn("recorded cry", signal["hygiene_note"])

    def test_hgss_profile_has_no_hygiene_note_and_the_elm_signal(self):
        created = self.api.create_profile({"name": "SS", "game": "soulsilver"})
        signal = self.api.get_profile(created["id"])["seed_a_signal"]
        self.assertEqual(signal["kind"], SIGNAL_ROAMERS_ELM)
        self.assertEqual(signal["hygiene_note"], "")

    def test_list_profiles_shows_the_game_name(self):
        self.api.create_profile({"name": "Plat", "game": "platinum"})
        row = self.api.list_profiles()[0]
        self.assertEqual(row["game"], "platinum")
        self.assertEqual(row["game_name"], "Platinum")

    def test_creating_with_an_unknown_game_is_refused(self):
        with self.assertRaises(ValueError):
            self.api.create_profile({"name": "Nope", "game": "Crystal"})


if __name__ == "__main__":
    unittest.main()
