# netscan

A Wi-Fi survey tool for a **Raspberry Pi 3B + NETGEAR USB Wi-Fi adapter**. Carry
the Pi to each spot where the IoT gateway could go. It records the RSSI of every
nearby network and ranks the spots, so you can pick where the gateway should sit.

It uses only the Python standard library and the `iw` tool, so nothing has to
be installed with pip.

## How it decides

The gateway needs a strong, steady link to your Wi-Fi network and little
competition on that channel. For the network you name (`--ssid`), each location
gets a score from 0 to 100:

| Part | Weight | What it measures |
|---|---|---|
| Signal | 55% | Mean RSSI of the strongest AP for your SSID (-90 dBm = 0, -50 dBm = 100) |
| Stability | 15% | How much the RSSI moves around (standard deviation) |
| Reliability | 15% | Share of scans in which your network was seen at all |
| Interference | 15% | Your signal compared with the combined power of other networks overlapping its channel (SIR) |

Each location also gets a rating from its mean RSSI:

| Rating | RSSI |
|---|---|
| Excellent | -60 dBm or stronger |
| Good | -60 to -67 dBm |
| Fair | -67 to -75 dBm |
| Poor | -75 to -82 dBm |
| Unusable | below -82 dBm |

Aim for **-67 dBm or better** at the gateway.

The report also ranks channels by how crowded they are (1/6/11 on 2.4 GHz). Use
this if the gateway runs its own access point for the IoT devices.

The default band is **2.4 GHz**, since most IoT radios (ESP32, many smart plugs and
so on) only support 2.4 GHz. If the gateway's uplink will use 5 GHz, pass
`--band 5`. Use `--band any` to consider both bands.

## Hardware notes

- **Pi 3B:** the built-in radio is `wlan0` and only supports 2.4 GHz. The NETGEAR
  adapter normally shows up as `wlan1`, and netscan uses it by default. You can
  still use `wlan0` over SSH (or Ethernet) to control the Pi while it surveys.
- **Power:** the Pi 3B and a USB Wi-Fi adapter together draw a lot of current.
  Use a battery pack that can supply 2.5 A, or the adapter may drop out. If you
  see a lightning-bolt icon or `Under-voltage detected` in `dmesg`, the battery
  pack can't supply enough current.
- **Drivers:** some NETGEAR models work as soon as you plug them in and some
  need an extra driver. Run `lsusb` to find the model, then
  `sudo netscan interfaces` to see which driver it loaded.

  | Model | Chipset | Linux driver |
  |---|---|---|
  | **A8000** (Wi-Fi 6E) | MT7921AU | `mt7921u`, built into the kernel. USB ID `0846:9060` is recognised from kernel 6.1 on (check with `uname -r`). Needs the MediaTek firmware files; `setup_pi.sh` installs them |
  | A6210 | MT7612U | `mt76x2u`, built into the kernel. Works out of the box |
  | WNA1100 | AR9271 | `ath9k_htc`, built into the kernel. Works out of the box |
  | WN111v2 | AR9170 | `carl9170`, built into the kernel |
  | A6150 | RTL8822BU | `rtw88_8822bu` (kernel 6.2+, which current Raspberry Pi OS has) |
  | A6100 | RTL8811AU | Needs an out-of-tree `8821au` driver (DKMS) |
  | A7000 | RTL8814AU | Needs an out-of-tree `8814au` driver (DKMS) |
  | WNA3100 / A6200 | Broadcom | Poor or no Linux support. Use a different adapter if you can |

  Any adapter whose driver uses cfg80211 works with `iw scan`.
- **NETGEAR A8000 notes:**
  - The Pi 3B only has USB 2.0 ports. That's fine, because scanning doesn't
    need much bandwidth.
  - The A8000 can also hear 6 GHz networks. Linux only scans the 6 GHz band if
    the Pi's Wi-Fi country is set. To set it, run
    `sudo raspi-config nonint do_wifi_country US` (use your own country code).
    `setup_pi.sh` warns you if the country isn't set.
  - 6 GHz access points are mostly found by listening rather than probing, so
    one scan can miss some. Take more scans per location (`-n 10`) if 6 GHz
    matters to you.
  - Most IoT devices can't use 6 GHz, so keep the default `--band 2.4` for the
    gateway's uplink unless you know the gateway uses 5 or 6 GHz.
  - If `sudo netscan interfaces` doesn't show the adapter, check whether it
    loaded:
    - `lsusb` should list a NETGEAR device.
    - `dmesg | grep -i mt7921` should show the driver loading its firmware.
- **RSSI differs between radios.** Different radios and antennas report
  different RSSI for the same signal, so use the readings to compare locations
  rather than as absolute values. If the gateway has a weaker antenna than the
  adapter, aim for a few dB of extra margin.

## Setup on the Pi

Copy this folder to the Pi (for example with `scp -r netscan pi@raspberrypi.local:`),
then run:

```bash
cd ~/netscan && sudo ./scripts/setup_pi.sh
```

If the scans keep failing with "Device or resource busy", stop NetworkManager
from managing the adapter. This setting lasts until the next reboot:

```bash
sudo ./scripts/setup_pi.sh --unmanage wlan1
```

## Usage

Scanning needs root, so every scan command uses `sudo`.

**1. Check the adapter**

```bash
sudo netscan interfaces
```

**2. Look around (optional).** This shows a refreshing view of your network's
signal and a bar meter. It's useful for getting a rough idea while you walk
around:

```bash
sudo netscan live -s "MyHomeWiFi"
```

**3. Survey the candidate spots.** Interactive mode prompts you for a location
name, takes 6 scans about 2 s apart, and then prompts for the next location:

```bash
sudo netscan survey -s "MyHomeWiFi" -d house.db
```

```
Location> Hallway shelf @ 2,5
  scan 1/6: 23 APs, MyHomeWiFi -58 dBm (Excellent)
  ...
Location> Garage @ 12,1
Location>            <- blank line to finish
```

The `@ x,y` part (in metres) is optional. If you add it, the HTML report shows
the spots on a floor plan, coloured by signal. You can also survey one spot
without the prompts:
`sudo netscan survey -s "MyHomeWiFi" -l "Kitchen" -n 10`.

Tips:

- Hold the Pi at the height and place the gateway would actually sit, such as a
  shelf or the inside of a cabinet. Don't hold it at chest height.
- Survey at a busy time of day as well as a quiet one. More neighbours'
  networks are active in the evening.
- Surveying a location again adds more scans to it. To start that location over,
  run `netscan locations -d house.db --delete "Kitchen"`.

**4. Get the ranking** (example output from synthetic test data)

```bash
netscan report -d house.db -s "MyHomeWiFi" --html report.html
```

```
Gateway placement ranking for SSID 'MyHomeWiFi' (band: 2.4)

 #  Location             Score  Verdict     Mean    Min   SD  Seen   Ch       SIR
---------------------------------------------------------------------------------
 1  Hallway shelf         91.4  Excellent  -54.7  -56.8  1.1   6/6    6   25.1 dB
 2  Living room           68.4  Good       -63.6  -65.4  1.4   6/6    6    7.9 dB
 3  Office desk           54.9  Fair       -69.7  -71.8  1.6   6/6    6   -4.0 dB
 4  Garage                37.3  Poor       -79.0  -81.3  1.5   4/6    6  -10.9 dB

Recommended spot: Hallway shelf (Excellent, -54.7 dBm, score 91.4)
```

To view the HTML report, copy it to your computer
(`scp pi@raspberrypi.local:netscan/report.html .`) and open it in a browser.

**Other commands**

| Command | What it does |
|---|---|
| `sudo netscan scan -s "MyHomeWiFi"` | Runs one scan and lists every AP |
| `netscan locations -d house.db` | Lists the surveyed locations |
| `netscan export -d house.db --csv survey.csv` | Exports the raw data for a spreadsheet |
| `netscan ingest -d house.db -l "Attic" scan1.txt` | Imports saved `iw dev wlan1 scan` output |

## Development

```bash
python3 -m unittest discover -s tests -t . -v
```

The tests use saved `iw` output, so they run on any machine, not just a Pi.
