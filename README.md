# misphere — access the Xiaomi Mi Sphere 360° camera from Linux

Control the **Xiaomi Mi Sphere 360° camera** (a.k.a. *MadV*, *Mijia Mi Sphere 4K*,
model **QJXJ01FJ**, CMIIT ID 2016DP6594, made by Beijing MadV Technology) from a
Linux laptop over WiFi — no proprietary app, no Android emulation.

Two small tools, zero dependencies:

| File | What it is |
|---|---|
| `misphere` | bash + NetworkManager helper: connect/disconnect the camera WiFi, status, open file browser, play live stream |
| `misphere.py` | Python 3 (stdlib only) control CLI: camera info, settings, photo/video capture, file listing/download, raw protocol access |

## What works

- **Live dual-lens preview** — RTSP `rtsp://192.168.42.1/live`, H.264
  1440×720 (both 190° fisheyes side-by-side) @ 29.97 fps
- **Camera control** over TCP `192.168.42.1:7878` — battery, storage,
  firmware info, mode switching (photo/video), remote shutter, video
  start/stop, resolution / ISO / WB / EV / LED / buzzer settings
- **Files on the SD card** — HTTP file server at `http://192.168.42.1:50422/`
  (browse and download DCIM)
- **Power off** the camera remotely

> **USB is (almost) useless**: the camera's micro-USB port charges but does not
> reliably enumerate as a USB device. WiFi is the way.

## Requirements

- Linux with **NetworkManager** (nmcli) for the WiFi helper
- Python 3 (no pip packages needed)
- `ffmpeg` (ffplay/ffprobe) for the live stream — optional
- A **microSD card** in the camera for photo/video capture and the file server
  (live preview works without one)

## Setup (one time)

Create a NetworkManager profile for the camera's hotspot (SSID prefix `MJXJ`,
factory WPA2 password `12345678`):

```bash
IFACE=wlp2s0   # your wifi interface (ip link)
nmcli con add type wifi ifname "$IFACE" con-name misphere ssid "MJXJ-XXXXXX" \
    802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk 12345678
# don't let the camera (which has no internet) hijack your default route,
# and prefer it over your home networks while it is visible:
nmcli con modify misphere ipv4.never-default yes ipv6.never-default yes \
    connection.autoconnect-priority 100
```

## Usage

```bash
# 1. wake the camera: short-press the shutter, then short-press the WiFi button
./misphere up                    # scan, connect, verify camera + internet state
./misphere status                # wifi ssid / camera / port / internet
./misphere stream                # watch the live dual-fisheye preview (ffplay)
./misphere files                 # browse + download SD card contents in a browser

python3 misphere.py info         # battery, storage, firmware, serial
python3 misphere.py mode video   # switch mode
python3 misphere.py photo        # capture a photo
python3 misphere.py video-start  # record
python3 misphere.py video-stop
python3 misphere.py ls           # list /tmp/SD0/DCIM over the control protocol
python3 misphere.py get /IMG_20261102_101010.JPG ./shots/
python3 misphere.py set --photo-res raw --iso 100 --wb outdoors
python3 misphere.py keepalive    # hold a control session so the camera stays awake
python3 misphere.py off          # power the camera off
./misphere down                  # disconnect -> your normal WiFi/internet returns
```

### Stitching

The camera outputs dual-fisheye. JPEGs option `--photo-res` supports
in-camera stitched output (`3456x1728` or `6912x3456`); for video use
[PanoramaStudio], [Kdenlive + Hugin], or Xiaomi's own (Windows/macOS) stitcher.

## Camera quirks (learned the hard way)

This camera has… character. Things to know:

1. **Hotspot vs client mode** — a *short* press of the WiFi button sometimes
   leaves it in client/search mode (blue LED blinking, no AP broadcast).
   **Hold the WiFi button 8–10 s** until the LED flashes rapidly to force
   AP (hotspot) mode.
2. **Aggressive auto-standby** — WiFi dies after ~2 min idle. The CLI sends
   `msg_id 4362` (standby off) on request; `keepalive` holds a session.
3. **One radio** — while connected to the camera you have no internet unless
   another uplink (ethernet/4G) is active. `misphere` profiles use
   `never-default` so your routing is never hijacked. `./misphere down`
   restores normal WiFi.
4. **Fragile RTSP server** — killing a stream client (`timeout`, Ctrl+C at the
   wrong moment) can crash the camera's WiFi stack until you power-cycle it.
   Close streams gracefully when possible.
5. **No SD card** → photos fail with `rval: -50`, storage stats are zero, and
   the HTTP file server (port 50422) does not start. Live preview still works.
6. The charging LED/USB icon only means power: **USB data never enumerates**
   (tested with multiple cables) — file transfer is WiFi-only.

## Protocol notes (for hacking further)

Everything lives in `misphere.py` and is deliberately readable:

| Endpoint | Purpose |
|---|---|
| `tcp://192.168.42.1:7878` | control: JSON messages `{"msg_id": N, "param": ..., "token": N}`; first `CONNECT (257)` with `token: 0` returns your session token |
| `rtsp://192.168.42.1/live` | live H.264 preview (1440×720 dual fisheye) |
| `http://192.168.42.1:50422/` | DCIM file server (starts when an SD card is present) |
| `tcp://192.168.42.1:8787` | thumbnail/IDR preview push — register your IP first with `msg_id 261` |

Message IDs (connect, get/set, capture, settings…) are named constants at the
top of `misphere.py`; `python3 misphere.py raw <msg_id> [param]` lets you poke
unknown IDs at your own risk.

## Credits & provenance

- Protocol reverse-engineering based on the excellent PoC
  [rnbguy/pysphere](https://github.com/rnbguy/pysphere) (Kivy app) — this repo
  re-implements the useful parts as a dependency-free CLI.
- Background/protocol notes: [niclet/xiaomi_hack](https://github.com/niclet/xiaomi_hack)
  (different camera, same era Xiaomi firmware patterns).

## Disclaimer

Unofficial tool for a discontinued camera. You use it at your own risk —
the authors are not responsible for bricked cameras, lost footage, or drained
batteries.

[PanoramaStudio]: https://www.panorama-studio.info/
[Kdenlive + Hugin]: https://userbase.kde.org/Kdenlive/Manual
