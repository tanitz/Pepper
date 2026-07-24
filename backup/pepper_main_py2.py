# -*- coding: utf-8 -*-
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "SDK_pynaoqi", "pynaoqi", "lib"))

import qi
import threading
import BaseHTTPServer
import time
import random
import urlparse
import urllib
import cgi

SPEAK_GESTURES = [
    "animations/Stand/BodyTalk/Speaking/BodyTalk_1",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_2",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_3",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_4",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_5",
    "animations/Stand/Gestures/Explain_1",
    "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Enthusiastic_1",
    "animations/Stand/Gestures/Enthusiastic_4",
]

def gesture_loop(session, stop_event):
    try:
        player = session.service("ALAnimationPlayer")
        while not stop_event.is_set():
            anim = random.choice(SPEAK_GESTURES)
            try:
                player.run(anim)
            except Exception:
                time.sleep(0.5)
    except Exception as e:
        print("Gesture error: " + str(e))

PEPPER_IP   = "172.101.99.97"
COMPUTER_IP = "10.1.8.88"
STREAM_PORT = 8080
VOLUME      = 80    # ระดับเสียง 0-100

COMMAND_FILE = "command.txt"
STATUS_FILE  = "status.txt"
SPEECH_FILE  = "speech.mp3"
QUERY_FILE   = "query.txt"

current_speech   = None
last_speech_text = u""
speech_lock      = threading.Lock()
audio_done_event = threading.Event()

_HTML_DIR = _os.path.dirname(_os.path.abspath(__file__))

def _load_html(filename):
    with open(_os.path.join(_HTML_DIR, filename), "r") as f:
        return f.read().decode("utf-8")

HTML_PAGE      = _load_html("index.html")
_PLAY_TEMPLATE = _load_html("play.html")

def make_play_page(text=u""):
    safe_text = cgi.escape(text) if text else u""
    vol = str(VOLUME / 100.0)
    return _PLAY_TEMPLATE.replace(u"{TEXT}", safe_text).replace(u"{VOL}", vol)


# ---- status / command file ----
def write_status(status):
    with open(STATUS_FILE, "w") as f:
        f.write(status)

def read_command():
    try:
        with open(COMMAND_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return content.decode("utf-8")
    except:
        pass
    return None

def clear_command():
    with open(COMMAND_FILE, "w") as f:
        f.write("")

def read_status_file():
    try:
        with open(STATUS_FILE, "r") as f:
            return f.read().strip()
    except:
        return "ready"


# ---- Load pre-generated MP3 from listener_py3 ----
def load_speech_from_file():
    try:
        with open(SPEECH_FILE, "rb") as f:
            data = f.read()
        with speech_lock:
            global current_speech
            current_speech = data
        return True
    except Exception as e:
        print("Load MP3 error: " + str(e))
        return False

def pepper_say_thai(session, text):
    global last_speech_text
    last_speech_text = text
    write_status("busy")
    print("Pepper: " + text.encode("utf-8"))
    if load_speech_from_file():
        try:
            motion = session.service("ALMotion")
            motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, 0.1], 0.3)
        except Exception:
            pass
        stop_gesture = threading.Event()
        gesture_thread = threading.Thread(target=gesture_loop, args=(session, stop_gesture))
        gesture_thread.daemon = True
        gesture_thread.start()
        try:
            tablet = session.service("ALTabletService")
            audio_done_event.clear()
            play_url = u"http://{}:{}/play?t={}".format(
                COMPUTER_IP, STREAM_PORT,
                urllib.quote(text.encode("utf-8"))
            )
            tablet.showWebview(play_url)
            with speech_lock:
                data_len = len(current_speech) if current_speech else 0
            fallback = max(8.0, data_len / 8000.0 + 5.0)
            audio_done_event.wait(timeout=fallback)
            tablet.showWebview("http://{}:{}/".format(COMPUTER_IP, STREAM_PORT))
        except Exception as e:
            print("Tablet error: " + str(e))
        finally:
            stop_gesture.set()
    write_status("drain")  # listener จะ drain buffer แล้วค่อย set "ready" เอง


# ---- HTTP Server ----
class SpeechHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        elif self.path == "/status":
            status = read_status_file()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(status)
            self.wfile.flush()

        elif self.path.startswith("/play"):
            qs = urlparse.urlparse(self.path).query
            params = urlparse.parse_qs(qs)
            raw = params.get("t", [b""])[0]
            speech_text = urllib.unquote(raw).decode("utf-8") if raw else u""
            body = make_play_page(speech_text).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        elif self.path == "/audio_done":
            audio_done_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        elif self.path == "/speech.mp3":
            with speech_lock:
                data = current_speech
            if data is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except Exception:
                pass

        elif self.path == "/reset":
            audio_done_event.set()
            write_status("ready")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        elif self.path == "/query_text":
            try:
                with open(QUERY_FILE, "r") as f:
                    body = f.read().strip().decode("utf-8").encode("utf-8")
            except Exception:
                body = b""
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        elif self.path == "/last_text":
            body = last_speech_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        else:
            self.send_error(404)

    def handle(self):
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
        except Exception:
            pass

    def finish(self):
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.finish(self)
        except Exception:
            pass


def start_server():
    server = BaseHTTPServer.HTTPServer(("0.0.0.0", STREAM_PORT), SpeechHandler)
    server.serve_forever()


# ---- Main ----
session = qi.Session()
session.connect("tcp://{}:9559".format(PEPPER_IP))
print("เชื่อมต่อสำเร็จ!")

t = threading.Thread(target=start_server)
t.daemon = True
t.start()
print("HTTP server เริ่มแล้ว!")

write_status("ready")
clear_command()

# เปิดหน้า UI บน tablet
tablet = session.service("ALTabletService")
tablet.hideWebview()
time.sleep(1)
tablet.showWebview("http://{}:{}/".format(COMPUTER_IP, STREAM_PORT))
print("เปิด tablet แล้ว!")

print("รอคำสั่งจาก listener_gemini_live.py...")

while True:
    cmd = read_command()
    if cmd:
        clear_command()
        pepper_say_thai(session, cmd)
    time.sleep(0.3)