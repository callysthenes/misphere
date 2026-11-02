#!/usr/bin/env python3
"""Xiaomi Mi Sphere 360 (MadV QJXJ01FJ) control CLI over WiFi.

Protocol: JSON payloads over TCP 192.168.42.1:7878.
File system over HTTP 192.168.42.1:50422, live preview over RTSP rtsp://192.168.42.1/live.

Requires: laptop connected to the camera WiFi (MJXJ-XXXXXX).
Uses Python stdlib only.
"""
import argparse
import http.client
import json
import os
import socket
import sys
import time
from collections import deque

CAM_IP = "192.168.42.1"
CAM_TCP = 7878
CAM_HTTP = 50422

# message ids
CONNECT = 257
DISCONNECT = 258
REGISTER_TCP = 261
GET_WIFI = 1539
GET_SERIAL_NO = 4097
GET_STORAGE = 4358
GET_DEVICE = 4364
GET_CAMERA = 4365
BATTERY_STATUS = 4361
CHANGE_DIRECTORY = 1283
LIST_DIRECTORY = 1282
DELETE_FILE = 1281
FILE_INFO = 1026
FILE_PREVIEW = 1025
SWITCH_MODE = 4611
PHOTO_PRESS = 4864
PHOTO_LONGPRESS = 4868
VIDEO_REC_START = 5028
VIDEO_REC_STOP = 514
TURN_OFF = 6155
SET_LED = 6156
SET_BUZZER_VOLUME = 6145
AUTO_TURN_OFF = 6151
PHOTO_RES = 4872
PHOTO_WB = 5168
PHOTO_EV = 5169
PHOTO_ISO = 5172
VIDEO_RES = 4612
VIDEO_WB = 5136
VIDEO_EV = 5137

PHOTO_RES_OPTS = {
    "raw": 0,
    "stitched-1728": 1,
    "stitched-full": 2,
    "raw-plus": 3,
}
VIDEO_RES_OPTS = {
    "3456x1728@30": 0,
    "2304x1152@30": 1,
    "2304x1152@60": 2,
    "2048x512@120-top": 7,
    "2048x512@120-bottom": 9,
    "3456x1728@30-hq": 10,
}
WB_OPTS = {"auto": 0, "outdoors": 1, "overcast": 2, "incandescent": 3, "fluorescent": 4}
ISO_OPTS = [0, 50, 100, 200, 400, 800, 1600]

SD_BASE = "/tmp/SD0/DCIM/"


class Camera:
    def __init__(self, ip=CAM_IP, port=CAM_TCP, timeout=6.0):
        self.addr = (ip, port)
        self.timeout = timeout
        self.sock = None
        self.buf = b""
        self.pending = deque()
        self.token = 0

    def _recv_json(self):
        """Receive the next JSON object, tolerating fragmented/concatenated frames."""
        dec = json.JSONDecoder()
        while True:
            if self.buf:
                try:
                    obj, idx = dec.raw_decode(self.buf.decode(errors="replace"))
                    self.buf = self.buf[idx:].lstrip()
                    return obj
                except json.JSONDecodeError:
                    pass
            self.sock.settimeout(self.timeout)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("camera closed connection")
            self.buf += chunk

    def _wait_msg(self, msg_id):
        stash = deque()
        while True:
            obj = self.pending.popleft() if self.pending else self._recv_json()
            if obj.get("msg_id") == msg_id:
                self.pending.extendleft(reversed(stash))
                return obj
            stash.append(obj)

    def connect(self):
        self.sock = socket.create_connection(self.addr, timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        resp = self.request(CONNECT, token=0)
        self.token = resp.get("param", 3)
        return self.token

    def request(self, msg_id, params=None, token=None):
        payload = {"msg_id": msg_id, "token": self.token if token is None else token}
        if params:
            for k, v in params.items():
                payload[k] = str(v) if k == "param" else v
        self.sock.sendall(json.dumps(payload).encode())
        return self._wait_msg(msg_id)

    def close(self):
        if self.sock:
            try:
                self.request(DISCONNECT, token=self.token)
            except Exception:
                pass
            self.sock.close()
            self.sock = None

    # convenience
    def get_info(self):
        info = {}
        for mid, key in ((GET_DEVICE, "device"), (GET_CAMERA, "camera"),
                         (GET_STORAGE, "storage"), (BATTERY_STATUS, "battery")):
            try:
                resp = self.request(mid)
                info[key] = {k: v for k, v in resp.items() if k not in ("msg_id", "token")}
            except Exception as e:
                info[key] = f"error: {e}"
        return info

    def mode(self):
        return self.request(GET_CAMERA).get("mode")

    def set_mode(self, mode):
        mode = 1 if mode == "photo" else 0
        return self.request(SWITCH_MODE, {"param": mode})

    def ensure_photo_mode(self):
        if self.mode() != 1:
            self.set_mode("photo")
            time.sleep(0.6)

    def take_photo(self):
        return self.request(PHOTO_PRESS)

    def video_start(self):
        return self.request(VIDEO_REC_START)

    def video_stop(self):
        return self.request(VIDEO_REC_STOP)

    def ls(self, path=SD_BASE):
        resp = self.request(CHANGE_DIRECTORY, {"param": path})
        if resp.get("rval", -1) != 0:
            raise RuntimeError(f"cannot cd {path}: {resp}")
        return self.request(LIST_DIRECTORY)

    def http_get(self, remotepath, localpath):
        conn = http.client.HTTPConnection(CAM_IP, CAM_HTTP, timeout=self.timeout)
        try:
            conn.request("GET", remotepath)
            resp = conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {remotepath}")
            with open(localpath, "wb") as fh:
                total = 0
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total += len(chunk)
            return total
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser(description="Xiaomi Mi Sphere 360 control CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="battery, storage, camera state")
    sub.add_parser("photo", help="take a photo")
    sub.add_parser("video-start", help="start recording")
    sub.add_parser("video-stop", help="stop recording")
    p = sub.add_parser("mode", help="switch to photo or video mode")
    p.add_argument("value", choices=["photo", "video"])
    sub.add_parser("off", help="power off camera")
    p = sub.add_parser("ls", help="list directory on SD (default DCIM)")
    p.add_argument("path", nargs="?", default=SD_BASE)
    p = sub.add_parser("get", help="download file over HTTP")
    p.add_argument("remotepath", help="e.g. /IMG_20261102_101010.JPG (relative to HTTP root) or full URL path")
    p.add_argument("localpath", nargs="?", default=".")
    p = sub.add_parser("set", help="set option, e.g. --photo-res raw")
    p.add_argument("--photo-res", choices=PHOTO_RES_OPTS)
    p.add_argument("--video-res", choices=VIDEO_RES_OPTS)
    p.add_argument("--wb", choices=WB_OPTS)
    p.add_argument("--iso", type=int, choices=ISO_OPTS)
    p.add_argument("--ev", type=float)
    p.add_argument("--led", type=int, choices=[0, 1])
    p.add_argument("--buzzer", type=int)
    p.add_argument("--auto-off", type=int, help="minutes, 0 to disable")
    p = sub.add_parser("raw", help="send raw msg_id with optional param")
    p.add_argument("msg_id", type=int)
    p.add_argument("param", nargs="?", default=None)
    sub.add_parser("keepalive", help="keep the camera awake (Ctrl+C to stop)")

    args = ap.parse_args()
    cam = Camera()
    try:
        cam.connect()
        if args.cmd == "info":
            print(json.dumps(cam.get_info(), indent=2, default=str))
        elif args.cmd == "photo":
            cam.ensure_photo_mode()
            print(json.dumps(cam.take_photo()))
        elif args.cmd == "video-start":
            print(json.dumps(cam.video_start()))
        elif args.cmd == "video-stop":
            print(json.dumps(cam.video_stop()))
        elif args.cmd == "mode":
            print(json.dumps(cam.set_mode(args.value)))
        elif args.cmd == "off":
            print(json.dumps(cam.request(TURN_OFF)))
        elif args.cmd == "ls":
            print(json.dumps(cam.ls(args.path), indent=2, default=str))
        elif args.cmd == "get":
            path = args.remotepath if args.remotepath.startswith("/") else "/" + args.remotepath
            name = os.path.basename(path)
            local = args.localpath if os.path.isdir(args.localpath) or not os.path.splitext(args.localpath)[1] \
                else os.path.dirname(args.localpath) or "."
            target = args.localpath if os.path.splitext(args.localpath)[1] else os.path.join(args.localpath, name)
            size = cam.http_get(path, target)
            print(f"saved {target} ({size} bytes)")
        elif args.cmd == "set":
            for attr, mid, fmt in (("photo_res", PHOTO_RES, PHOTO_RES_OPTS),
                                   ("video_res", VIDEO_RES, VIDEO_RES_OPTS),
                                   ("wb", PHOTO_WB, WB_OPTS), ("iso", PHOTO_ISO, None),
                                   ("ev", PHOTO_EV, None), ("led", SET_LED, None),
                                   ("buzzer", SET_BUZZER_VOLUME, None), ("auto_off", AUTO_TURN_OFF, None)):
                val = getattr(args, attr)
                if val is None:
                    continue
                if attr == "photo_res":
                    val = PHOTO_RES_OPTS[val]
                elif attr == "video_res":
                    val = VIDEO_RES_OPTS[val]
                elif attr == "wb":
                    val = WB_OPTS[val]
                elif attr == "ev":
                    val = int(2 * val)
                print(attr, json.dumps(cam.request(mid, {"param": val})))
        elif args.cmd == "raw":
            params = {"param": args.param} if args.param is not None else None
            print(json.dumps(cam.request(args.msg_id, params)))
        elif args.cmd == "keepalive":
            try:
                while True:
                    resp = cam.request(GET_CAMERA)
                    print(time.strftime("%H:%M:%S"),
                          "awake, mode:", "photo" if resp.get("mode") == 1 else "video")
                    time.sleep(25)
            except KeyboardInterrupt:
                print("\nstopped")
    finally:
        cam.close()


if __name__ == "__main__":
    main()
