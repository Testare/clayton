"""Dump a battle log's RNG calls in order, one turn at a time.

Usage: PYTHONPATH=. python one-offs/battle_log_rolls.py <log.jsonl> [turn ...]

Turns are split on the wild Pokemon's move-choice roll at 0x0225e46e, which is the first
roll of every turn -- see notes/hooh_log_replay.md sec 1.
"""
import json, sys
CHOICE = "0x0225e46e"
d = json.load(open(sys.argv[1]))
recs = d["records"]
marks = [i for i, r in enumerate(recs) if "roll" in r and r["roll"]["addr"] == CHOICE]
want = set(int(x) for x in sys.argv[2:])
for t, (a, b) in enumerate(zip(marks, marks[1:] + [len(recs)]), start=1):
    if want and t not in want: continue
    print(f"\n=== log turn {t}")
    for r in recs[a:b]:
        if "roll" in r:
            print(f"   roll {r['roll']['func']:36s} {r['roll']['addr']}")
        elif "msg" in r:
            print("  MSG", " ".join(r["msg"].split()))
        elif "hp" in r:
            print("  HP ", [(x["battler"], x["hp"]) for x in r["hp"]])
