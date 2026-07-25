# -*- coding: utf-8 -*-
# test_speak_once.py  –  ส่ง speech.mp3 ให้ Pepper พูด 1 รอบ แล้วจบโปรแกรม
# รอจบตามความยาวจริงของไฟล์เสียง (parse MP3 frame) + สัญญาณ /audio_done จาก tablet
# Run: python test_speak_once.py   (Python 2 / qi framework เหมือน pepper_main.py)

import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from naoqi_path import add_sdk_to_path
add_sdk_to_path()

import qi
import socket
import threading
import BaseHTTPServer
import SocketServer
import re
import time
import urllib
import cgi

PEPPER_IP   = "172.101.99.97"
STREAM_PORT = 8080          # ต้องเป็น port ที่ firewall เปิดแล้ว (เหมือน pepper_main.py) — ปิด pepper_main.py ก่อนรัน
VOLUME      = 80
SPEECH_FILE = "speech.mp3"
TEST_TEXT   = u"ทดสอบเสียง speech.mp3"

_HTML_DIR = _os.path.dirname(_os.path.abspath(__file__))

# ── MP3 duration (นับ frame จริง ไม่ใช้ lib ภายนอก) ─────────────────────────
_BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
_BITRATES_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
_SAMPLERATES   = {3: [44100, 48000, 32000],   # MPEG1
                  2: [22050, 24000, 16000],   # MPEG2
                  0: [11025, 12000, 8000]}    # MPEG2.5

def mp3_duration(data):
    """คืนความยาวเสียงเป็นวินาที โดยเดินไล่ MP3 frame ทีละ frame (Layer III)"""
    pos = 0
    # ข้าม ID3v2 tag ถ้ามี
    if data[:3] == b"ID3" and len(data) > 10:
        size = ((ord(data[6]) & 0x7F) << 21) | ((ord(data[7]) & 0x7F) << 14) | \
               ((ord(data[8]) & 0x7F) << 7) | (ord(data[9]) & 0x7F)
        pos = 10 + size
    duration = 0.0
    n = len(data)
    while pos + 4 <= n:
        b1, b2 = ord(data[pos]), ord(data[pos + 1])
        if b1 != 0xFF or (b2 & 0xE0) != 0xE0:
            pos += 1
            continue
        version = (b2 >> 3) & 0x03          # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer   = (b2 >> 1) & 0x03          # 1=Layer III
        if version == 1 or layer != 1:
            pos += 1
            continue
        b3 = ord(data[pos + 2])
        br_idx, sr_idx = (b3 >> 4) & 0x0F, (b3 >> 2) & 0x03
        if br_idx in (0, 15) or sr_idx == 3:
            pos += 1
            continue
        bitrate    = (_BITRATES_V1L3 if version == 3 else _BITRATES_V2L3)[br_idx] * 1000
        samplerate = _SAMPLERATES[version][sr_idx]
        padding    = (b3 >> 1) & 0x01
        if version == 3:
            frame_len, samples = 144 * bitrate // samplerate + padding, 1152
        else:
            frame_len, samples = 72 * bitrate // samplerate + padding, 576
        if frame_len <= 0:
            pos += 1
            continue
        duration += float(samples) / samplerate
        pos += frame_len
    return duration

# ── หา IP ของเครื่องนี้ฝั่งเดียวกับ Pepper ───────────────────────────────────
def detect_computer_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((PEPPER_IP, 9559))
        return s.getsockname()[0]
    finally:
        s.close()

# ── โหลดไฟล์ ────────────────────────────────────────────────────────────────
with open(_os.path.join(_HTML_DIR, SPEECH_FILE), "rb") as f:
    speech_data = f.read()
with open(_os.path.join(_HTML_DIR, "pepper_speak.html"), "r") as f:
    play_template = f.read().decode("utf-8")

audio_len = mp3_duration(speech_data)
print("speech.mp3: {} bytes, duration ~{:.1f}s".format(len(speech_data), audio_len))
if audio_len <= 0:
    print("Cannot parse MP3 duration — fallback to size estimate")
    audio_len = len(speech_data) / 8000.0

# TABLET_AUDIO=0 → แท็บเล็ตโชว์ข้อความอย่างเดียว เสียงออกลำโพงหุ่นผ่าน ALAudioPlayer
play_page = play_template.replace(u"{TEXT}", cgi.escape(TEST_TEXT)) \
                         .replace(u"{VOL}", str(VOLUME / 100.0)) \
                         .replace(u"{TABLET_AUDIO}", u"0")

audio_done_event = threading.Event()

# ── HTTP server (เฉพาะ endpoint ที่หน้า play ใช้) ─────────────────────────────
class TestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send(self, body, ctype="text/plain", code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra:
            for k, v in extra:
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except Exception:
            pass

    def do_GET(self):
        path  = self.path.split("?")[0]
        if path == "/play" or path == "/":
            self._send(play_page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/speech.mp3":
            data, total = speech_data, len(speech_data)
            start, end, partial = 0, total - 1, False
            rng = self.headers.get("Range")
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
                if m:
                    g1, g2 = m.group(1), m.group(2)
                    if g1 == "" and g2 != "":
                        start, end = max(0, total - int(g2)), total - 1
                    else:
                        start = int(g1) if g1 else 0
                        end   = int(g2) if g2 else total - 1
                    end = min(end, total - 1)
                    if 0 <= start <= end:
                        partial = True
            chunk = data[start:end + 1] if partial else data
            extra = [("Accept-Ranges", "bytes"), ("Cache-Control", "no-cache, no-store")]
            if partial:
                extra.append(("Content-Range", "bytes {}-{}/{}".format(start, end, total)))
            self._send(chunk, "audio/mpeg", 206 if partial else 200, extra)
        elif path == "/audio_done" or path == "/reset":
            audio_done_event.set()
            self._send(b"ok")
        elif path == "/log":
            try:
                qs = self.path.split("?", 1)[1]
                msg = urllib.unquote(qs.split("m=", 1)[1])
                print("Tablet audio: " + msg)
            except Exception:
                pass
            self._send(b"ok")
        else:
            self.send_error(404)

class ThreadingHTTPServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    daemon_threads      = True
    allow_reuse_address = True

# ── Main ────────────────────────────────────────────────────────────────────
computer_ip = detect_computer_ip()
print("Computer IP: {}".format(computer_ip))

print("Connecting to Pepper at {} ...".format(PEPPER_IP))
session = qi.Session()
session.connect("tcp://{}:9559".format(PEPPER_IP))
print("Connected!")

server = ThreadingHTTPServer(("0.0.0.0", STREAM_PORT), TestHandler)
t = threading.Thread(target=server.serve_forever)
t.daemon = True
t.start()
print("HTTP server on port {}".format(STREAM_PORT))

tablet = session.service("ALTabletService")
tablet.showWebview("http://{}:{}/play".format(computer_ip, STREAM_PORT))

# เล่นผ่านลำโพงหุ่น: playWebStream จะ block จนเล่นจบตามความยาวเสียงจริง
# ใช้ duration ที่ parse ได้ + margin เป็น safety timeout กันค้าง
ap = session.service("ALAudioPlayer")
url = "http://{}:{}/speech.mp3?_={}".format(computer_ip, STREAM_PORT, int(time.time() * 1000))
print("Playing on robot speaker... duration {:.1f}s (timeout {:.1f}s)".format(audio_len, audio_len + 10.0))
result = {"ok": False}

def _run():
    try:
        ap.playWebStream(url, VOLUME / 100.0, 0.0)
        result["ok"] = True
    except Exception as e:
        print("ALAudioPlayer error: " + str(e))

t0 = time.time()
th = threading.Thread(target=_run)
th.daemon = True
th.start()
th.join(audio_len + 10.0)
if th.is_alive():
    try:
        ap.stopAll()
    except Exception:
        pass
    th.join(2)
elapsed = time.time() - t0
if result["ok"]:
    print("Audio finished after {:.1f}s".format(elapsed))
else:
    print("Playback did not complete normally ({:.1f}s elapsed)".format(elapsed))

try:
    tablet.hideWebview()
except Exception:
    pass
server.shutdown()
print("Done. Exiting.")
