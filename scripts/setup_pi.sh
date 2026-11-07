#!/usr/bin/env bash
# One-time setup on the Raspberry Pi. Run from the project folder:
#   sudo ./scripts/setup_pi.sh            # install deps + `netscan` command
#   sudo ./scripts/setup_pi.sh --unmanage wlan1
#        ...also tell NetworkManager to stop using wlan1 so its own background
#        scans don't collide with ours ("Device or resource busy").
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq iw usbutils python3 >/dev/null

echo "==> Installing /usr/local/bin/netscan -> $HERE"
cat > /usr/local/bin/netscan <<WRAP
#!/bin/sh
PYTHONPATH="$HERE" exec python3 -m netscan "\$@"
WRAP
chmod +x /usr/local/bin/netscan

echo "==> Checking MediaTek MT7921 firmware (NETGEAR A8000)"
if ls /lib/firmware/mediatek/WIFI_RAM_CODE_MT7961_1.bin* >/dev/null 2>&1; then
  echo "   firmware present"
else
  echo "   firmware missing; installing firmware-misc-nonfree"
  apt-get install -y -qq firmware-misc-nonfree >/dev/null \
    && echo "   installed. Unplug and replug the adapter (or reboot) to load it." \
    || echo "   could not install; see README 'NETGEAR A8000 notes'"
fi
modprobe mt7921u 2>/dev/null || true

echo "==> Wi-Fi regulatory country"
country=$(iw reg get 2>/dev/null | awk '/^country/ {sub(":","",$2); print $2; exit}')
if [[ -z "$country" || "$country" == "00" ]]; then
  echo "   NOT SET - 6 GHz (and some 5 GHz) channels won't be scanned."
  echo "   Fix: sudo raspi-config nonint do_wifi_country US   (use your country code)"
else
  echo "   $country"
fi

echo "==> NETGEAR USB devices (vendor 0846):"
lsusb | grep -i '0846:' || echo "   none found - is the adapter plugged in?"

echo "==> Wireless interfaces:"
for dev in /sys/class/net/*; do
  [[ -d "$dev/wireless" || -d "$dev/phy80211" ]] || continue
  name=$(basename "$dev")
  drv=$(basename "$(readlink -f "$dev/device/driver" 2>/dev/null)" 2>/dev/null || echo "?")
  echo "   $name  driver=$drv"
done

if [[ "${1:-}" == "--unmanage" && -n "${2:-}" ]]; then
  if command -v nmcli >/dev/null; then
    nmcli device set "$2" managed no && echo "==> NetworkManager no longer manages $2"
  else
    echo "nmcli not found; skipping --unmanage"
  fi
fi

echo
echo "Done. Try:  sudo netscan interfaces   then   sudo netscan live -s \"YourSSID\""
