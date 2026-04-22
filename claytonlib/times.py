import datetime as dt
import json
import sys


def calculate_seed(time: dt.datetime, delay: int) -> int:
    mdms = (time.month * time.day + time.minute + time.second) & 0xFF
    return (mdms << 24) | (time.hour << 16) | (delay & 0xFFFF)


def generate_times(key_seed):
    mdms  = (key_seed & 0xFF000000) >> 24
    hour  = (key_seed & 0x00FF0000) >> 16
    delay =  key_seed & 0x0000FFFF

    with open('./mdMap.json', 'r') as f:
        md_map = json.load(f)

    mdms2 = (mdms + 138) % 0x100

    if mdms2 > mdms:
        slots = md_map[:mdms+1] + md_map[mdms2:]
    else:
        slots = md_map[mdms2:mdms + 1]

    # Flatten: each md_map slot is a list of [month, day] pairs
    pairs = [pair for slot in slots for pair in slot]

    date_times = []
    for month, day in pairs:
        ms = (0x100 + mdms - (month * day)) % 0x100
        # All [minute, second] where minute + second == ms, both in [0, 59]
        for minute in range(max(0, ms - 59), min(59, ms) + 1):
            second = ms - minute
            date_times.append(
                f"2000-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
            )

    return {"delay": delay, "times": sorted(date_times)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python times.py <key_seed>")
        print("  key_seed: 8-digit hex (e.g. 0xf519083F or f519083F)")
        sys.exit(1)

    result = generate_times(int(sys.argv[1], 16))
    print(json.dumps(result, indent=2))
