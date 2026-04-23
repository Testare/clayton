import datetime as dt
import json
import sys
from pathlib import Path

_TIMES_DIR = Path('data/times')
_TIME_FMT = '%Y-%m-%d %H:%M:%S'


def calculate_seed(time: dt.datetime, delay: int) -> int:
    mdms = (time.month * time.day + time.minute + time.second) & 0xFF
    return (mdms << 24) | (time.hour << 16) | (delay & 0xFFFF)


def generate_times(key_seed):
    mdms  = (key_seed & 0xFF000000) >> 24
    hour  = (key_seed & 0x00FF0000) >> 16
    delay =  key_seed & 0x0000FFFF

    with open(Path(__file__).parent / "basedata" / "mdMap.json", 'r') as f:
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


def get_times(key_seed: int) -> tuple[int, list[dt.datetime]]:
    """Return (delay, times) for key_seed, loading from cache if available."""
    cache_path = _TIMES_DIR / f"{key_seed:08X}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            data = json.load(f)
    else:
        data = generate_times(key_seed)
        _TIMES_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w') as f:
            json.dump(data, f, indent=2)
    delay = data['delay']
    times = [dt.datetime.strptime(t, _TIME_FMT) for t in data['times']]
    return delay, times


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python times.py <key_seed>")
        print("  key_seed: 8-digit hex (e.g. 0xf519083F or f519083F)")
        sys.exit(1)

    result = generate_times(int(sys.argv[1], 16))
    print(json.dumps(result, indent=2))
