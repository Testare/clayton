"""
expedition — High-level workflow manager.

Ties together chart, compass, and machete tools with persistent configuration
so the player doesn't have to manually re-enter parameters each session.

Usage:
    from claytonlib.expedition import expedition
    x = expedition("metang")
    x.chart_safari()
    x.save()
"""
import datetime as dt
import json
import os
from pathlib import Path

from claytonlib.expedition._config import (
    CheckConfig,
    _build_strategy_registry,
    _build_criteria_registry,
    _resolve_strategy,
    _resolve_criteria,
    _resolve_eval_strategy,
    _EVAL_TYPES,
)


# ---------------------------------------------------------------------------
# Expedition registry
# ---------------------------------------------------------------------------

_expeditions: dict[str, 'Expedition'] = {}
_EXPEDITIONS_DIR = Path('data/expeditions')


def _parse(t):
    """A datetime from a datetime or a string (ISO 'T' or space separator both accepted)."""
    if isinstance(t, dt.datetime):
        return t
    try:
        return dt.datetime.fromisoformat(t)
    except ValueError:
        return dt.datetime.strptime(t, '%Y-%m-%d %H:%M:%S')


def _phase(t):
    """The RNG-relevant phase (month, day, hour, minute, second) of a time; year is ignored."""
    d = _parse(t) if isinstance(t, str) else t
    return (d.month, d.day, d.hour, d.minute, d.second)


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
        # Which frame-rate model shape the chart/target math uses ("linear" default, or "quad").
        # The calibration artifact holds both; precompute_chart covers their UNION, so this can
        # be flipped (adjust(fps_model="quadratic")) without a re-precompute.  See notes/refined_chart.md.
        self.fps_model:           str = "linear"
        # Fold the calibration model's fitted safari load-path offset into the frame center for
        # ALL safari scoring/identification (precompute, chart_report, compass_safari,
        # chart_check_target_landing).  Kept uniform on purpose: the compass candidate set and the
        # chart scorer must share one frame model or they go disjoint (clayton-xqf).  Default True;
        # set False to score against the raw metronome fit.  No-op if no offset is fit.
        self.use_safari_offset:   bool = True

        # Chart tuning (I/O batching, resume validation — see chart.ChartOptions)
        from claytonlib.chart import ChartOptions
        self.chart_options: ChartOptions = ChartOptions()

        # Compass inputs
        self.window:              int | None = None
        self.target_delay:        int | None = None
        self.initial_time:        str | None = None  # ISO format

        # Chosen target (set by select_target from chart_report's findings)
        self.target_timer_delay:       int | None = None  # commanded countdown M to dial (ms)
        self.target_timer_calibration: int | None = None  # signed offset; M = delay + calibration

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
        from dataclasses import asdict
        return {
            'name':                     self.name,
            'chart_options':            asdict(self.chart_options),
            'pokemon_name':             self.pokemon_name,
            'key_seed':                 self.key_seed,
            'setup_delay_seconds':      self.setup_delay_seconds,
            'max_target_seconds':       self.max_target_seconds,
            'strategy_name':            self.strategy_name,
            'criteria_name':            self.criteria_name,
            'eval_strategy_name':       self.eval_strategy_name,
            'fps_model':                getattr(self, 'fps_model', 'linear'),
            'use_safari_offset':        getattr(self, 'use_safari_offset', True),
            'window':                   self.window,
            'target_delay':             self.target_delay,
            'initial_time':             self.initial_time,
            # getattr defaults keep save() working on instances created before these fields
            # existed (e.g. a live notebook object after autoreload).
            'target_timer_delay':       getattr(self, 'target_timer_delay', None),
            'target_timer_calibration': getattr(self, 'target_timer_calibration', None),
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
        from claytonlib.chart import ChartOptions
        f = cls(name=data['name'])
        _co = data.get('chart_options')
        if _co:
            valid = {k: v for k, v in _co.items() if k in ChartOptions.__dataclass_fields__}
            f.chart_options = ChartOptions(**valid)
        f.pokemon_name             = data.get('pokemon_name')
        f.key_seed                 = data.get('key_seed')
        f.setup_delay_seconds      = data.get('setup_delay_seconds')
        f.max_target_seconds       = data.get('max_target_seconds')
        f.strategy_name            = data.get('strategy_name')
        f.criteria_name            = data.get('criteria_name')
        f.eval_strategy_name       = data.get('eval_strategy_name')
        f.fps_model                = data.get('fps_model') or 'linear'
        f.use_safari_offset        = data.get('use_safari_offset', True)
        f.window                   = data.get('window')
        f.target_delay             = data.get('target_delay')
        f.initial_time             = data.get('initial_time')
        f.target_timer_delay       = data.get('target_timer_delay')
        f.target_timer_calibration = data.get('target_timer_calibration')
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
            ("fps_model",        getattr(self, 'fps_model', 'linear')),
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

    def _ensure_fps_model(self) -> None:
        if getattr(self, "fps_model", None):
            return
        from claytonlib.calibration import normalize_fps_model
        print("  Frame-rate model:  linear (default, physically-sane flat slope) | "
              "quadratic (in-range-tighter for 3-10 min; do NOT extrapolate)")
        while True:
            raw = input("  fps_model [linear/quadratic]: ").strip() or "linear"
            try:
                self.fps_model = normalize_fps_model(raw)
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
        ("fps_model",                 "fps_model",          "fps_model",                 "_ensure_fps_model"),
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
                if key == "fps_model":                      # validate + normalize ("quadratic"->"quad")
                    from claytonlib.calibration import normalize_fps_model
                    val = normalize_fps_model(val)
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
            options=self.chart_options,
        )

    def calibration_model(self, safari: bool | None = None):
        """The latest fitted timer-calibration model, or None if none has been exported yet.

        Reads the shared artifact that utils/calibration_tools refreshes after each saved run
        (the loop-back), so charting reflects the tightened model without a manual re-fit.
        Use it to build a CalibratedLandingWindow: it maps a commanded countdown M to the
        landing distribution over the battle-seed frame F_b.

        By default the fitted safari load-path offset is folded into the frame center (the whole
        expedition IS the safari path), so every caller -- chart_report, compass_safari,
        chart_check_target_landing -- shares one frame model and stays mutually consistent
        (clayton-xqf).  ``safari`` overrides that: None follows ``use_safari_offset`` (default
        True); False returns the raw metronome fit.  Folding is a no-op if no offset is fit.
        """
        from claytonlib.calibration import CalibrationModel
        model = CalibrationModel.load_default(which=getattr(self, "fps_model", "linear"))
        if model is None:
            return None
        if safari is None:
            safari = getattr(self, "use_safari_offset", True)
        return model.with_safari_offset() if safari else model

    def _warn_if_canon_missing_fps_model(self) -> None:
        """Warn if the stored canon wasn't precomputed for the selected fps_model.

        The canon covers the UNION of every model precompute_chart was run with; switching to a
        model it doesn't list risks silent under-coverage (esp. quad at high M, which centers far
        above linear).  A re-run of precompute_chart appends the missing frames (a fast extend).
        """
        from claytonlib.chart import CanonStore
        meta = CanonStore(self._canon_store_path()).read_meta()
        if meta is None:
            return
        built = meta.get("built_models")
        fps = getattr(self, "fps_model", "linear")
        if built and fps not in built:
            self._log(f"[warning] canon was built for fps_model {built}, but fps_model={fps!r} "
                      f"is selected -- run precompute_chart() to cover it (fast incremental extend).")

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
    # canonical chart pipeline (mdmsh capture map + sigma(M) scorer)
    # ------------------------------------------------------------------

    @staticmethod
    def _log(msg: str) -> None:
        """Print a timestamped [expedition] log line."""
        print(f"[expedition] {dt.datetime.now().strftime('%H:%M:%S')}  {msg}")

    def _canon_store_path(self) -> str:
        """Where this expedition's canonical capture map lives."""
        from claytonlib.chart import _output_dir
        return str(_output_dir(self._get_chart_input()) / "canon.jsonl")

    def _report_path(self) -> str:
        """Where chart_report's ranked findings are saved (for select_target to read)."""
        from claytonlib.chart import _output_dir
        return str(_output_dir(self._get_chart_input()) / "chart_report.json")

    @staticmethod
    def _ser_rows(rows) -> list:
        return [{
            "rank": i,
            "initial_time": (r["initial_time"].isoformat()
                             if isinstance(r.get("initial_time"), dt.datetime) else None),
            "M": round(r["M"]),
            "target_delay": int(r["F"]),
            "second": int(r["second"]),
            "p": r["p"],
            "sigma": r["sigma"],
            "mdmsh": list(r["mdmsh"]),
        } for i, r in enumerate(rows, 1)]

    def _write_report(self, mode: str, initial_time, params: dict, top: list,
                      per_initial_time: list | None = None) -> None:
        """Idempotently persist chart_report's findings (overwrites the same file).

        `top` = the ranked target list; `per_initial_time` = the best target for each
        candidate starting time (saved even though only the top of `top` is printed).
        """
        payload = {
            "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "initial_time": (initial_time.isoformat() if isinstance(initial_time, dt.datetime)
                             else initial_time),
            "params": params,
            "top": self._ser_rows(top),
            "per_initial_time": (self._ser_rows(per_initial_time)
                                 if per_initial_time is not None else None),
        }
        path = self._report_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=2)
        n_extra = len(payload["per_initial_time"]) if payload["per_initial_time"] else 0
        self._log(f"findings saved -> {path}  "
                  f"(top {len(payload['top'])}" +
                  (f" + {n_extra} per-starting-time" if n_extra else "") + ")")

    def precompute_chart(self, workers: int | None = None):
        """Precompute the canonical capture map (resumable) — supersedes chart_safari.

        Evaluates capture once per distinct (mdmsh, frame) seed across all RNG-equivalent
        candidate datetimes (~one grid, not one-per-datetime), into a resumable CanonStore.
        Re-run to resume or extend the range; only un-computed frames are evaluated.

        `workers` sets the process-pool size (default: all CPUs); pass 1 for a single core.
        Progress lines are timestamped with a rolling ETA.
        """
        import os
        import time
        self._log(f"=== precompute_chart ===  ({dt.datetime.now().strftime('%Y-%m-%d')})")
        self._ensure_pokemon()
        self._ensure_key_seed()
        self._ensure_setup_delay_seconds()
        self._ensure_max_target_seconds()
        self._ensure_strategy()
        self._ensure_criteria()

        from claytonlib.chart import precompute_canon, CanonStore
        from claytonlib.times import get_times
        from claytonlib.safari import safari_pokemon_by_name

        if workers is None:
            workers = os.cpu_count() or 1
        base_delay, times = get_times(self.key_seed)
        pokemon = safari_pokemon_by_name(self.pokemon_name)
        strategy = _resolve_strategy(self.strategy_name)
        criteria = _resolve_criteria(self.criteria_name)
        store = CanonStore(self._canon_store_path())

        # Build over the UNION of every model in the artifact (linear + quad), so fps_model can
        # be switched later without re-precomputing.  load_set returns {} if no artifact exists.
        from claytonlib.calibration import CalibrationModel
        model_set = CalibrationModel.load_set()
        if not model_set:
            raise RuntimeError(
                "precompute_chart needs a calibration model (it places each RTC second's frame "
                "band and maps M->second). None found at data/calibration_model.json -- save a "
                "calibration run first (utils/calibration_tools.save_compass_run).")
        # Fold the safari load-path offset into every model so the canon covers the SHIFTED frame
        # band the safari scorers will ask for -- otherwise precompute evaluates the raw-metronome
        # frames and chart_report (also folded) looks them up in a canon that never computed them.
        # Must match calibration_model()'s folding so precompute and scoring stay in lockstep.
        if getattr(self, "use_safari_offset", True):
            model_set = {k: m.with_safari_offset() for k, m in model_set.items()}
        model = model_set  # dict {fps_model_key: model}; precompute_canon unions their frames

        t0 = time.perf_counter()

        def _progress(done, total, stats):
            if done == 1 or done % 5 == 0 or done == total:
                elapsed = time.perf_counter() - t0
                eta = elapsed / done * (total - done) if done else 0.0
                self._log(f"mdmsh {done}/{total}  elapsed {elapsed / 60:.1f}m  "
                          f"eta ~{eta / 60:.1f}m")

        self._log(f"charting {self.pokemon_name} key_seed=0x{self.key_seed:08X} "
                  f"delay={self.setup_delay_seconds}-{self.max_target_seconds}s "
                  f"strategy={self.strategy_name} criteria={self.criteria_name}  "
                  f"fps_models={sorted(model_set)} (union)  workers={workers}")
        stats = precompute_canon(base_delay, times, self.setup_delay_seconds,
                                 self.max_target_seconds, pokemon, strategy, criteria, store,
                                 model, progress=_progress, workers=workers)
        elapsed = time.perf_counter() - t0
        self._log(f"=== precompute_chart complete ===  (elapsed {elapsed / 60:.1f}m)")
        self._log(f"-> {store.path}  ({stats['n_distinct_seeds']:,} seeds, "
                  f"{stats.get('evaluated_this_run', 0):,} evaluated this run, "
                  f"{stats['n_mdmsh']} mdmsh, reuse {stats['reuse_factor']:.0f}x)")
        return stats

    def chart_report(self, top: int = 10, step: int = 4, k: float = 3.5,
                     include_calibration: bool = False, initial_time=None):
        """Rank the best targets from the precomputed map + the calibration model.

        Default (mode A): prints the top `top` **(boot time, commanded countdown M)** pairs
        across all candidate boot times, and saves BOTH that ranking AND the best target for
        EACH candidate starting time (one row per boot time) to chart_report.json.  Pass
        `initial_time` (mode B) to rank the best M for one fixed boot time.  Needs
        precompute_chart() (the map) and a calibration model (see calibration_model()).
        """
        self._log("=== chart_report ===")
        from claytonlib.chart import (CanonStore, rank_boot_marginal, best_per_scenario,
                                      print_pairs_rows, print_target_report)
        from claytonlib.times import get_times

        store = CanonStore(self._canon_store_path())
        if store.read_meta() is None:
            self._log("No canonical map found. Run precompute_chart() first.")
            return None
        self._warn_if_canon_missing_fps_model()
        model = self.calibration_model()
        if model is None:
            self._log("No calibration model found. Save some compass runs first "
                      "(utils/calibration_tools.save_compass_run).")
            return None

        base_delay, times = get_times(self.key_seed)
        cmap = store.load_map()
        params = {"step": step, "k": k, "include_calibration": include_calibration, "top": top}
        setup, maxt = self.setup_delay_seconds, self.max_target_seconds

        if initial_time is None:
            # One marginalized per-boot sweep feeds both the overall pairs and the per-time bests.
            # Each boot's score is the SECOND-marginalized capture prob (Σ_s P(S=s|M)·cp), so an M
            # whose second is split across seeds is penalised (notes/seed_hitting_process.md).
            per_time = rank_boot_marginal(cmap, model, times, base_delay, setup, maxt,
                                          step=step, k=k, include_calibration=include_calibration)
            overall = best_per_scenario(per_time)
            print_pairs_rows(overall[:top], k, include_calibration,
                             title=f"Best (boot time, M) pairs  [top {top} of {len(overall)}]")
            self._log(f"best target for each of {len(per_time)} starting times also saved")
            self._write_report("pairs", None, params, top=overall[:top], per_initial_time=per_time)
            return overall[:top]

        # Mode B: rank M for a specific boot time (must be RNG-consistent with key_seed).
        it = _parse(initial_time)
        key_hour = (self.key_seed >> 16) & 0xFF
        if it.hour != key_hour:
            self._log(f"initial_time {it:%Y-%m-%d %H:%M:%S} (hour {it.hour}) is NOT RNG-consistent "
                      f"with key_seed 0x{self.key_seed:08X} (hour {key_hour}) -- it can't produce "
                      f"that boot seed; pick a candidate from get_times(key_seed).")
            return None
        all_rows = print_target_report(cmap, model, it, base_delay, setup, maxt, step=step, k=k,
                                       include_calibration=include_calibration, top=top)
        self._write_report("fixed", it, params, top=all_rows[:top], per_initial_time=None)
        return all_rows[:top]

    def select_target(self):
        """Pick a target from chart_report's saved findings — the new choose_target.

        A separate step from chart_report: reads chart_report.json (run chart_report() first),
        lists the ranked targets, prompts for a selection, and records it on the expedition:
        initial_time = the boot datetime, target_timer_delay = the commanded countdown M to dial
        (calibration 0), target_delay = the expected battle frame F_b (for identification).
        Returns the chosen row dict, or None if cancelled / no findings.
        """
        self._log("=== select_target ===")
        path = self._report_path()
        if not os.path.exists(path):
            self._log("No saved findings. Run chart_report() first.")
            return None
        with open(path) as fh:
            payload = json.load(fh)
        top_rows = payload.get("top") or payload.get("rows") or []  # 'rows' = older format
        per_time = payload.get("per_initial_time")
        if not top_rows:
            self._log("Saved findings are empty. Re-run chart_report().")
            return None
        default_boot = payload.get("initial_time")
        # The last starting time we used (persisted on the expedition), offered as a shortcut so
        # you don't have to retype it -- only when it's actually one of this report's candidates.
        last_boot = getattr(self, "initial_time", None)
        last_dt = _parse(last_boot) if last_boot else None
        reuse_ok = bool(per_time and last_dt and any(
            r.get("initial_time") and _phase(r["initial_time"]) == (
                last_dt.month, last_dt.day, last_dt.hour, last_dt.minute, last_dt.second)
            for r in per_time))

        while True:
            opts = "[t] top ranking" + ("   [s] specific starting time" if per_time else "")
            if reuse_ok:
                opts += f"   [l] reuse last ({last_dt:%m-%d %H:%M:%S})"
            try:
                raw = input(f"\nSelect by  {opts}  (blank to cancel): ").strip().lower()
            except EOFError:
                raw = ""
            if raw == "":
                self._log("No target selected.")
                return None
            if raw in ("t", "top"):
                chosen = self._select_from_rows(top_rows, default_boot)
                break
            if raw in ("s", "specific", "time") and per_time:
                chosen = self._select_by_time(per_time)
                break
            if raw in ("l", "last") and reuse_ok:
                chosen = self._row_for_time(per_time, last_dt)
                break
            print("  enter " + ("t, s" + (", or l" if reuse_ok else "") if per_time else "t") + ".")

        if chosen is None:
            self._log("No target selected.")
            return None

        boot = chosen.get("initial_time") or default_boot
        if boot is None:
            self._log("Selected row has no boot time; cannot set target.")
            return None
        self.initial_time = boot
        self.target_delay = int(chosen["target_delay"])
        self.target_timer_delay = int(chosen["M"])
        self.target_timer_calibration = 0
        self.save()
        self._log(f"target set: boot {self.initial_time}, timer M={self.target_timer_delay} ms, "
                  f"expected F_b={self.target_delay} (P~{chosen['p'] * 100:.1f}%). Saved.")

        # Predicted battle RTC time (boot + M/1000 + setup), so you can compare it against the
        # time you actually hit in the calibration notebook.  Only month/day/hour:min:sec are
        # meaningful (the chart models the year as 2000; your real run's year differs).
        model = self.calibration_model()
        if model is not None:
            M = self.target_timer_delay + (self.target_timer_calibration or 0)
            battle = _parse(self.initial_time) + dt.timedelta(
                seconds=model.battle_second_offset(M))
            self._log(f"predicted battle time (m/d h:m:s): {battle:%m-%d %H:%M:%S}  "
                      f"(= boot + {model.battle_second_offset(M)}s; year is the chart's 2000)")
        return chosen

    @staticmethod
    def _fmt_boot(row, default_boot) -> str:
        boot = row.get("initial_time") or default_boot or "(get_times candidate)"
        return boot.replace("T", " ")[:19] if isinstance(boot, str) else str(boot)

    def _select_from_rows(self, rows, default_boot):
        """List the ranked targets and prompt for a pick.  Returns a row, or None to cancel."""
        print(f"  {'#':>3}  {'boot time':>19}  {'M (ms)':>9}  {'F_b':>8}  "
              f"{'second':>6}  {'P(capture)':>10}")
        for r in rows:
            print(f"  {r['rank']:>3}  {self._fmt_boot(r, default_boot):>19}  {r['M']:>9}  "
                  f"{r['target_delay']:>8}  {r['second']:>6}  {r['p'] * 100:>9.1f}%")
        while True:
            try:
                raw = input("Select a target number (blank to cancel): ").strip()
            except EOFError:
                raw = ""
            if raw == "":
                return None
            try:
                idx = int(raw)
            except ValueError:
                print("  enter a number.")
                continue
            chosen = next((r for r in rows if r["rank"] == idx), None)
            if chosen is None:
                print(f"  no target #{idx}.")
                continue
            return chosen

    def _select_by_time(self, per_time):
        """Prompt for a specific starting time; return its best-target row (or None)."""
        print("Enter a starting time (year ignored). e.g. '2000-05-30 14:59:59' or "
              "'05-30 14:59:59'.")
        try:
            raw = input("Starting time (blank to cancel): ").strip()
        except EOFError:
            raw = ""
        if raw == "":
            return None
        t = self._parse_time_loose(raw)
        if t is None:
            self._log("Couldn't parse that time.")
            return None
        return self._row_for_time(per_time, t)

    def _row_for_time(self, per_time, t):
        """The per-time row whose boot phase matches datetime `t` (year ignored), or None."""
        key = (t.month, t.day, t.hour, t.minute, t.second)
        match = next((r for r in per_time
                      if r.get("initial_time") and _phase(r["initial_time"]) == key), None)
        if match is None:
            self._log("That isn't a candidate starting time for this key_seed (or has no "
                      "target). Pick one that get_times(key_seed) produces.")
            return None
        print(f"  -> best target for {self._fmt_boot(match, None)}: "
              f"M={match['M']} ms, F_b={match['target_delay']}, P~{match['p'] * 100:.1f}%")
        return match

    @staticmethod
    def _parse_time_loose(s):
        """Parse a full datetime, or an 'MM-DD HH:MM:SS' (year filled in); None on failure."""
        s = s.strip()
        try:
            return _parse(s)
        except (ValueError, TypeError):
            pass
        try:
            return dt.datetime.strptime("2000-" + s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

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

    def compass_safari(self, second_offsets=(-1, 0, 1), mass_cap=0.999) -> None:
        """Run compass_safari using stored config. Saves resulting seeds.

        Prefers the calibrated (second, frame) sweep: when a calibration model is available
        and a commanded countdown M is set (via select_target), the candidate set is built
        from ``from_expedition_target`` — no hand-set delay window.  Falls back to the legacy
        delay-window sweep when no model/M is available.

        ``second_offsets`` covers off-by-one timer-start timing (default δ∈{−1,0,+1}); each
        offset uses the SAME frame window (the second-offset is decoupled from the frame).
        ``mass_cap`` bounds the candidate set to the highest-prior seeds covering that share of
        the landing probability (trims the far tails); set None to keep the full ±kσ window.
        """
        print(f"[expedition] === compass_safari ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_pokemon()
        self._ensure_key_seed()
        self._ensure_strategy()
        self._ensure_criteria()

        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import CRITERIA_CAPTURE
        from claytonlib.compass import (
            compass_safari as _compass_safari,
            CompassSafariInput,
        )
        from claytonlib.times import get_times
        from claytonlib.chart.evaluation import DPS

        base_delay, _ = get_times(self.key_seed)
        pokemon = safari_pokemon_by_name(self.pokemon_name)
        strategy = _resolve_strategy(self.strategy_name)
        criteria = _resolve_criteria(self.criteria_name)
        eval_strategy = _resolve_strategy(self.strategy_name)

        model = self.calibration_model()
        M = (self.target_timer_delay + (self.target_timer_calibration or 0)
             if self.target_timer_delay is not None else None)

        if model is not None and M is not None and self.initial_time is not None:
            initial_time = dt.datetime.fromisoformat(self.initial_time)
            F = model.frame(M, base_delay)  # actual battle-seed low16 (dF+F_a; year-correct)
            sigma = model.jitter_sigma(M)
            print(f"[expedition] Calibrated sweep: M={M} ms → F*≈{F:.0f}  σ≈{sigma:.1f} frames "
                  f"(delay-from-key {F - base_delay:.0f}, {(F - base_delay) / DPS:.2f}s)")
            inputs = CompassSafariInput.from_expedition_target(
                model=model, M=M, initial_time=initial_time, key_seed=self.key_seed,
                max_target_seconds=self.max_target_seconds,
                pokemon=pokemon, strategy=strategy, criteria=criteria,
                second_offsets=tuple(second_offsets), mass_cap=mass_cap,
                evaluation_strategy=eval_strategy, evaluation_criteria=CRITERIA_CAPTURE,
            )
        else:
            missing = ("no calibration model" if model is None else
                       "no commanded M (run select_target)")
            print(f"[expedition] Legacy sweep ({missing}).")
            self._ensure_window()
            self._ensure_target()
            delay_from_key = self.target_delay - base_delay
            print(f"[expedition] Delay from key seed: {delay_from_key} frames  "
                  f"({delay_from_key / 60:.2f}s)")
            inputs = CompassSafariInput(
                pokemon=pokemon, strategy=strategy, criteria=criteria,
                window=self.window,
                initial_time=dt.datetime.fromisoformat(self.initial_time),
                key_seed=self.key_seed,
                target_delay=self.target_delay,
                evaluation_strategy=eval_strategy,
                evaluation_criteria=CRITERIA_CAPTURE,
            )

        seeds = _compass_safari(inputs)
        # Stash for the loop-back save (save_safari_run needs the CompassSafariInput to recover
        # the (frame, second, δ) of the identified seed).
        self._last_compass_inputs = inputs
        self._last_compass_seeds = seeds
        if seeds:
            self.target_seeds = seeds
            self.target_seeds_path = f"compass_safari/{self.name}"
            print(f"[expedition] Saved {len(seeds)} seed(s) to target_seeds.")
            if len(seeds) == 1:
                print("[expedition] Tip: x.save_safari_run() to log this run "
                      "(seed, path, inferred timer offset) to data/safari_runs.jsonl.")
        else:
            print("[expedition] No seeds returned from compass_safari.")

    def save_safari_run(self, path: str | None = None):
        """Loop-back: log the last compass_safari result to data/safari_runs.jsonl.

        Records the identified seed, the observed path, and the calibrated landing
        (M via the timer fields, plus frame / RTC second / second-offset δ) — no capture
        required.  Run compass_safari() first.  Returns the saved record, or None.
        """
        inputs = getattr(self, "_last_compass_inputs", None)
        seeds = getattr(self, "_last_compass_seeds", None) or self.target_seeds
        if not seeds:
            print("[expedition] No compass_safari result to save. Run compass_safari() first.")
            return None
        from claytonlib.calibration_tools import save_safari_run as _save
        return _save(seeds, inputs=inputs, path=path)

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
    # metronome_compass
    # ------------------------------------------------------------------

    def compass_premetronome(self, *, second_window: int | None = None) -> None:
        """Run compass_premetronome using stored config.

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
        seeds = _compass_premetronome(inputs)
        if seeds:
            self.target_seeds = seeds
            self.target_seeds_path = f"compass_premetronome/{self.name}"
            
            # Save to history
            if self.compass_metronome_histsize:
                entry = {
                    'timestamp': dt.datetime.now().isoformat(),
                    'target_delay': target_delay,
                    'seeds': seeds,
                }
                self.compass_m_history.append(entry)
                self.compass_m_history = self.compass_m_history[-self.compass_metronome_histsize:]

    def compass_m_clear(self) -> None:
        """Clear the compass metronome history."""
        self.compass_m_history = []
        print("[expedition] Metronome history cleared.")

    def compass_m_suggest(self) -> None:
        """Suggest most likely time based on metronome history. (Not yet implemented.)"""
        print("[expedition] compass_m_suggest: not yet implemented.")

    # ------------------------------------------------------------------

    def metronome_compass(self, *, second_window: int | None = None) -> None:
        """Run metronome_compass (full) using stored config.

        Prompts for Magikarp level (session parameter, not saved).
        second_window overrides self.metronome_second_window for this call only.
        """
        print(f"[expedition] === metronome_compass ===  {dt.datetime.now().strftime('%H:%M:%S')}")
        self._ensure_key_seed()
        self._ensure_window()
        self._ensure_metronome_histsize()

        from claytonlib.metronome_compass import (
            metronome_compass as _metronome_compass,
            CompassMetronomeInput,
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
        inputs = CompassMetronomeInput(
            opponent=MetronomeOpponent.MAGIKARP,
            key_seed=self.key_seed,
            target_delay=target_delay,
            initial_time=initial_time,
            window=self.window,
            magikarp_level=level,
            known_moves=tuple(self.known_moves),
            second_window=self.metronome_second_window if second_window is None else second_window,
        )
        seeds = _metronome_compass(inputs)
        if seeds:
            self.target_seeds = seeds
            self.target_seeds_path = f"metronome_compass/{self.name}"
            
            # Save to history
            if self.compass_metronome_histsize:
                entry = {
                    'timestamp': dt.datetime.now().isoformat(),
                    'target_delay': target_delay,
                    'seeds': seeds,
                }
                self.compass_m_history.append(entry)
                self.compass_m_history = self.compass_m_history[-self.compass_metronome_histsize:]

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

    def chart_check_target_landing(self, k: float = 3.5, step: int = 1,
                                   include_calibration: bool = False, verify: bool = False):
        """Break down the selected target's landing probability, one RTC second at a time.

        The battle RTC second isn't certain (σ_S wander), and each candidate second is a DIFFERENT
        mdmsh -- a different seed set -- so the frames must NOT be pooled across seconds.  This
        prints a SEPARATE frame breakdown per candidate second, ordered by P(S=s): the most likely
        second first (full landing window), then the next, then a third if it carries meaningful
        mass, each culled to a tighter window since it matters less.  The frame center is the SAME
        at every second (a second miss is a phase/δ0 effect that doesn't move the frame).  The
        bottom line is the MARGINAL P(capture) = Σ_s P(S=s)·cp_s.  `verify=True` re-evaluates every
        shown seed live; `step` prints every step-th frame row (the cp per second is still exact).
        """
        import math
        exp = self._exp

        missing = [lbl for attr, lbl in [
            ('key_seed', 'key_seed'), ('initial_time', 'initial_time'),
            ('target_timer_delay', 'target_timer_delay (run select_target)'),
            ('pokemon_name', 'pokemon_name'), ('strategy_name', 'strategy_name'),
            ('criteria_name', 'criteria_name'),
        ] if getattr(exp, attr, None) is None]
        if missing:
            raise RuntimeError(f"check: expedition fields not set: {', '.join(missing)}")

        from claytonlib.chart import CanonStore, seed_for_mdmsh, evaluate_seed
        from claytonlib.chart.scorer import marginal_capture
        from claytonlib.times import get_times
        from claytonlib.safari import safari_pokemon_by_name

        model = exp.calibration_model()
        if model is None:
            raise RuntimeError("no calibration model (data/calibration_model.json)")
        store = CanonStore(exp._canon_store_path())
        if store.read_meta() is None:
            raise RuntimeError("no canonical map; run precompute_chart() first")
        exp._warn_if_canon_missing_fps_model()
        cmap = store.load_map()

        M = exp.target_timer_delay + (exp.target_timer_calibration or 0)
        it = _parse(exp.initial_time)
        base_delay, _ = get_times(exp.key_seed)
        F = model.frame(M, base_delay)  # actual battle-seed low16 (dF+F_a; year-correct)
        sigma = (model.total_sigma(M, include_calibration=True) if include_calibration
                 else model.jitter_sigma(M))
        mc = marginal_capture(cmap, model, it, M, base_delay, k=k,
                              include_calibration=include_calibration)
        if mc is None:
            raise RuntimeError("empty second distribution for this target")
        breakdown = mc["breakdown"]  # per second, sorted by P(S=s) desc

        band = "jitter+calib" if include_calibration else "jitter"
        print(f"\nchart_check_target_landing  ({band} kernel, k={k})")
        print(f"boot={exp.initial_time}  timer M={M} ms  ->  mean F_b={F:.1f} (target_delay="
              f"{exp.target_delay})  sigma={sigma:.1f}")
        dist_str = "  ".join(f"{b['second']}={b['p_second'] * 100:.0f}%" for b in breakdown)
        print(f"RTC-second distribution (σ_S={model.rtc_offset_std:.2f}s):  {dist_str}")

        if verify:
            pokemon = safari_pokemon_by_name(exp.pokemon_name)
            strategy = _resolve_strategy(exp.strategy_name)
            criteria = _resolve_criteria(exp.criteria_name)

        head = f"{'frame':>7}  {'Δ':>5}  {'seed':>10}  {'hit':>3}  {'weight':>8}  {'w%':>8}  {'cumP%':>9}"
        if verify:
            head += f"  {'live':>4}"

        # Show the seconds carrying meaningful mass (>=2%), most-likely first, at most 3.
        shown = [b for b in breakdown if b["p_second"] >= 0.02][:3] or breakdown[:1]
        p_top = shown[0]["p_second"]
        two_s2 = 2.0 * sigma * sigma
        center_frame = round(F)
        mismatches = 0

        for idx, b in enumerate(shown):
            s, ps, mdmsh_s, cp_s = b["second"], b["p_second"], b["mdmsh"], b["cp"]
            full_lo, full_hi = b["lo"], b["hi"]
            # Less-likely seconds matter less -> cull their far frames (tighter display window).
            k_disp = k if idx == 0 else max(1.0, k * ps / p_top)
            disp_lo = max(full_lo, math.floor(F - k_disp * sigma))
            disp_hi = min(full_hi, math.ceil(F + k_disp * sigma))
            battle_s = it + dt.timedelta(seconds=s)
            print(f"\n=== second {s}  P(S={s})={ps * 100:.1f}%   mdmsh(m,h)={mdmsh_s}   "
                  f"battle {battle_s:%m-%d %H:%M:%S}")
            print(f"    cp(this second) = {cp_s * 100:.2f}%   ->  contributes P·cp = "
                  f"{ps * cp_s * 100:.2f}% to the total")
            if disp_lo > full_lo or disp_hi < full_hi:
                print(f"    (showing frames [{disp_lo}, {disp_hi}] of [{full_lo}, {full_hi}]; "
                      f"far tails culled)")
            print("    " + head)
            print("    " + "-" * len(head))
            # den over the FULL window so w%/cumP are exact even when the display is culled.
            data = []
            for frame in range(full_lo, full_hi + 1):
                w = math.exp(-((frame - F) ** 2) / two_s2)
                cap = cmap.captured(mdmsh_s, frame)
                live = (evaluate_seed(seed_for_mdmsh(mdmsh_s, frame), pokemon, strategy, criteria)
                        if verify else None)
                if verify and live != cap:
                    mismatches += 1
                data.append((frame, w, cap, live))
            den = sum(w for _, w, _, _ in data) or 1.0
            run_num = 0.0
            for frame, w, cap, live in data:
                if cap:
                    run_num += w
                if disp_lo <= frame <= disp_hi and ((frame - disp_lo) % step == 0
                                                    or frame == center_frame):
                    seedv = seed_for_mdmsh(mdmsh_s, frame)
                    mark = "  ←" if frame == center_frame else ""
                    line = (f"{frame:>7}  {frame - center_frame:>+5}  0x{seedv:08X}  "
                            f"{'✓' if cap else '✗':>3}  {w:>8.4f}  {w / den * 100:>7.3f}%  "
                            f"{run_num / den * 100:>8.3f}%")
                    if verify:
                        flag = ('✓' if live else '✗') if live == cap else f"!{'✓' if live else '✗'}"
                        line += f"  {flag:>4}"
                    print("    " + line + mark)

        print("\n" + "=" * (len(head) + 4))
        contrib = "  +  ".join(f"{b['p_second'] * 100:.0f}%·{b['cp'] * 100:.1f}%" for b in shown)
        print(f"MARGINAL P(capture) = Σ P(S=s)·cp_s  ({contrib})  =  {mc['p'] * 100:.3f}%")
        if verify:
            print(f"map vs live: {mismatches} mismatch(es) across shown seconds "
                  f"({'MAP MATCHES LIVE' if mismatches == 0 else 'DISCREPANCY!'})")
        return {"p": mc["p"],
                "seconds": [{"second": b["second"], "p_second": b["p_second"], "cp": b["cp"]}
                            for b in breakdown],
                "mismatches": mismatches if verify else None}
