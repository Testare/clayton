"""Clayton's version number, and that the places carrying it agree (VERSION at the root).

The number appears in four places — VERSION, pyproject, the Nix package, and the window
header — and nothing enforces that automatically, so a bump that misses one is the obvious
failure. These catch it.
"""
import pathlib
import re
import tempfile
import unittest

from app._version import version

_ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestVersion(unittest.TestCase):
    def test_it_reads_the_version_file(self):
        self.assertEqual(version(), (_ROOT / "VERSION").read_text().strip())

    def test_it_looks_like_a_version(self):
        self.assertRegex(version(), r"^\d+\.\d+(\.\d+)?$")

    def test_the_packaged_copy_matches_the_root_file(self):
        # app/resources/VERSION is what ships in the wheel and the frozen build; the root
        # VERSION is what the release workflow reads for its tag. They must not drift.
        self.assertEqual((_ROOT / "app" / "resources" / "VERSION").read_text().strip(),
                         (_ROOT / "VERSION").read_text().strip())

    def test_pyproject_agrees(self):
        text = (_ROOT / "pyproject.toml").read_text()
        found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        self.assertIsNotNone(found, "pyproject has no version")
        self.assertEqual(found.group(1), version())

    def test_the_nix_package_agrees(self):
        text = (_ROOT / "flake.nix").read_text()
        found = re.search(r'version\s*=\s*"([^"]+)"\s*;', text)
        self.assertIsNotNone(found, "flake.nix has no version")
        self.assertEqual(found.group(1), version())

    def test_the_facade_exposes_it(self):
        from app.facade import Facade
        from app.store import FileStore
        self.assertEqual(Facade(FileStore(tempfile.mkdtemp())).app_version(), version())

    def test_a_missing_version_file_does_not_break_startup(self):
        # A version number is decoration; it must never be why the app fails to launch.
        import unittest.mock as mock
        with mock.patch("importlib.resources.files", side_effect=OSError("gone")):
            self.assertRegex(version(), r"^\d+\.\d+(\.\d+)?$")


if __name__ == "__main__":
    unittest.main()
