"""
expedition.py — High-level workflow manager.

Ties together chart, compass, and machete tools with persistent configuration
so the player doesn't have to manually re-enter parameters each session.

Usage:
    from claytonlib.expedition import expedition
    x = expedition("metang")
    f.chart_safari()
    f.save()
"""
import datetime as dt
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# CheckConfig
# ---------------------------------------------------------------------------

class CheckConfig:
    """Persistent configuration for the CheckHelper utilities."""

    def __init__(self):
        self.target_window: int = 30

    def _to_dict(self) -> dict:
        return {'target_window': self.target_window}

    @classmethod
    def _from_dict(cls, data: dict) -> 'CheckConfig':
        cfg = cls()
        cfg.target_window = data.get('target_window', 30)
        return cfg


# ---------------------------------------------------------------------------
# Strategy / criteria name registry
# ---------------------------------------------------------------------------

def _build_strategy_registry():
    from claytonlib.chart import (
        STRATEGY_ONLY_BALLS, STRATEGY_ONE_MUD, STRATEGY_SIX_BAIT,
    )
    return {
        STRATEGY_ONLY_BALLS.name:   STRATEGY_ONLY_BALLS,
        STRATEGY_ONE_MUD.name:      STRATEGY_ONE_MUD,
        STRATEGY_SIX_BAIT.name:     STRATEGY_SIX_BAIT,
    }


def _build_criteria_registry():
    from claytonlib.chart import (
        CRITERIA_CAPTURE, CRITERIA_WONT_FLEE_10_TURNS,
        CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS,
        CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS,
    )
    return {
        CRITERIA_CAPTURE.name:                    CRITERIA_CAPTURE,
        CRITERIA_WONT_FLEE_10_TURNS.name:         CRITERIA_WONT_FLEE_10_TURNS,
        CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS.name: CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS,
        CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS.name: CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS,
    }


def _resolve_strategy(name: str):
    reg = _build_strategy_registry()
    if name in reg:
        return reg[name]
    raise ValueError(f"Unknown strategy name: {name!r}. Known: {list(reg)}")


def _resolve_criteria(name: str):
    from claytonlib.chart import machete_x_turns_n_balls_criteria
    reg = _build_criteria_registry()
    if name in reg:
        return reg[name]
    # parameterised: "machete-{turns}-turns-after-{n}-balls"
    m = re.fullmatch(r'machete-(\d+)-turns-after-(\d+)-balls', name)
    if m:
        return machete_x_turns_n_balls_criteria(int(m.group(1)), int(m.group(2)))
    raise ValueError(f"Unknown criteria name: {name!r}")


def _resolve_eval_strategy(name: str):
    from claytonlib.chart.evaluation import SlidingWindowSum, NormalWindow
    # "sliding_window_N"
    m = re.fullmatch(r'sliding_window_(\d+)', name)
    if m:
        return SlidingWindowSum(int(m.group(1)))
    # "normal_S"
    m = re.fullmatch(r'normal_(.+)', name)
    if m:
        return NormalWindow(float(m.group(1)))
    raise ValueError(f"Unknown evaluation strategy filename: {name!r}")


_EVAL_TYPES = [
    ("sliding_window", "sliding window sum  (prompts for window size, must be odd)"),
    ("normal",         "Gaussian window  (prompts for sigma frames, e.g. 3.0)"),
]


# ---------------------------------------------------------------------------
# Expedition registry
# ---------------------------------------------------------------------------

_expeditions: dict[str, 'Expedition'] = {}
_EXPEDITIONS_DIR = Path('data/expeditions')


def expedition(name: str) -> 'Expedition':
    """Return the named Expedition, loading from file if necessary, creating if absent."""
    if name in _expeditions:
        return _expeditions[name]
    path = _EXPEDITIONS_DIR / f"{name}.json"
    if path.exists():
        f = Expedition._load(name, path)
    else:
        f = Expedition(name=name)
    _expeditions[name] = f
    return f


# ---------------------------------------------------------------------------
# Expedition class
# ---------------------------------------------------------------------------

class Expedition:
    """Persistent configuration and workflow manager for a single run."""

    def __init__(self, name: str):
        self.name = name

        # Chart inputs
        self.pokemon_name:        str | None = None
        self.key_seed:            int | None = None
        self.setup_delay_seconds: int | None = None
        self.max_target_seconds:  int | None = None
        self.strategy_name:       str | None = None
        self.criteria_name:       str | None = None
        self.eval_strategy_name:  str | None = None

        # Compass inputs
        self.window:              int | None = None
        self.target_delay:        int | None = None
        self.initial_time:        str | None = None  # ISO format

        # Results
        self.target_seeds:        list[str] = []
        self.target_seeds_path:   str | None = None

        # Compass premetronome
        self.compass_premetronome_histsize:  int | None = None
        self.metronome_second_window:     int        = 0
        self.compass_m_history:           list       = []
        self.compass_m_delay:             int | None = None  # saved calibration delay
        self.known_moves:                 list[int]  = []    # move numbers Metronome can't pick

        # Check utilities
        self.check_config: CheckConfig = CheckConfig()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def _to_dict(self) -> dict:
        return {
            'name':                     self.name,
            'pokemon_name':             self.pokemon_name,
            'key_seed':                 self.key_seed,
            'setup_delay_seconds':      self.setup_delay_seconds,
            'max_target_seconds':       self.max_target_seconds,
            'strategy_name':            self.strategy_name,
            'criteria_name':            self.criteria_name,
            'eval_strategy_name':       self.eval_strategy_name,
            'window':                   self.window,
            'target_delay':             self.target_delay,
            'initial_time':             self.initial_time,
            'target_seeds':             self.target_seeds,
            'target_seeds_path':        self.target_seeds_path,
            'compass_premetronome_histsize': self.compass_premetronome_histsize,
            'metronome_second_window':   self.metronome_second_window,
            'compass_m_history':        self.compass_m_history,
            'compass_m_delay':          self.compass_m_delay,
            'known_moves':              self.known_moves,
            'check':                    self.check_config._to_dict(),
        }

    @classmethod
    def _from_dict(cls, data: dict) -> 'Expedition':
        f = cls(name=data['name'])
        f.pokemon_name             = data.get('pokemon_name')
        f.key_seed                 = data.get('key_seed')
        f.setup_delay_seconds      = data.get('setup_delay_seconds')
        f.max_target_seconds       = data.get('max_target_seconds')
        f.strategy_name            = data.get('strategy_name')
        f.criteria_name            = data.get('criteria_name')
        f.eval_strategy_name       = data.get('eval_strategy_name')
        f.window                   = data.get('window')
        f.target_delay             = data.get('target_delay')
        f.initial_time             = data.get('initial_time')
        f.target_seeds             = data.get('target_seeds') or []
        f.target_seeds_path        = data.get('target_seeds_path')
        f.compass_premetronome_histsize = data.get('compass_premetronome_histsize')
        f.metronome_second_window    = data.get('metronome_second_window') or 0
        f.compass_m_history        = data.get('compass_m_history') or []
        f.compass_m_delay          = data.get('compass_m_delay')
        f.known_moves              = data.get('known_moves') or []
        f.check_config             = CheckConfig._from_dict(data.get('check') or {})
        return f

    @classmethod
    def _load(cls, name: str, path: Path) -> 'Expedition':
        with open(path) as fh:
            data = json.load(fh)
        return cls._from_dict(data)

    def save(self) -> None:
        """Persist this Expedition to data/expeditions/{name}.json."""
        _EXPEDITIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = _EXPEDITIONS_DIR / f"{self.name}.json"
        with open(path, 'w') as fh:
            json.dump(self._to_dict(), fh, indent=2)
        print(f"[expedition] Saved to {path}")

    def reload(self) -> None:
        """Reload config from file, discarding in-memory changes."""
        path = _EXPEDITIONS_DIR / f"{self.name}.json"
        if not path.exists():
            print(f"[expedition] No saved file at {path}; nothing to reload.")
            return
        loaded = Expedition._load(self.name, path)
        self.__dict__.update(loaded.__dict__)
        print(f"[expedition] Reloaded from {path}")

    def print(self) -> None:  # noqa: A003
        """Pretty-print current configuration."""
        fields = [
            ("pokemon",          self.pokemon_name or "(not set)"),
            ("key_seed",         f"0x{self.key_seed:08X}" if self.key_seed is not None else "(not set)"),
            ("setup_delay_s",    self.setup_delay_seconds if self.setup_delay_seconds is not None else "(not set)"),
            ("max_target_s",     self.max_target_seconds  if self.max_target_seconds  is not None else "(not set)"),
            ("strategy",         self.strategy_name       or "(not set)"),
            ("criteria",         self.criteria_name       or "(not set)"),
            ("eval_strategy",    self.eval_strategy_name  or "(not set)"),
            ("window",           self.window              if self.window              is not None else "(not set)"),
            ("target_delay",     self.target_delay        if self.target_delay        is not None else "(not set)"),
            ("initial_time",     self.initial_time        or "(not set)"),
            ("target_seeds",     self.target_seeds        or "(none)"),
            ("metronome_histsz",  self.compass_premetronome_histsize if self.compass_premetronome_histsize is not None else "(not set)"),
            ("metronome_second_window", self.metronome_second_window),
            ("compass_m_delay",   self.compass_m_delay            if self.compass_m_delay            is not None else "(not set)"),
        ]
        label_w = max(len(k) for k, _ in fields)
        print(f"=== Expedition: {self.name} ===")
        for key, val in fields:
            print(f"  {key:<{label_w}}  {val}")
        if self.key_seed is not None and self.target_delay is not None:
            from claytonlib.times import get_times
            base_delay, _ = get_times(self.key_seed)
            delay_from_key = self.target_delay - base_delay
            print(f"  {'---'}")
            print(f"  {'delay_from_key':<{label_w}}  {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prompt_int(self, prompt: str) -> int:
        while True:
            raw = input(prompt).strip()
            try:
                return int(raw)
            except ValueError:
                print("  Please enter a whole number.")

    def _prompt_hex(self, prompt: str) -> int:
        while True:
            raw = input(prompt).strip()
            try:
                return int(raw, 16)
            except ValueError:
                print("  Please enter a hex value (e.g. EC1504DC).")

    def _ensure_pokemon(self) -> None:
        if self.pokemon_name is not None:
            return
        from claytonlib.safari import safari_pokemon_by_name
        while True:
            name = input("Pokemon name: ").strip()
            try:
                safari_pokemon_by_name(name)
                self.pokemon_name = name
                return
            except KeyError:
                print(f"  Unknown pokemon {name!r}.")

    def _ensure_key_seed(self) -> None:
        if self.key_seed is not None:
            return
        self.key_seed = self._prompt_hex("Key seed (hex): ")

    def _ensure_setup_delay_seconds(self) -> None:
        if self.setup_delay_seconds is not None:
            return
        self.setup_delay_seconds = self._prompt_int("Setup delay (seconds): ")

    def _ensure_max_target_seconds(self) -> None:
        if self.max_target_seconds is not None:
            return
        self.max_target_seconds = self._prompt_int("Max target (seconds): ")

    def _ensure_strategy(self) -> None:
        if self.strategy_name is not None:
            return
        reg = _build_strategy_registry()
        names = list(reg)
        print("  Strategies:")
        for i, name in enumerate(names, 1):
            print(f"    {i}. {name}")
        while True:
            raw = input("  Strategy (number or name): ").strip()
            try:
                idx = int(raw)
                if 1 <= idx <= len(names):
                    self.strategy_name = names[idx - 1]
                    return
                print(f"  Enter a number 1-{len(names)}.")
                continue
            except ValueError:
                pass
            if raw in reg:
                self.strategy_name = raw
                return
            print(f"  Unknown strategy {raw!r}.")

    def _ensure_criteria(self) -> None:
        if self.criteria_name is not None:
            return
        reg = _build_criteria_registry()
        names = list(reg)
        print("  Criteria:")
        for i, name in enumerate(names, 1):
            print(f"    {i}. {name}")
        custom_idx = len(names) + 1
        print(f"    {custom_idx}. machete (custom)  —  prompts for turns and balls")
        while True:
            raw = input("  Criteria (number or name): ").strip()
            try:
                idx = int(raw)
                if 1 <= idx <= len(names):
                    self.criteria_name = names[idx - 1]
                    return
                if idx == custom_idx:
                    turns = self._prompt_int("  Machete turns: ")
                    balls = self._prompt_int("  Balls before machete: ")
                    name = f"machete-{turns}-turns-after-{balls}-balls"
                    try:
                        _resolve_criteria(name)
                        self.criteria_name = name
                        return
                    except ValueError as e:
                        print(f"  {e}")
                    continue
                print(f"  Enter a number 1-{custom_idx}.")
                continue
            except ValueError:
                pass
            try:
                _resolve_criteria(raw)
                self.criteria_name = raw
                return
            except ValueError as e:
                print(f"  {e}")

    def _ensure_eval_strategy(self) -> None:
        if self.eval_strategy_name is not None:
            return
        print("  Evaluation strategies:")
        for i, (key, desc) in enumerate(_EVAL_TYPES, 1):
            print(f"    {i}. {key}  —  {desc}")
        print("  (Or enter a full name like sliding_window_9 or normal_3.0)")
        while True:
            raw = input("  Eval strategy (number or full name): ").strip()
            try:
                idx = int(raw)
                if 1 <= idx <= len(_EVAL_TYPES):
                    key, _ = _EVAL_TYPES[idx - 1]
                    if key == "sliding_window":
                        while True:
                            n = self._prompt_int("  Window size (odd integer, e.g. 9): ")
                            name = f"sliding_window_{n}"
                            try:
                                _resolve_eval_strategy(name)
                                self.eval_strategy_name = name
                                return
                            except ValueError as e:
                                print(f"  {e}")
                    else:  # normal
                        while True:
                            s_raw = input("  Sigma frames (e.g. 3.0): ").strip()
                            try:
                                sigma = float(s_raw)
                                name = f"normal_{sigma:g}"
                                _resolve_eval_strategy(name)
                                self.eval_strategy_name = name
                                return
                            except ValueError as e:
                                print(f"  {e}")
                    continue
                print(f"  Enter a number 1-{len(_EVAL_TYPES)}.")
                continue
            except ValueError:
                pass
            try:
                _resolve_eval_strategy(raw)
                self.eval_strategy_name = raw
                return
            except ValueError as e:
                print(f"  {e}")

    def _ensure_window(self) -> None:
        if self.window is not None:
            return
        self.window = self._prompt_int("Compass window size (frames): ")

    def _ensure_target(self) -> None:
        if self.target_delay is not None and self.initial_time is not None:
            return
        print("[expedition] No target set. Run choose_target() first.")
        choice = input("  Run choose_target() now? (y/n) ").strip().lower()
        if choice in ('y', 'yes'):
            self.choose_target()
        else:
            raise RuntimeError("Aborted: target_delay/initial_time not set.")

    def _ensure_initial_time(self) -> None:
        if self.initial_time is not None:
            return
        self._prompt_initial_time()

    def _ensure_metronome_histsize(self) -> None:
        if self.compass_premetronome_histsize is not None:
            return
        self.compass_premetronome_histsize = self._prompt_int(
            "Compass metronome history size (0 to disable): "
        )

    def _ensure_metronome_second_window(self) -> None:
        self.metronome_second_window = self._prompt_int(
            f"Metronome second window (current={self.metronome_second_window}): "
        )

    def _prompt_target_delay(self) -> None:
        self.target_delay = self._prompt_int("Target delay (frames): ")

    def _prompt_initial_time(self) -> None:
        while True:
            raw = input("Initial time (YYYY-MM-DD HH:MM:SS): ").strip()
            try:
                self.initial_time = dt.datetime.strptime(raw, '%Y-%m-%d %H:%M:%S').isoformat()
                return
            except ValueError:
                print("  Use format YYYY-MM-DD HH:MM:SS.")

    # ------------------------------------------------------------------
    # adjust
    # ------------------------------------------------------------------

    # Ordered list of (field_name, display_label, clear_attr, setter_method_name)
    _ADJUSTABLE_FIELDS = [
        ("pokemon_name",              "pokemon",            "pokemon_name",              "_ensure_pokemon"),
        ("key_seed",                  "key_seed",           "key_seed",                  "_ensure_key_seed"),
        ("setup_delay_seconds",       "setup_delay_s",      "setup_delay_seconds",       "_ensure_setup_delay_seconds"),
        ("max_target_seconds",        "max_target_s",       "max_target_seconds",        "_ensure_max_target_seconds"),
        ("strategy_name",             "strategy",           "strategy_name",             "_ensure_strategy"),
        ("criteria_name",             "criteria",           "criteria_name",             "_ensure_criteria"),
        ("eval_strategy_name",        "eval_strategy",      "eval_strategy_name",        "_ensure_eval_strategy"),
        ("window",                    "window",             "window",                    "_ensure_window"),
        ("target_delay",              "target_delay",       "target_delay",              "_prompt_target_delay"),
        ("initial_time",              "initial_time",       "initial_time",              "_prompt_initial_time"),
        ("compass_premetronome_histsize","metronome_histsz",    "compass_premetronome_histsize","_ensure_metronome_histsize"),
        ("metronome_second_window",  "metronome_second_window", "metronome_second_window", "_ensure_metronome_second_window"),
    ]

    def adjust(self, **kwargs) -> None:
        """Change one or more already-set fields.

        Keyword form:  expedition.adjust(criteria_name="only-balls")
        Interactive:   expedition.adjust()  — prompts for which field to change.
        """
        if kwargs:
            valid = {f for f, *_ in self._ADJUSTABLE_FIELDS}
            for key, val in kwargs.items():
                if key not in valid:
                    raise ValueError(f"Unknown field {key!r}. Adjustable fields: {sorted(valid)}")
                setattr(self, key, val)
                print(f"[expedition] {key} = {val!r}")
            return

        # Interactive
        label_w = max(len(lbl) for _, lbl, *_ in self._ADJUSTABLE_FIELDS)
        print("Fields:")
        for i, (attr, lbl, _, _) in enumerate(self._ADJUSTABLE_FIELDS, 1):
            val = getattr(self, attr)
            if attr == "key_seed" and val is not None:
                display = f"0x{val:08X}"
            else:
                display = val if val is not None else "(not set)"
            print(f"  {i:2}. {lbl:<{label_w}}  {display}")

        while True:
            raw = input("Field to change (number or name): ").strip()
            match = None
            try:
                idx = int(raw)
                if 1 <= idx <= len(self._ADJUSTABLE_FIELDS):
                    match = self._ADJUSTABLE_FIELDS[idx - 1]
            except ValueError:
                for entry in self._ADJUSTABLE_FIELDS:
                    if raw in (entry[0], entry[1]):
                        match = entry
                        break
            if match is None:
                print(f"  Unrecognised {raw!r}.")
                continue
            attr, lbl, clear_attr, setter = match
            setattr(self, clear_attr, None)
            getattr(self, setter)()
            break

    def _get_chart_input(self):
        from claytonlib.chart import ChartSafariInput
        from claytonlib.safari import safari_pokemon_by_name
        return ChartSafariInput(
            key_seed=self.key_seed,
            setup_delay_seconds=self.setup_delay_seconds,
            max_target_seconds=self.max_target_seconds,
            strategy=_resolve_strategy(self.strategy_name),
            criteria=_resolve_criteria(self.criteria_name),
            pokemon=safari_pokemon_by_name(self.pokemon_name),
        )

    def _eval_filename_override(self, eval_strat, chart_dir) -> str | None:
        """Return the eval JSON basename override when max_target_seconds truncates chains."""
        if self.max_target_seconds is None or self.setup_delay_seconds is None:
            return None
        from claytonlib.chart.chain import LocalChainStore
        store = LocalChainStore()
        chain_paths = [
            p for p in store.list_chain_files(chart_dir)
            if int(p.stem.split('+')[1]) == self.setup_delay_seconds
        ]
        if not chain_paths:
            return None
        eval_max_links = self.max_target_seconds - self.setup_delay_seconds + 1
        full_links = store.file_size(chain_paths[0]) // 8
        if eval_max_links >= full_links:
            return None
        return f"{eval_strat.filename}_MAX_{self.max_target_seconds}s"

    # ------------------------------------------------------------------
    # chart_safari
    # ------------------------------------------------------------------

    def chart_safari(self) -> None:
        """Chart seeds for this pokemon. Prompts for missing config fields."""
        print(f"[expedition] === chart_safari ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        self._ensure_key_seed()
        self._ensure_setup_delay_seconds()
        self._ensure_max_target_seconds()
        self._ensure_strategy()
        self._ensure_criteria()

        from claytonlib.chart import chart_safari as _chart_safari
        inputs = self._get_chart_input()
        print(f"[expedition] Charting {self.pokemon_name} key_seed=0x{self.key_seed:08X} "
              f"delay={self.setup_delay_seconds}-{self.max_target_seconds}s "
              f"strategy={self.strategy_name} criteria={self.criteria_name}")
        _chart_safari(inputs)
        print("[expedition] chart_safari complete.")

    # ------------------------------------------------------------------
    # evaluate_chart
    # ------------------------------------------------------------------

    def evaluate_chart(self) -> None:
        """Evaluate the chart. Runs chart_safari() first if needed."""
        print(f"[expedition] === evaluate_chart ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self.chart_safari()
        self._ensure_eval_strategy()

        from claytonlib.chart import evaluate_chart as _evaluate_chart
        inputs = self._get_chart_input()
        eval_strat = _resolve_eval_strategy(self.eval_strategy_name)
        print(f"[expedition] Evaluating with strategy={self.eval_strategy_name}")
        _evaluate_chart(inputs, eval_strat, eval_max_seconds=self.max_target_seconds)
        print("[expedition] evaluate_chart complete.")

    # ------------------------------------------------------------------
    # choose_target helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_alternate_times(data, delay: int, score) -> list:
        """Return list of (chain_name, TopResult) where top5 or best5 contains delay+score."""
        matches = []
        for chain_name, chain_result in data.results.items():
            for top_r in chain_result.top5 + chain_result.best5:
                if top_r.delay == delay and top_r.score == score:
                    matches.append((chain_name, top_r))
                    break  # one entry per chain is enough
        # Sort by chain_name (chronological)
        matches.sort(key=lambda x: x[0])
        return matches

    # ------------------------------------------------------------------
    # choose_target
    # ------------------------------------------------------------------

    def choose_target(self) -> None:
        """Present top10/best10 results and prompt the user to pick a target."""
        print(f"[expedition] === choose_target ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self.evaluate_chart()

        from claytonlib.chart import _output_dir
        from claytonlib.chart.evaluation import read_evaluation
        from claytonlib.times import get_times

        inputs = self._get_chart_input()
        chart_dir = _output_dir(inputs)
        eval_strat = _resolve_eval_strategy(self.eval_strategy_name)
        data = read_evaluation(chart_dir, eval_strat, filename_override=self._eval_filename_override(eval_strat, chart_dir))

        if data is None or (not data.top10 and not data.best10):
            print("[expedition] No evaluation data found. Run evaluate_chart() first.")
            return

        base_delay, _ = get_times(self.key_seed)

        def _make_row(label: str, r) -> tuple:
            prob = eval_strat.score_to_probability(r.score)
            delay_from_key_s = (r.delay - base_delay) / 60
            return (label, str(r.score), f"{prob*100:.1f}%", str(r.delay), r.time, f"+{delay_from_key_s:.2f}s")

        headers = ("", "score", "prob", "delay", "time", "+key_s")
        top_rows  = [_make_row(f"t{i}", r) for i, r in enumerate(data.top10, 1)]
        best_rows = [_make_row(f"b{i}", r) for i, r in enumerate(data.best10, 1)]
        all_rows  = top_rows + best_rows

        col_w = [
            max(len(headers[c]), max((len(row[c]) for row in all_rows), default=0))
            for c in range(len(headers))
        ]

        def _fmt_row(row: tuple) -> str:
            return "  " + "  ".join(f"{v:<{col_w[ci]}}" for ci, v in enumerate(row))

        def _print_table(title: str, rows: list) -> None:
            print(title)
            print(_fmt_row(headers))
            for row in rows:
                print(_fmt_row(row))

        print()
        _print_table("Top 10 (t1-t10):", top_rows)
        print()
        _print_table("Best 10 (b1-b10):", best_rows)

        # Build lookup: label -> CrossChainResult
        options: dict[str, object] = {}
        for i, r in enumerate(data.top10,  1):
            options[f"t{i}"] = r
        for i, r in enumerate(data.best10, 1):
            options[f"b{i}"] = r

        print()
        print("Enter a label (t1-t10, b1-b10) or a hex seed to use directly.")

        while True:
            raw = input("Choice: ").strip()
            if raw in options:
                r = options[raw]
                self.target_delay = r.delay
                # Parse initial_time from chain filename: "YYYY-MM-DD_HH-MM-SS+NNN.chain"
                time_str = r.chain.split('+')[0]
                parsed = dt.datetime.strptime(time_str, '%Y-%m-%d_%H-%M-%S')
                self.initial_time = parsed.isoformat()
                delay_from_key = self.target_delay - base_delay
                print(f"[expedition] Target set: delay={self.target_delay}  initial_time={self.initial_time}")
                print(f"[expedition] Delay from key seed: {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")

                # Offer to scan for alternate chains with the same delay+score
                alt_choice = input("  See other times with the same score for this delay? (y/n) ").strip().lower()
                if alt_choice in ('y', 'yes'):
                    alts = self._find_alternate_times(data, r.delay, r.score)
                    other_alts = [x for x in alts if x[0] != r.chain]
                    if not other_alts:
                        print("  No other times found with the same delay and score.")
                    else:
                        print(f"  Found {len(alts)} time(s) (including chosen):")
                        for ai, (chain_name, top_r) in enumerate(alts, 1):
                            chain_date = chain_name.split('+')[0]  # "YYYY-MM-DD_HH-MM-SS"
                            chain_parsed = dt.datetime.strptime(chain_date, '%Y-%m-%d_%H-%M-%S')
                            marker = "  ← default" if chain_name == r.chain else ""
                            print(f"    {ai:2}. {chain_parsed.strftime('%Y-%m-%d %H:%M:%S')} → {top_r.time}{marker}")
                        print("  Enter a number to switch, or press Enter to keep default.")
                        raw2 = input("  Choice: ").strip()
                        if raw2:
                            try:
                                ai = int(raw2)
                                if 1 <= ai <= len(alts):
                                    alt_chain_name, _ = alts[ai - 1]
                                    alt_date = alt_chain_name.split('+')[0]
                                    alt_parsed = dt.datetime.strptime(alt_date, '%Y-%m-%d_%H-%M-%S')
                                    self.initial_time = alt_parsed.isoformat()
                                    print(f"[expedition] initial_time updated to {self.initial_time}")
                                else:
                                    print(f"  Number out of range; keeping {self.initial_time}.")
                            except ValueError:
                                print(f"  Not a number; keeping {self.initial_time}.")
                return
            # Try as hex seed
            try:
                seed_val = int(raw, 16)
                if seed_val > 0xFFFF_FFFF:
                    print("  Value out of range for a 32-bit seed.")
                    continue
                # Prompt for initial_time since we don't have a chain result
                print("  Seed entered directly. Also need initial_time.")
                raw_delay = input("  Target delay: ").strip()
                self.target_delay = int(raw_delay)
                raw_time = input("  Initial time (YYYY-MM-DD HH:MM:SS): ").strip()
                self.initial_time = dt.datetime.strptime(raw_time, '%Y-%m-%d %H:%M:%S').isoformat()
                delay_from_key = self.target_delay - base_delay
                print(f"[expedition] Target set: delay={self.target_delay}  initial_time={self.initial_time}")
                print(f"[expedition] Delay from key seed: {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")
                return
            except ValueError:
                pass
            print(f"  Unrecognised input {raw!r}. Enter a label like t1 or a hex seed.")

    # ------------------------------------------------------------------
    # compass_safari
    # ------------------------------------------------------------------

    def compass_safari(self) -> None:
        """Run compass_safari using stored config. Saves resulting seeds."""
        print(f"[expedition] === compass_safari ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        self._ensure_key_seed()
        self._ensure_strategy()
        self._ensure_criteria()
        self._ensure_window()
        self._ensure_target()

        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import CRITERIA_CAPTURE
        from claytonlib.compass import (
            compass_safari as _compass_safari,
            CompassSafariInput,
        )
        from claytonlib.times import get_times

        base_delay, _ = get_times(self.key_seed)
        delay_from_key = self.target_delay - base_delay
        print(f"[expedition] Delay from key seed: {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")

        initial_time = dt.datetime.fromisoformat(self.initial_time)
        inputs = CompassSafariInput(
            pokemon=safari_pokemon_by_name(self.pokemon_name),
            strategy=_resolve_strategy(self.strategy_name),
            criteria=_resolve_criteria(self.criteria_name),
            window=self.window,
            initial_time=initial_time,
            key_seed=self.key_seed,
            target_delay=self.target_delay,
            evaluation_strategy=_resolve_strategy(self.strategy_name),
            evaluation_criteria=CRITERIA_CAPTURE,
        )

        seeds = _compass_safari(inputs)
        if seeds:
            self.target_seeds = seeds
            self.target_seeds_path = f"compass_safari/{self.name}"
            print(f"[expedition] Saved {len(seeds)} seed(s) to target_seeds.")
        else:
            print("[expedition] No seeds returned from compass_safari.")

    # ------------------------------------------------------------------
    # compass_premetronome helpers
    # ------------------------------------------------------------------

    def _pick_metronome_delay(self) -> int:
        """Interactively resolve which target delay to use for compass_premetronome.

        Priority order:
          1. Main target_delay (if set) — user may accept or decline.
          2. Evaluation results — offered if no target_delay set.
          3. Saved compass_m_delay — offered as fallback when user declines (1) or (2).
          4. Manual entry — frames (integer) or seconds (decimal, converted via DPS).

        Sets self.initial_time if not already set.
        Saves manually-entered delays to self.compass_m_delay.
        """
        from claytonlib.chart.evaluation import DPS
        from claytonlib.times import get_times

        if self.target_delay is not None:
            ans = input(f"  Use target delay {self.target_delay}? (y/n) ").strip().lower()
            if ans in ('y', 'yes'):
                self._ensure_initial_time()
                return self.target_delay
        else:
            ans = input("  No target set. Choose a delay from evaluation results? (y/n) ").strip().lower()
            if ans in ('y', 'yes'):
                self.choose_target()   # sets target_delay + initial_time
                return self.target_delay

        # User declined — offer saved calibration delay first
        if self.compass_m_delay is not None:
            ans2 = input(f"  Re-use last calibration delay {self.compass_m_delay}? (y/n) ").strip().lower()
            if ans2 in ('y', 'yes'):
                self._ensure_initial_time()
                return self.compass_m_delay

        # Manual entry
        base_delay, _ = get_times(self.key_seed)
        print("  Enter a delay in frames (integer) or seconds (decimal, e.g. 5.32).")
        while True:
            raw = input("  Delay: ").strip()
            try:
                if '.' in raw:
                    seconds = float(raw)
                    delay = base_delay + round(seconds * DPS)
                    print(f"  → {seconds}s ≈ delay {delay}  (base {base_delay} + {delay - base_delay})")
                else:
                    delay = int(raw)
                self.compass_m_delay = delay
                self._ensure_initial_time()
                return delay
            except ValueError:
                print("  Enter an integer (frames) or a decimal number (seconds).")

    # ------------------------------------------------------------------
    # compass_premetronome
    # ------------------------------------------------------------------

    def compass_premetronome(self, *, second_window: int | None = None) -> None:
        """Run compass_premetronome using stored config. (History saving: stub.)

        second_window overrides self.metronome_second_window for this call only.
        """
        print(f"[expedition] === compass_premetronome ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_key_seed()
        self._ensure_window()
        self._ensure_metronome_histsize()

        from claytonlib.compass_premetronome import (
            compass_premetronome as _compass_premetronome,
            CompassPremetronomeInput,
            MetronomeOpponent,
        )
        from claytonlib.times import get_times

        target_delay = self._pick_metronome_delay()

        base_delay, _ = get_times(self.key_seed)
        delay_from_key = target_delay - base_delay
        print(f"[expedition] target_delay={target_delay}  Δ from key: {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")

        initial_time = dt.datetime.fromisoformat(self.initial_time)
        inputs = CompassPremetronomeInput(
            opponent=MetronomeOpponent.MAGIKARP,
            key_seed=self.key_seed,
            target_delay=target_delay,
            initial_time=initial_time,
            window=self.window,
            second_window=self.metronome_second_window if second_window is None else second_window,
        )
        _compass_premetronome(inputs)
        # TODO: save results to compass_m_history when histsize > 0

    def compass_m_clear(self) -> None:
        """Clear the compass metronome history."""
        self.compass_m_history = []
        print("[expedition] Metronome history cleared.")

    def compass_m_suggest(self) -> None:
        """Suggest most likely time based on metronome history. (Not yet implemented.)"""
        print("[expedition] compass_m_suggest: not yet implemented.")

    # ------------------------------------------------------------------
    # metronome_compass_full
    # ------------------------------------------------------------------

    def metronome_compass_full(self, *, second_window: int | None = None) -> None:
        """Run metronome_compass_full using stored config.

        Prompts for Magikarp level (session parameter, not saved).
        second_window overrides self.metronome_second_window for this call only.
        """
        print(f"[expedition] === metronome_compass_full ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_key_seed()
        self._ensure_window()

        from claytonlib.metronome_compass_full import (
            metronome_compass_full as _metronome_compass_full,
            CompassMetronomeFullInput,
        )
        from claytonlib.compass_premetronome import MetronomeOpponent
        from claytonlib.times import get_times

        # Prompt for Magikarp level (session parameter, not stored)
        while True:
            raw = input("  Magikarp level (2-20): ").strip()
            try:
                level = int(raw)
                if 2 <= level <= 20:
                    break
                print("  Enter a level between 2 and 20.")
            except ValueError:
                print("  Please enter a whole number.")

        target_delay = self._pick_metronome_delay()

        base_delay, _ = get_times(self.key_seed)
        delay_from_key = target_delay - base_delay
        print(f"[expedition] target_delay={target_delay}  Δ from key: {delay_from_key} frames  ({delay_from_key / 60:.2f}s)")

        initial_time = dt.datetime.fromisoformat(self.initial_time)
        inputs = CompassMetronomeFullInput(
            opponent=MetronomeOpponent.MAGIKARP,
            key_seed=self.key_seed,
            target_delay=target_delay,
            initial_time=initial_time,
            window=self.window,
            magikarp_level=level,
            known_moves=tuple(self.known_moves),
            second_window=self.metronome_second_window if second_window is None else second_window,
        )
        _metronome_compass_full(inputs)

    # ------------------------------------------------------------------
    # _pick_seed — shared by machete methods
    # ------------------------------------------------------------------

    def _pick_seed(self) -> str:
        """Return one seed hex string, prompting if multiple are available."""
        if not self.target_seeds:
            raise RuntimeError("No target_seeds set. Run compass_safari() first.")
        if len(self.target_seeds) == 1:
            return self.target_seeds[0]
        print("Multiple target seeds available:")
        for i, s in enumerate(self.target_seeds, 1):
            print(f"  {i}. {s}")
        while True:
            raw = input("Pick a seed (number or hex): ").strip()
            try:
                idx = int(raw)
                if 1 <= idx <= len(self.target_seeds):
                    return self.target_seeds[idx - 1]
                print(f"  Enter a number between 1 and {len(self.target_seeds)}.")
                continue
            except ValueError:
                pass
            # Try as hex
            try:
                val = int(raw, 16)
                hex_str = f"0x{val:08X}"
                if hex_str in self.target_seeds:
                    return hex_str
                print(f"  {raw!r} not in target_seeds list.")
            except ValueError:
                print("  Enter a list number or hex seed.")

    # ------------------------------------------------------------------
    # machete_one
    # ------------------------------------------------------------------

    def machete_one(self, max_turns: int | None = None) -> None:
        """Find shortest capture path for the chosen seed via BFS."""
        print(f"[expedition] === machete_one ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        seed_hex = self._pick_seed()
        seed = int(seed_hex, 16)

        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.machete import machete_one as _machete_one

        pokemon = safari_pokemon_by_name(self.pokemon_name)
        print(f"[expedition] Running machete_one for seed {seed_hex} ...")
        path = _machete_one(pokemon, seed=seed, max_turns=max_turns)
        if path is not None:
            print(f"[expedition] Capture path: {path}")
        else:
            print("[expedition] No capture path found.")

    # ------------------------------------------------------------------
    # machete_all
    # ------------------------------------------------------------------

    def machete_all(self) -> None:
        """Find all capture paths for the chosen seed via DFS."""
        print(f"[expedition] === machete_all ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        seed_hex = self._pick_seed()
        seed = int(seed_hex, 16)

        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.machete import machete_all as _machete_all

        pokemon = safari_pokemon_by_name(self.pokemon_name)
        print(f"[expedition] Running machete_all for seed {seed_hex} ...")
        paths, truncated = _machete_all(pokemon, seed=seed)
        if paths:
            print(f"[expedition] {len(paths)} capture path(s) found:")
            for p in paths:
                print(f"  {p}")
        else:
            print("[expedition] No capture paths found.")
        if truncated:
            print(f"[expedition] {truncated} branch(es) were depth-limited.")

    # ------------------------------------------------------------------
    # machete_jane
    # ------------------------------------------------------------------

    def machete_jane(self) -> None:
        """Run Jane (optimal decision tree) across all target seeds."""
        print(f"[expedition] === machete_jane ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        if not self.target_seeds:
            raise RuntimeError("No target_seeds set. Run compass_safari() first.")

        from claytonlib.safari import safari_pokemon_by_name, SafariContext
        from claytonlib.machete import machete_jane as _machete_jane

        pokemon = safari_pokemon_by_name(self.pokemon_name)
        candidates = [
            (SafariContext.start_encounter(int(s, 16), pokemon), int(s, 16))
            for s in self.target_seeds
        ]
        print(f"[expedition] Running machete_jane across {len(candidates)} seed(s) ...")
        _machete_jane(candidates, pokemon=pokemon, interactive=True)

    # ------------------------------------------------------------------
    # check
    # ------------------------------------------------------------------

    def check(self) -> 'CheckHelper':
        """Return a CheckHelper for validating implementation against this expedition's config."""
        return CheckHelper(self)


# ---------------------------------------------------------------------------
# CheckHelper
# ---------------------------------------------------------------------------

class CheckHelper:
    """Validation utilities for an Expedition. Returned by Expedition.check()."""

    def __init__(self, expedition: Expedition):
        self._exp = expedition

    @property
    def check_config(self) -> CheckConfig:
        return self._exp.check_config

    def chart_check_target_window(self, window: int | None = None) -> None:
        """Show per-delay seed evaluation and sliding window scores around the target delay.

        For each delay in [target_delay - window, ..., target_delay + window] (step 2),
        displays:
          - delay value and signed delta from target
          - second index (s), frame index within that second (j), frames in that second (n)
          - clock time (HH:MM:SS) at that second
          - seconds elapsed from key seed (3 decimal places)
          - seed_a and seed_b values with pass/fail under expedition strategy/criteria
          - straightened (blended) score: eval_a * wa + eval_b * wb
          - sliding window score from the expedition eval strategy

        Parameters
        ----------
        window:
            Number of delays on each side to examine.
            Falls back to check_config.target_window (default 30).
        """
        exp = self._exp
        cfg = exp.check_config

        if window is None:
            window = cfg.target_window

        # Validate prerequisites
        missing = [
            label for attr, label in [
                ('key_seed',           'key_seed'),
                ('target_delay',       'target_delay'),
                ('initial_time',       'initial_time'),
                ('pokemon_name',       'pokemon_name'),
                ('strategy_name',      'strategy_name'),
                ('criteria_name',      'criteria_name'),
                ('eval_strategy_name', 'eval_strategy_name'),
            ] if getattr(exp, attr) is None
        ]
        if missing:
            raise RuntimeError(f"check: expedition fields not set: {', '.join(missing)}")

        from claytonlib.chart import evaluate_seed
        from claytonlib.chart.evaluation import (
            DPS, SPF, frames_in_second, offset_frames, delay_at_second,
        )
        from claytonlib.compass import _delay_offset_to_second_frame
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.times import get_times, calculate_seed

        base_delay, _ = get_times(exp.key_seed)
        initial_time = dt.datetime.fromisoformat(exp.initial_time)
        pokemon = safari_pokemon_by_name(exp.pokemon_name)
        strategy = _resolve_strategy(exp.strategy_name)
        criteria = _resolve_criteria(exp.criteria_name)
        eval_strat = _resolve_eval_strategy(exp.eval_strategy_name)

        # Build delay range clipped to >= base_delay
        start = exp.target_delay - window
        delays = [d for d in range(start, exp.target_delay + window + 1)
                  if d >= base_delay]

        # Per-frame evaluation
        rows = []
        straight_scores = []
        for d in delays:
            offset = d - base_delay
            second_idx, frame_j = _delay_offset_to_second_frame(offset)
            n = frames_in_second(second_idx)
            time_at = initial_time + dt.timedelta(seconds=second_idx)

            seed_a_base = calculate_seed(time_at, delay_at_second(base_delay, second_idx))
            seed_a = seed_a_base + frame_j

            to_seed = calculate_seed(time_at + dt.timedelta(seconds=1),
                                     delay_at_second(base_delay, second_idx + 1))
            seed_b = (to_seed - n) + frame_j

            eval_a = evaluate_seed(seed_a, pokemon, strategy, criteria)
            eval_b = evaluate_seed(seed_b, pokemon, strategy, criteria)

            off = offset_frames(second_idx)
            wb = min(1.0, SPF * (frame_j + off))
            wa = 1.0 - wb
            straight = eval_a * wa + eval_b * wb

            rows.append({
                'delay':      d,
                'delta':      d - exp.target_delay,
                'second_idx': second_idx,
                'frame_j':    frame_j,
                'n':          n,
                'time':       time_at.strftime("%H:%M:%S"),
                'key_s':      offset / DPS,
                'seed_a':     seed_a,
                'eval_a':     eval_a,
                'seed_b':     seed_b,
                'eval_b':     eval_b,
                'straight':   straight,
            })
            straight_scores.append(straight)

        # Apply sliding window across the local frame range
        windowed = eval_strat.score(straight_scores)

        # Print
        header = (
            f"{'Delay':>7}  {'Δ':>5}  {'s':>4}  {'j':>3}  {'n':>2}  "
            f"{'Time':>8}  {'key_s':>9}  "
            f"{'seed_a':>10}  {'A'}  {'seed_b':>10}  {'B'}  "
            f"{'raw':>6}  {'score':>7}"
        )
        print(f"\nchart_check_target_window  ±{window} delays  eval={exp.eval_strategy_name}")
        print(f"key_seed=0x{exp.key_seed:08X}  base_delay={base_delay}  "
              f"target_delay={exp.target_delay}  initial_time={exp.initial_time}")
        print(header)
        print("-" * len(header))

        for row, wscore in zip(rows, windowed):
            delta_str = f"{row['delta']:+d}" if row['delta'] != 0 else "  0"
            score_str = f"{wscore:7.3f}" if wscore > 0 else "      -"
            marker = "  ←" if row['delay'] == exp.target_delay else ""
            print(
                f"{row['delay']:>7}  {delta_str:>5}  "
                f"{row['second_idx']:>4}  {row['frame_j']:>3}  {row['n']:>2}  "
                f"{row['time']:>8}  {row['key_s']:>9.3f}  "
                f"0x{row['seed_a']:08X}  {'✓' if row['eval_a'] else '✗'}  "
                f"0x{row['seed_b']:08X}  {'✓' if row['eval_b'] else '✗'}  "
                f"{row['straight']:>6.3f}  {score_str}"
                f"{marker}"
            )
