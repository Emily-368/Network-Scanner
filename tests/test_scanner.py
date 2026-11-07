import os
import unittest

from netscan.scanner import freq_to_band, freq_to_channel, parse_iw_scan

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "iw_scan.txt")


class ParseTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as f:
            self.aps = {a.bssid: a for a in parse_iw_scan(f.read())}

    def test_count(self):
        self.assertEqual(len(self.aps), 5)

    def test_associated_ap(self):
        a = self.aps["a0:40:a0:11:22:33"]
        self.assertEqual((a.ssid, a.freq, a.channel, a.band), ("HomeNet", 2437, 6, "2.4"))
        self.assertEqual(a.signal, -52.0)
        self.assertEqual(a.security, "WPA2/WPA3")
        self.assertEqual(a.station_count, 7)
        self.assertEqual(a.utilization, 20.0)

    def test_5ghz_vht_width(self):
        a = self.aps["a0:40:a0:11:22:34"]
        self.assertEqual((a.band, a.channel, a.width, a.security), ("5", 36, 80, "WPA2"))

    def test_escaped_utf8_ssid(self):
        self.assertEqual(self.aps["10:da:43:aa:bb:cc"].ssid, "Neighbor’s WiFi")
        self.assertEqual(self.aps["10:da:43:aa:bb:cc"].security, "WPA")

    def test_hidden_open(self):
        a = self.aps["22:33:44:55:66:77"]
        self.assertEqual((a.ssid, a.security), ("", "Open"))

    def test_enterprise(self):
        self.assertEqual(self.aps["66:77:88:99:aa:bb"].security, "WPA2-Enterprise")

    def test_empty(self):
        self.assertEqual(parse_iw_scan(""), [])

    def test_freq_helpers(self):
        self.assertEqual(freq_to_channel(2412), 1)
        self.assertEqual(freq_to_channel(2484), 14)
        self.assertEqual(freq_to_channel(5745), 149)
        self.assertEqual(freq_to_channel(5955), 1)
        self.assertEqual([freq_to_band(f) for f in (2412, 5180, 5955)], ["2.4", "5", "6"])


if __name__ == "__main__":
    unittest.main()
