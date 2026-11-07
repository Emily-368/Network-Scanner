"""Text and self-contained HTML reports for a survey."""
from __future__ import annotations

import html
import time
from typing import List, Optional

from .analysis import (LocationResult, WEIGHTS, channel_congestion, ssid_summary,
                       verdict)

VERDICT_COLORS = {"Excellent": "#1a7f37", "Good": "#4c9a2a", "Fair": "#b08800",
                  "Poor": "#d1580a", "Unusable": "#cf222e", "Not seen": "#6e7781"}


def _fmt(v, suffix="", none="-"):
    return none if v is None else f"{v}{suffix}"


def text_report(results: List[LocationResult], target: Optional[str], band: str) -> str:
    lines = []
    if target:
        lines.append(f"Gateway placement ranking for SSID '{target}' (band: {band})")
        lines.append("")
        hdr = (f"{'#':>2}  {'Location':<20} {'Score':>5}  {'Verdict':<9} "
               f"{'Mean':>6} {'Min':>6} {'SD':>4} {'Seen':>5} {'Ch':>4} {'SIR':>9}")
        lines += [hdr, "-" * len(hdr)]
        for i, r in enumerate(results, 1):
            t = r.target
            lines.append(
                f"{i:>2}  {r.location[:20]:<20} {_fmt(r.score):>5}  {r.verdict:<9} "
                f"{_fmt(t and t.mean):>6} {_fmt(t and t.min):>6} "
                f"{_fmt(t and t.stdev):>4} "
                f"{(f'{t.seen}/{t.scans}' if t else '-'):>5} "
                f"{_fmt(t and t.channel):>4} {_fmt(r.sir, ' dB'):>9}"
            )
        best = next((r for r in results if r.target), None)
        lines.append("")
        if best:
            lines.append(f"Recommended spot: {best.location} "
                         f"({best.verdict}, {best.target.mean} dBm, score {best.score})")
            if best.target.mean < -67:
                lines.append("  Warning: even the best spot is below -67 dBm. Consider "
                             "moving the router, adding an AP/mesh node, or an "
                             "external antenna on the gateway.")
        else:
            lines.append(f"'{target}' was not seen on band {band} at any location.")
    else:
        lines.append("No --ssid given; showing the RF environment only.")

    lines.append("")
    lines.append("Quietest channels (if the gateway hosts its own AP):")
    for b, loads in channel_congestion(results).items():
        top = ", ".join(f"ch {c.channel} ({c.networks} nets, {c.power_dbm} dBm)"
                        for c in loads[:3])
        lines.append(f"  {b} GHz: {top}")

    lines.append("")
    lines.append("Networks heard:")
    for n in ssid_summary(results)[:25]:
        lines.append(f"  {n['ssid'][:28]:<28} best {n['best']:>6.1f} dBm  "
                     f"{'/'.join(sorted(n['bands']))} GHz  ch "
                     f"{','.join(map(str, sorted(n['channels'])))}  {n['security']}")
    return "\n".join(lines)


def _bar(value: float, lo: float, hi: float, color: str, width: int = 160) -> str:
    frac = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return (f'<svg width="{width}" height="12" role="img" aria-label="{value}">'
            f'<rect width="{width}" height="12" rx="3" fill="var(--track)"/>'
            f'<rect width="{frac * width:.0f}" height="12" rx="3" fill="{color}"/></svg>')


def _floor_plan(results: List[LocationResult]) -> str:
    pts = [r for r in results if r.x is not None and r.y is not None]
    if len(pts) < 2:
        return ""
    xs, ys = [r.x for r in pts], [r.y for r in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    spanx, spany = (maxx - minx) or 1, (maxy - miny) or 1
    W, H, pad = 640, max(200, int(640 * spany / spanx)), 40
    H = min(H, 640)
    dots = []
    for r in pts:
        cx = pad + (r.x - minx) / spanx * (W - 2 * pad)
        cy = pad + (r.y - miny) / spany * (H - 2 * pad)
        c = VERDICT_COLORS[r.verdict]
        label = html.escape(r.location)
        sig = f"{r.target.mean} dBm" if r.target else "not seen"
        dots.append(
            f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="14" fill="{c}" opacity="0.85">'
            f'<title>{label}: {sig}</title></circle>'
            f'<text x="{cx:.0f}" y="{cy + 30:.0f}" text-anchor="middle" '
            f'class="lbl">{label}</text>'
        )
    return (f'<h2>Floor plan</h2><p class="muted">Positions from --xy, coloured by '
            f'target signal.</p><svg viewBox="0 0 {W} {H + 20}" class="plan">'
            f'{"".join(dots)}</svg>')


def html_report(results: List[LocationResult], target: Optional[str], band: str,
                survey_path: str) -> str:
    e = html.escape
    rows = []
    for i, r in enumerate(results, 1):
        t = r.target
        color = VERDICT_COLORS[r.verdict]
        rows.append(
            "<tr>"
            f"<td>{i}</td><td><b>{e(r.location)}</b></td>"
            f"<td>{_fmt(r.score)}</td>"
            f'<td><span class="pill" style="background:{color}">{r.verdict}</span></td>'
            f"<td>{_bar(t.mean, -90, -40, color) if t else ''} {_fmt(t and t.mean, ' dBm')}</td>"
            f"<td>{_fmt(t and t.min)} / {_fmt(t and t.max)}</td>"
            f"<td>{_fmt(t and t.stdev, ' dB')}</td>"
            f"<td>{f'{t.seen}/{t.scans}' if t else '-'}</td>"
            f"<td>{_fmt(t and t.channel)}{' (' + str(t.width) + ' MHz)' if t and t.width else ''}</td>"
            f"<td>{len(r.interferers) if t else '-'}</td>"
            f"<td>{_fmt(r.sir, ' dB')}</td>"
            "</tr>"
        )
    best = next((r for r in results if r.target), None)
    if target and best:
        rec = (f'<div class="rec"><div class="muted">Recommended gateway location</div>'
               f'<div class="big">{e(best.location)}</div>'
               f'<div>{best.verdict} &middot; {best.target.mean} dBm mean &middot; '
               f'score {best.score}/100 &middot; channel {best.target.channel}</div>')
        if best.target.mean < -67:
            rec += ('<p class="warn">Even the best spot is weaker than -67 dBm. Consider '
                    'moving the router, adding a mesh node, or a gateway with an '
                    'external antenna.</p>')
        rec += "</div>"
    elif target:
        rec = (f'<div class="rec warn">"{e(target)}" was not seen on the {e(band)} GHz '
               f'band at any surveyed location.</div>')
    else:
        rec = ('<div class="rec">No target SSID given. Re-run with '
               '<code>--ssid "YourNetwork"</code> to rank locations.</div>')

    chan_html = []
    for b, loads in channel_congestion(results).items():
        items = "".join(
            f"<tr><td>{c.channel}</td><td>{c.networks}</td><td>{c.power_dbm} dBm</td>"
            f"<td>{_bar(c.power_dbm, -100, -30, '#cf222e', 120)}</td></tr>"
            for c in loads[:8])
        chan_html.append(
            f'<div><h3>{b} GHz</h3><table><tr><th>Ch</th><th>Networks</th>'
            f'<th>Overlap power</th><th></th></tr>{items}</table></div>')

    net_rows = "".join(
        f"<tr><td>{e(n['ssid'])}</td><td>{n['best']:.1f} dBm</td>"
        f"<td>{'/'.join(sorted(n['bands']))}</td>"
        f"<td>{', '.join(map(str, sorted(n['channels'])))}</td>"
        f"<td>{len(n['bssids'])}</td><td>{e(n['security'])}</td>"
        f"<td>{len(n['locations'])}</td></tr>"
        for n in ssid_summary(results))

    detail = []
    tgt_cls = ' class="tgt"'
    for r in results:
        aps = "".join(
            f"<tr{tgt_cls if r.target and a.bssid == r.target.bssid else ''}>"
            f"<td>{e(a.ssid) or '<i>hidden</i>'}</td><td><code>{a.bssid}</code></td>"
            f"<td>{a.band}</td><td>{a.channel}</td><td>{a.mean}</td>"
            f"<td>{a.stdev}</td><td>{a.seen}/{a.scans}</td>"
            f"<td>{_fmt(a.station_count)}</td><td>{_fmt(a.utilization, '%')}</td></tr>"
            for a in r.aps)
        detail.append(
            f"<details><summary><b>{e(r.location)}</b> &middot; {r.scans} scans "
            f"&middot; {len(r.aps)} APs</summary><table><tr><th>SSID</th><th>BSSID</th>"
            f"<th>Band</th><th>Ch</th><th>Mean dBm</th><th>SD</th><th>Seen</th>"
            f"<th>Clients</th><th>Util</th></tr>{aps}</table></details>")

    weights = ", ".join(f"{k} {int(w * 100)}%" for k, w in WEIGHTS.items())
    title = f"Wi-Fi survey: {e(target)}" if target else "Wi-Fi survey"
    ranking = (
        f"<h2>Location ranking</h2><p class='muted'>Score weights: {weights}. "
        f"SIR = target signal minus combined power of other networks overlapping its "
        f"channel.</p><div class='scroll'><table><tr><th>#</th><th>Location</th>"
        f"<th>Score</th><th>Verdict</th><th>Mean RSSI</th><th>Min / Max</th><th>SD</th>"
        f"<th>Seen</th><th>Channel</th><th>Overlapping APs</th><th>SIR</th></tr>"
        f"{''.join(rows)}</table></div>" if target else "")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#fff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --track:#eaeef2;
        --card:#f6f8fa; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --line:#30363d;
          --track:#21262d; --card:#161b22; }} }}
body {{ background:var(--bg); color:var(--fg); margin:0 auto; max-width:1100px;
       padding:24px 16px; font:14px/1.5 system-ui,-apple-system,sans-serif; }}
h1 {{ margin:0 0 4px; }} h2 {{ margin-top:32px; }}
.muted {{ color:var(--muted); }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
         white-space:nowrap; }}
th {{ font-weight:600; color:var(--muted); font-size:12px; }}
.scroll {{ overflow-x:auto; }}
.pill {{ color:#fff; padding:2px 8px; border-radius:10px; font-size:12px; }}
.rec {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
       padding:16px; margin-top:16px; }}
.big {{ font-size:28px; font-weight:700; }}
.warn {{ color:#d1580a; }}
.chans {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
         gap:16px; }}
details {{ margin:8px 0; }} summary {{ cursor:pointer; padding:4px 0; }}
tr.tgt td {{ background:rgba(76,154,42,.15); }}
.plan {{ width:100%; max-width:640px; background:var(--card); border-radius:8px; }}
.plan .lbl {{ fill:var(--fg); font-size:12px; }}
svg {{ vertical-align:middle; }}
</style></head><body>
<h1>{title}</h1>
<div class="muted">{e(survey_path)} &middot; {len(results)} locations &middot;
band {e(band)} GHz &middot; generated {time.strftime('%Y-%m-%d %H:%M')}</div>
{rec}
{ranking}
{_floor_plan(results) if target else ''}
<h2>Channel congestion</h2>
<p class="muted">Lower overlap power is quieter. Use this to pick a channel if the
gateway runs its own access point for the IoT devices.</p>
<div class="chans">{''.join(chan_html)}</div>
<h2>Networks heard</h2>
<div class="scroll"><table><tr><th>SSID</th><th>Best RSSI</th><th>Bands</th>
<th>Channels</th><th>APs</th><th>Security</th><th>Locations</th></tr>{net_rows}</table></div>
<h2>Per-location detail</h2>
{''.join(detail)}
</body></html>
"""
