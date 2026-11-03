"""The tracker's (and the page's) copy of the saves projection matches engine.State.project, Corsi included."""
import unittest

import engine
import tracker


class Mirror(unittest.TestCase):
    def test_project_saves_matches_engine(self):
        p = engine.Params(c_ca=0.13, c_cf=0.38)
        st = engine.State(p)
        for i in range(12):
            st.update_team("TOR", 31 + i % 3, 27 - i % 4, f"2026-10-{i + 1:02d}", 3, 2, None, None, 62 + i, 50 - i % 5)
            st.update_team("BOS", 26, 33, f"2026-10-{i + 1:02d}", 2, 3, None, None, 48, 64)
        st.update_goalie(1, "J. Woll", "TOR", 28, 30, 60.0)
        exp_sa, sv, share, proj, d, o = st.project("TOR", "BOS", 1, True, False, False)
        payload = {"params": p.to_dict(), "league": st.league(), "lg_cf": st.lg_cf.s / st.lg_cf.w, "lg_share": 0.97,
                   "teams": {t: {"rate_def": st.team_rate(st.dfn, t), "rate_off": st.team_rate(st.off, t),
                                 "rate_ca": st.corsi_rate(st.ca, t)[0], "rate_cf": st.corsi_rate(st.cf, t)[0]} for t in ("TOR", "BOS")},
                   "goalies": [{"id": 1, "sv": sv, "share": share}]}
        sa2, sv2, proj2 = tracker.project_saves(payload, 1, "TOR", "BOS", True, False, False)
        self.assertAlmostEqual(exp_sa, sa2, places=9)
        self.assertAlmostEqual(proj, proj2, places=9)
        # Corsi moves the projection: BOS generates few attempts and TOR allows few, so fewer shots
        no_c = engine.State(engine.Params(c_ca=0.0, c_cf=0.0))
        no_c.__dict__.update({k: v for k, v in st.__dict__.items() if k != "p"})
        self.assertLess(exp_sa, no_c.project("TOR", "BOS", 1, True, False, False)[0])


if __name__ == "__main__":
    unittest.main()
