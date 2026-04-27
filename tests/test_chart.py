"""
Integration tests for chart_safari.
"""
import datetime as dt
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from claytonlib.chart import (
    ChartSafariInput,
    STRATEGY_ONLY_BALLS,
    CRITERIA_CAPTURE,
    chart_safari,
    chart_config,
)
from claytonlib.safari import safari_pokemon_by_name
from tests.testingutils import FakeChainStore


# Metang: catch_rate=3, flee_rate=60. Key seed 0xF6130000 (upper 16 bits),
# delay varies. We use a fixed seed 0xF6130875 which we verified previously
# captures on turn 14 with STRATEGY_ONLY_BALLS.
KEY_SEED = 0xF613_087B  # full seed (includes delay 0x087B = 2171)
SETUP_DELAY = 5
MAX_TARGET = 10
TOTAL_LINKS = MAX_TARGET - SETUP_DELAY + 1

TIME_A = dt.datetime(2000, 4, 30, 21, 57, 59)
TIME_B = dt.datetime(2000, 5, 24, 21, 57, 59)


def _fake_get_times_one(key_seed):
    """Single deterministic chain for most tests."""
    return key_seed & 0xFFFF, [TIME_A]


def _fake_get_times_two(key_seed):
    """Two chains for multi-chain tests."""
    return key_seed & 0xFFFF, [TIME_A, TIME_B]


def _make_inputs(**kwargs):
    base = dict(
        key_seed=KEY_SEED,
        setup_delay_seconds=SETUP_DELAY,
        max_target_seconds=MAX_TARGET,
        strategy=STRATEGY_ONLY_BALLS,
        criteria=CRITERIA_CAPTURE,
        pokemon=safari_pokemon_by_name('metang'),
    )
    base.update(kwargs)
    return ChartSafariInput(**base)


def _chart_dir(inputs):
    return Path('data') / f'metang_{KEY_SEED:08X}' / f'chart_{STRATEGY_ONLY_BALLS.name}_{CRITERIA_CAPTURE.name}'


class TestChartSafari(unittest.TestCase):

    def _run(self, inputs, store, get_times=_fake_get_times_one):
        with patch('claytonlib.chart.get_times', side_effect=get_times):
            chart_safari(inputs, store)

    # ------------------------------------------------------------------
    # Basic correctness
    # ------------------------------------------------------------------

    def test_produces_correct_number_of_links(self):
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)

        files = store.list_chain_files(_chart_dir(inputs))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(store.read_all(files[0])), TOTAL_LINKS)

    def test_file_size_is_multiple_of_16(self):
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)

        for path, data in store._files.items():
            self.assertEqual(len(data) % 16, 0, f"{path} has non-multiple-of-16 size")

    # ------------------------------------------------------------------
    # Resume / interrupt
    # ------------------------------------------------------------------

    def test_resume_after_partial_write(self):
        """Completing in two runs produces the same result as one full run."""
        store_full = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store_full)
        path = store_full.list_chain_files(_chart_dir(inputs))[0]
        full_values = store_full.read_all(path)

        store_partial = FakeChainStore()
        store_partial.append(path, full_values[:TOTAL_LINKS // 2])
        self._run(inputs, store_partial)

        self.assertEqual(full_values, store_partial.read_all(path))

    def test_idempotent_when_complete(self):
        """Running on an already-complete chart produces no additional writes."""
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)
        sizes_before = {p: store.file_size(p) for p in store._files}

        self._run(inputs, store)
        self.assertEqual(sizes_before, {p: store.file_size(p) for p in store._files})

    def test_over_size_complete_chain_is_truncated(self):
        """A chain file with more bytes than expected is truncated to complete_size."""
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)

        path = store.list_chain_files(_chart_dir(inputs))[0]
        full_size = store.file_size(path)

        # Inflate by one extra link
        store._files[path] += (0xDEADBEEF_DEADBEEF).to_bytes(16, 'little')
        self.assertEqual(store.file_size(path), full_size + 16)

        self._run(inputs, store)
        self.assertEqual(store.file_size(path), full_size)

    def test_square_off_among_incomplete_chains(self):
        """When two chains have different incomplete sizes, both are truncated to the smaller."""
        store = FakeChainStore()
        inputs = _make_inputs()

        # Run fully to get correct values
        self._run(inputs, store, get_times=_fake_get_times_two)
        files = store.list_chain_files(_chart_dir(inputs))
        self.assertEqual(len(files), 2)
        full_a = store.read_all(files[0])
        full_b = store.read_all(files[1])

        # Reset and pre-populate with different partial sizes
        store2 = FakeChainStore()
        store2.append(files[0], full_a[:2])   # 2 links written
        store2.append(files[1], full_b[:4])   # 4 links written — will be squared down to 2

        self._run(inputs, store2, get_times=_fake_get_times_two)

        self.assertEqual(store2.read_all(files[0]), full_a)
        self.assertEqual(store2.read_all(files[1]), full_b)

    def test_complete_chains_skipped_when_some_incomplete(self):
        """Chains already at complete_size are not re-evaluated; incomplete ones are finished."""
        store = FakeChainStore()
        inputs = _make_inputs()

        # Run fully with two chains
        self._run(inputs, store, get_times=_fake_get_times_two)
        files = store.list_chain_files(_chart_dir(inputs))
        full_a = store.read_all(files[0])
        full_b = store.read_all(files[1])

        # Reset: keep chain A complete, zero out chain B
        store2 = FakeChainStore()
        store2.append(files[0], full_a)  # complete
        # files[1] absent — size 0

        self._run(inputs, store2, get_times=_fake_get_times_two)

        self.assertEqual(store2.read_all(files[0]), full_a)  # unchanged
        self.assertEqual(store2.read_all(files[1]), full_b)  # now complete

    # ------------------------------------------------------------------
    # Resume validation
    # ------------------------------------------------------------------

    def test_resume_validation_passes_on_correct_data(self):
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)

        chart_config().resume_validation_enabled = True
        chart_config().resume_strict = True
        try:
            self._run(inputs, store)
        finally:
            chart_config().resume_validation_enabled = False
            chart_config().resume_strict = False

    def test_resume_validation_raises_on_corrupt_data(self):
        store = FakeChainStore()
        inputs = _make_inputs()
        self._run(inputs, store)

        # Corrupt the second-to-last link, then truncate the last link so the
        # chain looks incomplete but still contains the corrupted data.
        path = store.list_chain_files(_chart_dir(inputs))[0]
        store._files[path][-32:-16] = (0xDEAD).to_bytes(16, 'little')
        store.truncate(path, store.file_size(path) - 16)

        chart_config().resume_validation_enabled = True
        chart_config().resume_strict = True
        try:
            with self.assertRaises(RuntimeError):
                self._run(inputs, store)
        finally:
            chart_config().resume_validation_enabled = False
            chart_config().resume_strict = False


if __name__ == '__main__':
    unittest.main()
