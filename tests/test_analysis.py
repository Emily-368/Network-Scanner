import os
import tempfile
import unittest

from netscan.analysis import analyze, channel_congestion, channels_overlap, verdict
from netscan.report import html_report, text_report
from netscan.scanner import parse_iw_scan
from netscan.store import Survey

from .helpers import iw_block

HOME = "aa:aa:aa:aa:aa:01"


def build_survey(path):
    """Three spots: near the router, mid-house, far garage with a loud neighbour."""
    sv = Survey(path)
    spots = {
        "Hallway": ([-54, -55, -53, -56], -80, (2, 5)),
        "Living room": ([-63, -64, -65, -62], -72, (6, 4)),
        "Garage": ([-78, None, -81, -79], -70, (12, 1)),  # None = not seen that scan
    }
    for loc, (home_sigs, neigh, xy) in spots.items():
        for s in home_sigs:
            text = iw_block("bb:bb:bb:bb:bb:01", "Neighbour", 2442, neigh, 7)
            text += iw_block("cc:cc:cc:cc:cc:01", "FarAway", 2412, -85, 1)
            if s is not None:
                text += iw_block(HOME, "HomeNet", 2437, s, 6)
            sv.add_scan(loc, parse_iw_scan(text), "test", *xy)
    return sv


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "s.db")
        self.sv = build_survey(self.db)
        self.results = analyze([dict(o) for o in self.sv.observations()],
                               [dict(r) for r in self.sv.locations()], "HomeNet")

    def tearDown(self):
        self.sv.close()
        self.tmp.cleanup()

    def test_ranking_order(self):
        self.assertEqual([r.location for r in self.results],
                         ["Hallway", "Living room", "Garage"])
        self.assertGreater(self.results[0].score, self.results[1].score)

    def test_target_stats(self):
        hall = self.results[0]
        self.assertEqual(hall.target.bssid, HOME)
        self.assertEqual(hall.target.mean, -54.5)
        self.assertEqual(hall.verdict, "Excellent")
        garage = self.results[-1]
        self.assertEqual((garage.target.seen, garage.target.scans), (3, 4))
        self.assertEqual(garage.verdict, "Poor")

    def test_interference(self):
        hall = self.results[0]
        # Channel 7 overlaps channel 6; channel 1 does not.
        self.assertEqual([a.ssid for a in hall.interferers], ["Neighbour"])
        self.assertAlmostEqual(hall.sir, 25.5, places=1)
        self.assertLess(self.results[-1].sir, 0)

    def test_missing_target(self):
        res = analyze([dict(o) for o in self.sv.observations()],
                      [dict(r) for r in self.sv.locations()], "Nope")
        self.assertTrue(all(r.score == 0 and r.verdict == "Not seen" for r in res))

    def test_wrong_band_excluded(self):
        res = analyze([dict(o) for o in self.sv.observations()],
                      [dict(r) for r in self.sv.locations()], "HomeNet", band="5")
        self.assertTrue(all(r.target is None for r in res))

    def test_channel_congestion(self):
        loads = channel_congestion(self.results)["2.4"]
        self.assertEqual({c.channel for c in loads}, {1, 6, 11})
        self.assertEqual(loads[0].channel, 1)  # only the faint -85 dBm AP overlaps ch 1

    def test_reports_render(self):
        txt = text_report(self.results, "HomeNet", "2.4")
        self.assertIn("Recommended spot: Hallway", txt)
        page = html_report(self.results, "HomeNet", "2.4", self.db)
        self.assertIn("<svg viewBox", page)  # floor plan from --xy
        self.assertIn("Hallway", page)
        self.assertIn("No --ssid", text_report(
            analyze([dict(o) for o in self.sv.observations()],
                    [dict(r) for r in self.sv.locations()], None), None, "2.4"))

    def test_csv_export(self):
        out = os.path.join(self.tmp.name, "o.csv")
        self.assertEqual(self.sv.export_csv(out), 35)


class HelperTests(unittest.TestCase):
    def test_overlap(self):
        self.assertTrue(channels_overlap("2.4", 1, None, "2.4", 4, None))
        self.assertFalse(channels_overlap("2.4", 1, None, "2.4", 6, None))
        self.assertTrue(channels_overlap("5", 36, 80, "5", 48, 20))
        self.assertFalse(channels_overlap("5", 36, 80, "5", 52, 20))
        self.assertFalse(channels_overlap("5", 36, 20, "5", 40, 20))
        self.assertFalse(channels_overlap("2.4", 6, None, "5", 6, None))

    def test_verdict(self):
        self.assertEqual([verdict(v) for v in (-55, -65, -70, -80, -90, None)],
                         ["Excellent", "Good", "Fair", "Poor", "Unusable", "Not seen"])


if __name__ == "__main__":
    unittest.main()
