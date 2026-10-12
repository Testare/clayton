"""Replay a hooh*.jsonl log through claytonlib's simulator and diff every turn.

The evidence behind notes/hooh_log_replay.md. Usage:
    PYTHONPATH=. python one-offs/hooh_log_replay.py data/battle_logs/hooh1.jsonl

ITEMS and BAG below are INFERRED from the logs, not read from the profile -- see sec 4 of the
note for why, and for what each one costs if it is wrong.

Turn boundaries come from the RNG stream, not the message stream: every turn opens with the
wild Pokemon's move-choice roll at 0x0225e46e (`select_target_move`), so the rolls between two
consecutive ones are exactly one turn's cost. The six before the first are the battle-start
advances.
"""
import json, re, sys

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move

CHOICE_ADDR = "0x0225e46e"
PROFILE = json.load(open("notes/e4c9ed8a4995.json"))["party"]
BY_SPECIES = {p["species"]: p for p in PROFILE}
TYPES = {"natu": ("Psychic", "Flying"), "chatot": ("Normal", "Flying"),
         "magneton": ("Electric", "Steel"), "ampharos": ("Electric",),
         "granbull": ("Normal",), "smeargle": ("Normal",)}
NICK = {"ADAMANT": "natu", "CHATOT": "chatot", "FLASHDRIVE": "ampharos",
        "SCARY DOG": "granbull", "MAGNETON": "magneton"}
ITEMS = {"ampharos": "Leftovers", "smeargle": "Silk Scarf", "magneton": "Choice Scarf"}
#: Silk Scarf INFERRED from False Swipe damage; Choice Scarf INFERRED from Magneton moving
#: first. Neither is in the exported profile -- held items live on the hunt party slot.
MOVES = {"natu": ("Peck",)}
ORDER = ["natu", "chatot", "ampharos", "granbull", "magneton", "smeargle"]
#: Turns whose action leaves no message at all -- a bag item. Read off the state change instead
#: and listed per log so the replay is explicit about what it assumed.
BAG = {
    "hooh2": {24: ("revive", "smeargle")},
    "hooh3": {13: ("revive", "granbull")},
}

def battler(species, slot):
    p = BY_SPECIES[species]
    moves = MOVES.get(species) or tuple(p["moveset"])
    return Battler(name=p["name"], level=p["level"], types=TYPES[species],
                   stats=dict(p["stats"]), moves=moves,
                   pp=tuple(resolve_move(m).pp for m in moves),
                   ability=p["ability"], held_item=ITEMS.get(species, ""), party_slot=slot)

def species_of(nick):
    """Nicknames, normalised. The emulator prints "SCARY DOG!" and "Go! SCARY DOG!!", and
    Smeargle's nickname comes through as mojibake -- so anything unrecognised is Smeargle."""
    return NICK.get(" ".join(nick.split()).upper().rstrip("!"), "smeargle")

def segment(recs):
    """[(intro, [turn, ...])] split on the move-choice roll."""
    marks = [i for i, r in enumerate(recs)
             if "roll" in r and r["roll"]["addr"] == CHOICE_ADDR]
    chunks = []
    for a, b in zip(marks, marks[1:] + [len(recs)]):
        chunks.append(recs[a:b])
    return recs[:marks[0]], chunks

USED = re.compile(r"^(.+?) used\s+(.+?)!", re.S)
SWITCH = re.compile(r"^(.+?), switch out!", re.S)
GO = re.compile(r"^(?:Go! |Your foe's weak!\s*Get 'em, )(.+?)!*$", re.S)

def read_action(msgs, ours_species, party, label, turn):
    if (label in BAG) and turn in BAG[label]:
        kind, who = BAG[label][turn]
        return Action.REVIVE, {"revive": who}, f"{kind} on {who} (inferred -- no message)"
    for m in msgs:
        if SWITCH.match(m):
            for g in msgs:
                gm = GO.match(g.strip())
                if gm:
                    return Action.SWITCH, {"incoming": species_of(gm.group(1))}, "switch"
    for m in msgs:
        if "used" in m and "Ball" in m:
            return Action.STANDARD_BALL, {}, "Poke Ball"
        mm = USED.match(m.strip())
        if mm and species_of(mm.group(1)) == ours_species:
            want = " ".join(mm.group(2).split()).lower().replace(" ", "")
            for i, mv in enumerate(party[ours_species].moves):
                if mv.lower().replace(" ", "") == want:
                    return [Action.MOVE_1, Action.MOVE_2, Action.MOVE_3,
                            Action.MOVE_4][i], {}, mv
            return None, {}, f"UNKNOWN MOVE {want!r} for {ours_species}"
    if any("Got away safely" in m for m in msgs):
        return None, {}, "fled -- run ends"
    if any("fainted" in m for m in msgs):
        return Action.FAINTED, {}, "fainted before moving"
    return None, {}, "NO ACTION FOUND (bag action with no message?)"


TARGET_MOVES = ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard")
SHAKES = ["Oh, no!", "Aww!", "Aargh!", "Gah!"]

def semantics(msgs, rendered, before, after):
    """Compare the MEANING of the turn, not just its cost: which move the target chose, how
    each side's move resolved, and a ball's shake count."""
    out = []
    joined = " | ".join(msgs)
    # 1. which move the wild Pokemon picked, and whether it moved at all
    named = None
    for m in msgs:
        if m.startswith("The wild HO-OH used"):
            want = " ".join(m.split("used")[1].split()).rstrip("!").lower().replace(" ", "")
            for i, mv in enumerate(TARGET_MOVES):
                if mv.lower().replace(" ", "") == want:
                    named = i + 1
    import re as _re
    sim_slot = _re.search(r"E(\d)", rendered)
    sim_slot = int(sim_slot.group(1)) if sim_slot else None
    if named != sim_slot:
        out.append(f"TARGET MOVE sim=E{sim_slot} log=E{named}")
    # 2. fully paralyzed
    log_par = "is paralyzed! It can't move!" in joined
    if log_par != ("Epar" in rendered):
        out.append(f"PARALYSIS sim={'Epar' in rendered} log={log_par}")
    # 3. the target's hit/miss/crit, and ours
    log_miss = "attack missed" in joined
    if log_miss != bool(_re.search(r"E\d-", rendered)):
        out.append(f"TARGET MISS sim={bool(_re.search(r'E.-', rendered))} log={log_miss}")
    log_crit = "A critical hit!" in joined
    if log_crit != ("!" in rendered.split("E")[0] if rendered.startswith("M") else False):
        if log_crit != ("M" in rendered and "!" in rendered):
            out.append(f"CRIT sim={'!' in rendered} log={log_crit}")
    # 4. Static
    log_static = "Static paralyzed" in joined
    if log_static != ("*" in rendered):
        out.append(f"STATIC sim={'*' in rendered} log={log_static}")
    # 5. the secondary marker: a stat-rose/burned message from the target's move
    log_sec = ("'s Attack rose!" in joined or "was burned!" in joined)
    if log_sec and "~" not in rendered:
        out.append("SECONDARY missing from the tokens")
    # 6. a ball's shake count
    if "Ball!" in joined:
        shakes = next((i for i, s in enumerate(SHAKES) if s in joined), None)
        caught = "Gotcha!" in joined or "was caught" in joined
        sim_shakes = _re.search(r"[CP](\d)", rendered)
        sim_shakes = int(sim_shakes.group(1)) if sim_shakes else None
        if not caught and shakes != sim_shakes:
            out.append(f"SHAKES sim={sim_shakes} log={shakes}")
    return out

def main(path):
    label = path.split("/")[-1].split(".")[0]
    d = json.load(open(path))
    seed = int(d["forced_seed"], 16)
    ov = [r for r in d["records"] if "override" in r][0]["override"]["after"]
    target = Battler(name="Ho-Oh", level=70, types=("Fire", "Flying"),
                     stats={k: ov["stats"][k] for k in ("hp","atk","def","spa","spd","spe")},
                     moves=("Sacred Fire", "Punishment", "Ancient Power", "Safeguard"),
                     pp=(5, 5, 5, 25), ability="Pressure")
    party = {s: battler(s, i + 1) for i, s in enumerate(ORDER)}
    config = HuntConfig(target_catch_rate=3, target_has_pressure=True)
    state = BattleState(ours=party["natu"], target=target,
                        bench=tuple(party[s] for s in ORDER if s != "natu"), phase=1,
                        rng=opening_rng(seed, config))
    intro, chunks = segment(d["records"])
    intro_rolls = len([r for r in intro if "roll" in r])
    print(f"\n{'#'*96}\n# {label}  seed={d['forced_seed']}  intro rolls={intro_rolls} "
          f"(model: {config.battle_start_advances})  turns={len(chunks)}")
    by_name = {v.name: k for k, v in party.items()}
    problems = []
    for i, b in enumerate(chunks, start=1):
        msgs = [" ".join(r["msg"].split()) for r in b if "msg" in r]
        rolls = len([r for r in b if "roll" in r])
        hp = [(x["battler"], x["hp"], x["max"]) for r in b if "hp" in r for x in r["hp"]]
        out_species = by_name.get(state.ours.name)
        action, kw, note = read_action(msgs, out_species, party, label, i)
        if action is None:
            print(f"\n-- turn {i}: {note}")
            for m in msgs: print("     .", m)
            break
        extra = {}
        if action is Action.SWITCH:
            names = [bb.name for bb in state.bench]
            want = party[kw["incoming"]].name
            if want not in names:
                problems.append(f"turn {i}: {want} not benched ({names})")
                break
            extra["bench_slot"] = names.index(want)
        if action is Action.REVIVE:
            names = [bb.name for bb in state.bench]
            extra["bench_slot"] = names.index(party[kw["revive"]].name)
        if action is Action.FAINTED:
            pass
        # Who the player actually sent out after a faint, read off the log rather than guessed.
        repl = None
        for j, m in enumerate(msgs):
            if "Use next" in m or "weak!" in m:
                for g in msgs[j:]:
                    gm = GO.match(g.strip())
                    if gm:
                        repl = party[species_of(gm.group(1))].party_slot
                        break
                break
        nxt = simulate_turn(state, action, config, replacement=repl, **extra)
        rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
        spent = nxt.rng_offset - state.rng_offset
        ours_hp = [h for h in hp if h[0] == 0]
        theirs = [h for h in hp if h[0] == 1]
        flag = []
        if spent != rolls: flag.append(f"ROLLS sim={spent} log={rolls}")
        flag += semantics(msgs, rendered, state, nxt)
        if theirs and nxt.target.hp != theirs[-1][1]:
            flag.append(f"TARGET HP sim={nxt.target.hp} log={theirs[-1][1]}")
        if ours_hp and ours_hp[-1][2] == nxt.ours.max_hp and nxt.ours.hp != ours_hp[-1][1]:
            flag.append(f"OUR HP sim={nxt.ours.hp} log={ours_hp[-1][1]}")
        print(f"\n-- turn {i} [{note}] sim={rendered!r} rolls {spent}/{rolls}"
              + ("   <<<< " + " | ".join(flag) if flag else ""))
        for m in msgs: print("     .", m)
        print(f"     sim: {nxt.ours.name} {nxt.ours.hp}/{nxt.ours.max_hp} {nxt.ours.status.value}"
              f" | HO-OH {nxt.target.hp} {nxt.target.status.value}"
              f" atk{nxt.target.atk_stage} def{nxt.target.def_stage}"
              f" acc{nxt.target.accuracy_stage} spe{nxt.target.speed_stage}"
              f" sg{nxt.safeguard_turns} ls{nxt.light_screen_turns}")
        if hp: print("     log HP:", hp)
        if flag: problems.append(f"turn {i} [{note}]: " + " | ".join(flag))
        state = nxt
        if state.over:
            print("   (simulator says the battle is over)")
            break
    print(f"\n### {label}: {len(problems)} mismatching turns")
    for p in problems: print("   ", p)

for p in sys.argv[1:]:
    main(p)
