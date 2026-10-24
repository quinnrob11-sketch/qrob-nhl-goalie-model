"""Code defaults equal the fitted JSON values; missing params files fail loudly; the model is frozen."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import engine      # noqa: E402
import freeze      # noqa: E402
import saves_dist  # noqa: E402
import sog         # noqa: E402

OUT = os.path.join(HERE, "output")


class Defaults(unittest.TestCase):
    def test_engine_defaults_match_json(self):
        self.assertEqual(asdict(engine.Params()), asdict(engine.Params.load(os.path.join(OUT, "params.json"))))

    def test_saves_dist_defaults_match_json(self):
        js = saves_dist.load(os.path.join(OUT, "saves_dist.json"))
        self.assertEqual(saves_dist.DEFAULTS, {k: js[k] for k in saves_dist.DEFAULTS})
        self.assertEqual((saves_dist.DEFAULTS["gs"], saves_dist.DEFAULTS["gs_cap"], saves_dist.DEFAULTS["sd_floor"]), (0.025, 0.12, 5.5))
        self.assertEqual(engine.Params().half_life, 30.0)

    def test_sog_defaults_match_json(self):
        self.assertEqual(asdict(sog.SogParams()), asdict(sog.SogParams.load(os.path.join(OUT, "sog_params.json"))))

    def test_missing_file_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                engine.Params.load(os.path.join(d, "params.json"))
            with self.assertRaises(FileNotFoundError):
                saves_dist.load(os.path.join(d, "saves_dist.json"))
            with self.assertRaises(FileNotFoundError):
                sog.SogParams.load(os.path.join(d, "sog_params.json"))


class Freeze(unittest.TestCase):
    def test_frozen(self):
        p = json.load(open(os.path.join(OUT, "params.json")))
        self.assertIn("frozen_at", p)
        ok, msg = freeze.check(None)
        self.assertTrue(ok, msg)

    def test_change_detected(self):
        s = freeze.settings()
        s["params.json"]["half_life"] = 20.0
        self.assertNotEqual(freeze.digest(s), freeze.digest(freeze.settings()))

    def test_change_needs_unfreeze_message(self):
        # pretend HEAD~0 is the base with different settings: patch base_settings
        real = freeze.base_settings
        try:
            def fake(base):
                s = freeze.settings(); s["params.json"]["half_life"] = 20.0
                return s
            freeze.base_settings = fake
            os.environ["COMMIT_MESSAGES"] = "tweak params"
            self.assertFalse(freeze.check("abc")[0])
            os.environ["COMMIT_MESSAGES"] = "retune half-life --unfreeze"
            self.assertTrue(freeze.check("abc")[0])
        finally:
            freeze.base_settings = real
            os.environ.pop("COMMIT_MESSAGES", None)


if __name__ == "__main__":
    unittest.main()
