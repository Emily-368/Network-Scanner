"""Build fake `iw scan` text so tests don't need real hardware."""


def iw_block(bssid, ssid, freq, signal, channel=None, rsn=True):
    lines = [f"BSS {bssid}(on wlan1)", f"\tfreq: {freq}",
             "\tcapability: ESS Privacy (0x0411)", f"\tsignal: {signal:.2f} dBm",
             f"\tSSID: {ssid}"]
    if channel:
        lines.append(f"\tDS Parameter set: channel {channel}")
    if rsn:
        lines += ["\tRSN:\t * Version: 1", "\t\t * Authentication suites: PSK"]
    return "\n".join(lines) + "\n"
