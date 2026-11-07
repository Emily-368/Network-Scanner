"""Turn survey observations into per-location placement scores.

The idea: the IoT gateway needs (1) a strong, steady link back to your Wi-Fi
network (the "target" SSID) and (2) as little competing traffic on that
channel as possible. Every surveyed location gets a 0-100 score built from:

  * signal       55%  mean RSSI of the best target AP (-90 dBm -> 0, -50 dBm -> 100)
  * stability    15%  standard deviation of that RSSI (0 dB -> 100, 8+ dB -> 0)
  * reliability  15%  share of scans in which the target was seen at all
  * interference 15%  target signal vs. summed power of other networks that
                      overlap its channel (25+ dB margin -> 100, 0 dB -> 0)
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

WEIGHTS = {"signal": 0.55, "stability": 0.15, "reliability": 0.15,
           "interference": 0.15}

# RSSI quality bands commonly used for Wi-Fi site surveys. -67 dBm is the usual
# minimum for reliable data links; small IoT radios benefit from extra margin.
VERDICTS = [(-60, "Excellent"), (-67, "Good"), (-75, "Fair"), (-82, "Poor")]

CHANNELS_24 = [1, 6, 11]


def verdict(rssi: Optional[float]) -> str:
    if rssi is None:
        return "Not seen"
    for limit, label in VERDICTS:
        if rssi >= limit:
            return label
    return "Unusable"


def dbm_to_mw(dbm: float) -> float:
    return 10 ** (dbm / 10.0)


def mw_to_dbm(mw: float) -> float:
    return 10 * math.log10(mw) if mw > 0 else -120.0


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def channels_overlap(band_a: str, ch_a: int, w_a: Optional[int],
                     band_b: str, ch_b: int, w_b: Optional[int]) -> bool:
    if band_a != band_b:
        return False
    if band_a == "2.4":
        # 20 MHz channels 5 MHz apart: anything closer than 5 channels collides.
        return abs(ch_a - ch_b) < 5
    width = max(w_a or 20, w_b or 20)
    if width <= 20:
        return ch_a == ch_b
    block = width // 5  # channel numbers spanned by one bonded block
    base = 36 if band_a == "5" else 1
    return (ch_a - base) // block == (ch_b - base) // block


@dataclass
class APStats:
    bssid: str
    ssid: str
    band: str
    channel: int
    width: Optional[int]
    security: str
    mean: float
    stdev: float
    min: float
    max: float
    seen: int
    scans: int
    station_count: Optional[int] = None
    utilization: Optional[float] = None

    @property
    def seen_ratio(self) -> float:
        return self.seen / self.scans if self.scans else 0.0


@dataclass
class LocationResult:
    location: str
    scans: int
    x: Optional[float] = None
    y: Optional[float] = None
    aps: List[APStats] = field(default_factory=list)
    target: Optional[APStats] = None
    interferers: List[APStats] = field(default_factory=list)
    interference_dbm: Optional[float] = None
    sir: Optional[float] = None  # target signal minus interference power, dB
    components: Dict[str, float] = field(default_factory=dict)
    score: Optional[float] = None

    @property
    def verdict(self) -> str:
        return verdict(self.target.mean if self.target else None)


def _ap_stats(rows: List[dict], scans: int) -> APStats:
    sig = [r["signal"] for r in rows]
    last = rows[-1]
    return APStats(
        bssid=last["bssid"], ssid=last["ssid"], band=last["band"],
        channel=last["channel"], width=last["width"], security=last["security"],
        mean=round(statistics.fmean(sig), 1),
        stdev=round(statistics.pstdev(sig), 1) if len(sig) > 1 else 0.0,
        min=round(min(sig), 1), max=round(max(sig), 1), seen=len({r["scan_id"] for r in rows}),
        scans=scans, station_count=last["station_count"],
        utilization=last["utilization"],
    )


def band_matches(band: str, wanted: str) -> bool:
    return wanted == "any" or band == wanted


def analyze(observations: Iterable[dict], locations: Iterable[dict],
            target_ssid: Optional[str] = None, band: str = "2.4") -> List[LocationResult]:
    """Score each surveyed location. Results are sorted best-first."""
    by_loc: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    for o in observations:
        by_loc[o["location"]][o["bssid"]].append(dict(o))

    results = []
    for loc in locations:
        name, nscans = loc["location"], loc["scans"]
        res = LocationResult(location=name, scans=nscans, x=loc["x"], y=loc["y"])
        res.aps = sorted(
            (_ap_stats(rows, nscans) for rows in by_loc.get(name, {}).values()),
            key=lambda a: a.mean, reverse=True,
        )
        if target_ssid is not None:
            candidates = [a for a in res.aps
                          if a.ssid == target_ssid and band_matches(a.band, band)]
            if candidates:
                # A client roams to the strongest AP, so judge the best one
                # (weighting by how often it was actually seen).
                res.target = max(candidates, key=lambda a: a.mean + 10 * a.seen_ratio)
            _score(res, target_ssid)
        results.append(res)

    if target_ssid is not None:
        results.sort(key=lambda r: (r.score is not None, r.score or 0), reverse=True)
    return results


def _score(res: LocationResult, target_ssid: str) -> None:
    t = res.target
    if t is None:
        res.score = 0.0
        res.components = {k: 0.0 for k in WEIGHTS}
        return
    res.interferers = [
        a for a in res.aps
        if a.ssid != target_ssid
        and channels_overlap(t.band, t.channel, t.width, a.band, a.channel, a.width)
    ]
    if res.interferers:
        # Weight each interferer by how often it is present.
        mw = sum(dbm_to_mw(a.mean) * a.seen_ratio for a in res.interferers)
        res.interference_dbm = round(mw_to_dbm(mw), 1)
        res.sir = round(t.mean - res.interference_dbm, 1)
        interference = clamp(res.sir / 25.0 * 100)
    else:
        interference = 100.0
    res.components = {
        "signal": round(clamp((t.mean + 90) / 40.0 * 100), 1),
        "stability": round(clamp(100 - t.stdev / 8.0 * 100), 1),
        "reliability": round(t.seen_ratio * 100, 1),
        "interference": round(interference, 1),
    }
    res.score = round(sum(res.components[k] * w for k, w in WEIGHTS.items()), 1)


@dataclass
class ChannelLoad:
    band: str
    channel: int
    networks: int
    power_dbm: float  # summed power of everything overlapping this channel


def channel_congestion(results: List[LocationResult]) -> Dict[str, List[ChannelLoad]]:
    """Rank candidate channels per band by how much they overlap with what we
    heard, averaged over all locations. Lowest power = quietest channel.
    Useful if the gateway runs its own access point for the IoT devices."""
    seen: Dict[str, Dict[int, Optional[int]]] = defaultdict(dict)
    for r in results:
        for a in r.aps:
            seen[a.band][a.channel] = a.width
    candidates = {
        "2.4": CHANNELS_24,
        "5": sorted(c for c in seen.get("5", {})) or [36, 40, 44, 48, 149, 153, 157, 161],
    }
    if seen.get("6"):
        candidates["6"] = sorted(seen["6"])
    out: Dict[str, List[ChannelLoad]] = {}
    n = max(len(results), 1)
    for band, chans in candidates.items():
        loads = []
        for ch in chans:
            nets, mw = set(), 0.0
            for r in results:
                for a in r.aps:
                    if channels_overlap(band, ch, 20, a.band, a.channel, a.width):
                        nets.add(a.bssid)
                        mw += dbm_to_mw(a.mean) * a.seen_ratio
            loads.append(ChannelLoad(band, ch, len(nets), round(mw_to_dbm(mw / n), 1)))
        out[band] = sorted(loads, key=lambda c: c.power_dbm)
    return out


def ssid_summary(results: List[LocationResult]) -> List[dict]:
    """Every network heard anywhere, strongest first."""
    nets: Dict[str, dict] = {}
    for r in results:
        for a in r.aps:
            key = a.ssid or f"<hidden {a.bssid}>"
            n = nets.setdefault(key, {"ssid": key, "bssids": set(), "bands": set(),
                                      "channels": set(), "best": -200.0,
                                      "security": a.security, "locations": set()})
            n["bssids"].add(a.bssid)
            n["bands"].add(a.band)
            n["channels"].add(a.channel)
            n["locations"].add(r.location)
            n["best"] = max(n["best"], a.mean)
    return sorted(nets.values(), key=lambda n: n["best"], reverse=True)
