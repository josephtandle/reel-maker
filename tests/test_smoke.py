"""Public CLI integration smoke test (no speech models or network needed)."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"reel-maker"/"scripts"))
import rm_env
import smoke_test


class SmokeTest(unittest.TestCase):
    def test_cli_pipeline(self):
        if importlib.util.find_spec("PIL") is None:
            self.skipTest("Pillow is not installed")
        try:
            rm_env.ffmpeg()
        except rm_env.NeedsInput:
            self.skipTest("ffmpeg is not installed")
        self.assertEqual(smoke_test.main(), 0)


if __name__ == "__main__":
    unittest.main()
