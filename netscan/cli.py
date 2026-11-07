"""netscan command line: survey Wi-Fi signal to choose an IoT gateway location."""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import List, Optional

from . import __version__
from .analysis import analyze, verdict
from .report import html_report, text_report
from .scanner import AccessPoint, ScanError, list_interfaces, parse_iw_scan, scan
from .store import Survey


def pick_iface(requested: Optional[str]) -> str:
    if requested:
        return requested
    try:
        names = [i["name"] for i in list_interfaces()]
    except ScanError:
        names = []
    # On a Pi 3B wlan0 is the onboard radio; the USB adapter is usually wlan1.
    for n in names:
        if n != "wlan0":
            return n
    return names[0] if names else "wlan1"


def ap_table(aps: List[AccessPoint], target: Optional[str] = None, limit: int = 40) -> str:
    out = [f"{'SSID':<28} {'BSSID':<17} {'Band':>4} {'Ch':>3} {'dBm':>6}  {'Quality':<9} Security"]
    for ap in sorted(aps, key=lambda a: a.signal, reverse=True)[:limit]:
        name = ap.ssid or "<hidden>"
        mark = "*" if target and ap.ssid == target else " "
        out.append(f"{mark}{name[:27]:<27} {ap.bssid} {ap.band:>4} {ap.channel:>3} "
                   f"{ap.signal:>6.1f}  {verdict(ap.signal):<9} {ap.security}")
    return "\n".join(out)


def bar(dbm: float, width: int = 40) -> str:
    n = int(max(0, min(1, (dbm + 95) / 60)) * width)
    return "#" * n + "." * (width - n)


def cmd_interfaces(args) -> int:
    ifaces = list_interfaces()
    if not ifaces:
        print("No wireless interfaces found. Is the adapter plugged in? Try `lsusb`.")
        return 1
    for i in ifaces:
        print(f"{i['name']:<10} driver: {i['driver'] or 'unknown'}")
    return 0


def _get_scan(args) -> List[AccessPoint]:
    if getattr(args, "from_file", None):
        with open(args.from_file) as f:
            return parse_iw_scan(f.read())
    return scan(args.iface)


def cmd_scan(args) -> int:
    aps = _get_scan(args)
    print(f"{len(aps)} access points on {args.from_file or args.iface}\n")
    print(ap_table(aps, args.ssid, args.limit))
    return 0


def cmd_live(args) -> int:
    history: List[float] = []
    try:
        while True:
            aps = scan(args.iface)
            os.system("clear")
            print(f"netscan live  {args.iface}  {time.strftime('%H:%M:%S')}  "
                  f"(Ctrl-C to stop)\n")
            if args.ssid:
                tgt = [a for a in aps if a.ssid == args.ssid
                       and (args.band == "any" or a.band == args.band)]
                if tgt:
                    best = max(tgt, key=lambda a: a.signal)
                    history = (history + [best.signal])[-10:]
                    avg = statistics.fmean(history)
                    print(f"  {args.ssid}: {best.signal:.0f} dBm  "
                          f"(avg of last {len(history)}: {avg:.1f})  "
                          f"{verdict(avg)}  ch {best.channel}")
                    print(f"  [{bar(best.signal)}]\n")
                else:
                    history = []
                    print(f"  {args.ssid}: not seen on band {args.band}\n")
            print(ap_table(aps, args.ssid, args.limit))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
        return 0


def _parse_xy(s: Optional[str]):
    if not s:
        return None, None
    try:
        x, y = (float(v) for v in s.split(","))
        return x, y
    except ValueError:
        raise SystemExit(f"--xy must look like 3.5,2 (got {s!r})")


def _survey_location(sv: Survey, args, location: str, x, y) -> None:
    for i in range(args.samples):
        try:
            aps = _get_scan(args)
        except ScanError as e:
            print(f"  scan {i + 1}: failed ({e})")
            continue
        sv.add_scan(location, aps, args.iface, x, y)
        line = f"  scan {i + 1}/{args.samples}: {len(aps)} APs"
        if args.ssid:
            tgt = [a.signal for a in aps if a.ssid == args.ssid
                   and (args.band == "any" or a.band == args.band)]
            line += (f", {args.ssid} {max(tgt):.0f} dBm ({verdict(max(tgt))})"
                     if tgt else f", {args.ssid} not seen")
        print(line, flush=True)
        if i < args.samples - 1:
            time.sleep(args.interval)


def cmd_survey(args) -> int:
    sv = Survey(args.db)
    try:
        if args.location:
            x, y = _parse_xy(args.xy)
            print(f"Surveying '{args.location}' ({args.samples} scans)...")
            _survey_location(sv, args, args.location, x, y)
        else:
            print("Interactive survey. Walk to each candidate gateway spot, hold the "
                  "Pi where the gateway would sit, and enter a name.\n"
                  "Optionally add coordinates in metres: 'Kitchen @ 3.5,2'. "
                  "Blank line to finish.\n")
            while True:
                try:
                    entry = input("Location> ").strip()
                except EOFError:
                    break
                if not entry:
                    break
                name, _, xy = entry.partition("@")
                x, y = _parse_xy(xy.strip())
                _survey_location(sv, args, name.strip(), x, y)
        print(f"\nSaved to {args.db}. Run: netscan report --db {args.db}"
              + (f' --ssid "{args.ssid}"' if args.ssid else ""))
    finally:
        sv.close()
    return 0


def cmd_report(args) -> int:
    sv = Survey(args.db)
    try:
        locs = [dict(r) for r in sv.locations()]
        if not locs:
            print(f"No scans in {args.db} yet. Run `netscan survey` first.")
            return 1
        results = analyze([dict(o) for o in sv.observations()], locs,
                          args.ssid, args.band)
    finally:
        sv.close()
    print(text_report(results, args.ssid, args.band))
    if args.html:
        with open(args.html, "w") as f:
            f.write(html_report(results, args.ssid, args.band, args.db))
        print(f"\nHTML report written to {args.html}")
    return 0


def cmd_locations(args) -> int:
    sv = Survey(args.db)
    try:
        if args.delete:
            n = sv.delete_location(args.delete)
            print(f"Deleted {n} scans for '{args.delete}'.")
            return 0
        for r in sv.locations():
            xy = f"  @ {r['x']},{r['y']}" if r["x"] is not None else ""
            print(f"{r['location']:<24} {r['scans']:>3} scans  "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['first']))}{xy}")
    finally:
        sv.close()
    return 0


def cmd_export(args) -> int:
    sv = Survey(args.db)
    try:
        n = sv.export_csv(args.csv)
    finally:
        sv.close()
    print(f"Wrote {n} observations to {args.csv}")
    return 0


def cmd_ingest(args) -> int:
    """Store saved `iw scan` text output as scans for a location."""
    sv = Survey(args.db)
    try:
        x, y = _parse_xy(args.xy)
        for path in args.files:
            with open(path) as f:
                aps = parse_iw_scan(f.read())
            sv.add_scan(args.location, aps, "file", x, y)
            print(f"{path}: {len(aps)} APs -> '{args.location}'")
    finally:
        sv.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="netscan",
        description="Wi-Fi survey tool for choosing an IoT gateway location.")
    p.add_argument("--version", action="version", version=f"netscan {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def scan_opts(sp, ssid_help="Highlight / track this SSID"):
        sp.add_argument("-i", "--iface", help="Wireless interface (default: the USB "
                        "adapter, usually wlan1)")
        sp.add_argument("-s", "--ssid", help=ssid_help)
        sp.add_argument("-b", "--band", default="2.4", choices=["2.4", "5", "6", "any"],
                        help="Band the gateway will use for its uplink (default 2.4, "
                        "since most IoT radios are 2.4 GHz only)")

    sp = sub.add_parser("interfaces", help="List wireless adapters and drivers")
    sp.set_defaults(func=cmd_interfaces)

    sp = sub.add_parser("scan", help="Run one scan and print every AP")
    scan_opts(sp)
    sp.add_argument("--limit", type=int, default=60)
    sp.add_argument("--from-file", help="Parse saved `iw scan` output instead")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("live", help="Continuously rescan; handy while walking around")
    scan_opts(sp)
    sp.add_argument("--interval", type=float, default=2.0)
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_live)

    sp = sub.add_parser("survey", help="Record scans at named locations")
    scan_opts(sp, "Your network; shows its signal after each scan")
    sp.add_argument("-d", "--db", default="survey.db")
    sp.add_argument("-l", "--location", help="Location name (omit for interactive mode)")
    sp.add_argument("--xy", help="Optional position in metres, e.g. 3.5,2")
    sp.add_argument("-n", "--samples", type=int, default=6,
                    help="Scans per location (default 6)")
    sp.add_argument("--interval", type=float, default=2.0,
                    help="Seconds between scans (default 2)")
    sp.set_defaults(func=cmd_survey)

    sp = sub.add_parser("report", help="Rank surveyed locations")
    sp.add_argument("-d", "--db", default="survey.db")
    sp.add_argument("-s", "--ssid", help="Network the gateway will join")
    sp.add_argument("-b", "--band", default="2.4", choices=["2.4", "5", "6", "any"])
    sp.add_argument("--html", help="Also write an HTML report to this path")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("locations", help="List (or delete) surveyed locations")
    sp.add_argument("-d", "--db", default="survey.db")
    sp.add_argument("--delete", metavar="NAME", help="Delete all scans for a location")
    sp.set_defaults(func=cmd_locations)

    sp = sub.add_parser("export", help="Export raw observations to CSV")
    sp.add_argument("-d", "--db", default="survey.db")
    sp.add_argument("--csv", default="survey.csv")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("ingest", help="Import saved `iw scan` output files")
    sp.add_argument("-d", "--db", default="survey.db")
    sp.add_argument("-l", "--location", required=True)
    sp.add_argument("--xy")
    sp.add_argument("files", nargs="+")
    sp.set_defaults(func=cmd_ingest)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "iface") and not getattr(args, "from_file", None):
        args.iface = pick_iface(args.iface)
    try:
        return args.func(args)
    except ScanError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
