import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import freshness  # noqa: E402


class Freshness(unittest.TestCase):
    def test_lag(self):
        self.assertTrue(freshness.check({"data_through": "2026-10-23", "latest_final": "2026-10-24"})[0])
        self.assertFalse(freshness.check({"data_through": "2026-10-21", "latest_final": "2026-10-23"})[0])
        self.assertTrue(freshness.check({"data_through": "2026-10-21", "latest_final": None})[0])


if __name__ == "__main__":
    unittest.main()
