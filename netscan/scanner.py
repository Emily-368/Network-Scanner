"""Run `iw` scans on a wireless interface and parse the results.

Uses only the standard library so it runs on a stock Raspberry Pi OS install.
Scanning requires root (or CAP_NET_ADMIN), so run the CLI with sudo.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class AccessPoint:
    bssid: str
    ssid: str
    freq: int  # MHz
    channel: int
    band: str  # "2.4", "5" or "6"
    signal: float  # dBm
    security: str
    station_count: Optional[int] = None
    utilization: Optional[float] = None  # 0-100 %, from the BSS Load element
    width: Optional[int] = None  # MHz, best guess from HT/VHT/HE operation

    def to_dict(self) -> dict:
        return asdict(self)


class ScanError(RuntimeError):
    pass


def freq_to_channel(freq: int) -> int:
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if 5000 <= freq <= 5925:
        return (freq - 5000) // 5
    if 5950 <= freq <= 7125:
        return (freq - 5950) // 5
    return 0


def freq_to_band(freq: int) -> str:
    if freq < 3000:
        return "2.4"
    if freq < 5950:
        return "5"
    return "6"


def _decode_ssid(raw: str) -> str:
    """iw escapes non-printable bytes as \\xNN; decode them back to text."""
    if "\\x" not in raw:
        return raw
    try:
        data = re.sub(
            r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw
        ).encode("latin-1")
        text = data.decode("utf-8", errors="replace")
    except (UnicodeEncodeError, ValueError):
        return raw
    # An SSID of all NUL bytes is a hidden network.
    return "" if text.strip("\x00") == "" else text


_BSS_RE = re.compile(r"^BSS ([0-9a-fA-F:]{17})")


def parse_iw_scan(output: str) -> List[AccessPoint]:
    """Parse the text output of `iw dev <iface> scan`."""
    aps: List[AccessPoint] = []
    cur: Optional[dict] = None
    section = ""

    def finish() -> None:
        if cur is None or cur.get("freq") is None or cur.get("signal") is None:
            return
        freq = cur["freq"]
        if cur["rsn"]:
            security = "WPA3" if cur["sae"] and not cur["psk"] else (
                "WPA2/WPA3" if cur["sae"] else (
                    "WPA2-Enterprise" if cur["eap"] else "WPA2"))
        elif cur["wpa"]:
            security = "WPA"
        elif cur["privacy"]:
            security = "WEP"
        else:
            security = "Open"
        aps.append(AccessPoint(
            bssid=cur["bssid"],
            ssid=cur.get("ssid", ""),
            freq=freq,
            channel=cur.get("channel") or freq_to_channel(freq),
            band=freq_to_band(freq),
            signal=cur["signal"],
            security=security,
            station_count=cur.get("station_count"),
            utilization=cur.get("utilization"),
            width=cur.get("width"),
        ))

    for line in output.splitlines():
        m = _BSS_RE.match(line)
        if m:
            finish()
            cur = {"bssid": m.group(1).lower(), "rsn": False, "wpa": False,
                   "privacy": False, "sae": False, "psk": False, "eap": False}
            section = ""
            continue
        if cur is None:
            continue
        s = line.strip()
        # Track which IE block we are in (lines with a single leading tab).
        if line.startswith("\t") and not line.startswith("\t\t") and ":" in s:
            section = s.split(":", 1)[0]
        if s.startswith("freq:"):
            cur["freq"] = int(float(s.split(":", 1)[1].strip()))
        elif s.startswith("signal:"):
            cur["signal"] = float(s.split(":", 1)[1].split()[0])
        elif s.startswith("SSID:"):
            cur["ssid"] = _decode_ssid(line.split("SSID:", 1)[1].strip(" \t"))
        elif s.startswith("capability:"):
            cur["privacy"] = "Privacy" in s
        elif s.startswith("RSN:"):
            cur["rsn"] = True
        elif s.startswith("WPA:"):
            cur["wpa"] = True
        elif "Authentication suites:" in s and section in ("RSN", "WPA"):
            suites = s.split(":", 1)[1]
            cur["sae"] = cur["sae"] or "SAE" in suites
            cur["psk"] = cur["psk"] or bool(re.search(r"\bPSK\b", suites))
            cur["eap"] = cur["eap"] or "IEEE 802.1X" in suites
        elif s.startswith("DS Parameter set: channel"):
            cur["channel"] = int(s.rsplit(" ", 1)[1])
        elif s.startswith("* primary channel:") and "channel" not in cur:
            cur["channel"] = int(s.split(":", 1)[1])
        elif s.startswith("* station count:"):
            cur["station_count"] = int(s.split(":", 1)[1])
        elif s.startswith("* channel utilisation:"):
            num, den = s.split(":", 1)[1].strip().split("/")
            cur["utilization"] = round(100.0 * int(num) / int(den), 1)
        elif s.startswith("* STA channel width:") and "any" in s:
            cur["width"] = max(cur.get("width") or 20, 40)
        elif section == "VHT operation" and s.startswith("* channel width:"):
            # "1 (80 MHz)", "2 (160 MHz)", "0 (20 or 40 MHz)"
            mw = re.search(r"\((\d+) MHz\)", s)
            if mw:
                cur["width"] = max(cur.get("width") or 20, int(mw.group(1)))
    finish()
    return aps


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def scan(iface: str, retries: int = 4, flush: bool = True) -> List[AccessPoint]:
    """Trigger a fresh scan on `iface` and return the access points seen."""
    iw = shutil.which("iw") or "/usr/sbin/iw"
    # Interface has to be up to scan. Ignore failure; iw will report it.
    ip = shutil.which("ip") or "/usr/sbin/ip"
    _run([ip, "link", "set", iface, "up"])

    last_err = ""
    for attempt in range(retries):
        cmd = [iw, "dev", iface, "scan"] + (["flush"] if flush else [])
        try:
            res = _run(cmd)
        except FileNotFoundError:
            raise ScanError("`iw` not found. Install it with: sudo apt install iw")
        except subprocess.TimeoutExpired:
            last_err = "scan timed out"
            continue
        if res.returncode == 0:
            return parse_iw_scan(res.stdout)
        last_err = (res.stderr or res.stdout).strip()
        if "Operation not permitted" in last_err:
            raise ScanError("Scanning needs root. Re-run with sudo.")
        if "No such device" in last_err:
            raise ScanError(
                f"Interface {iface!r} not found. Run `iw dev` to list adapters."
            )
        if "Invalid argument" in last_err and flush:
            flush = False  # older iw/driver without flush support
            continue
        # -16 "Device or resource busy" is common while a previous scan finishes.
        time.sleep(1.5 * (attempt + 1))
    raise ScanError(f"Scan on {iface} failed: {last_err}")


def list_interfaces() -> List[dict]:
    """Return wireless interfaces from `iw dev` with their driver if known."""
    iw = shutil.which("iw") or "/usr/sbin/iw"
    try:
        out = _run([iw, "dev"]).stdout
    except FileNotFoundError:
        raise ScanError("`iw` not found. Install it with: sudo apt install iw")
    ifaces = []
    for m in re.finditer(r"Interface (\S+)", out):
        name = m.group(1)
        driver = ""
        try:
            driver = os.path.basename(
                os.readlink(f"/sys/class/net/{name}/device/driver")
            )
        except OSError:
            pass
        ifaces.append({"name": name, "driver": driver})
    return ifaces
