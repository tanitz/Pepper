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

current_speech   = None
last_speech_text = u""
speech_lock      = threading.Lock()
audio_done_event = threading.Event()

def make_play_page(text=u""):
    safe_text = cgi.escape(text) if text else u""
    vol = VOLUME / 100.0
    return u"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background:#000;
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:center;
    height:100vh;
    font-family:sans-serif;
    padding:20px;
}}
.waves {{ display:flex; align-items:center; gap:10px; height:120px; }}
.bar {{
    width:16px;
    background:linear-gradient(to top,#ff4e1a,#ffb347);
    border-radius:8px;
    animation:wave 0.7s ease-in-out infinite;
}}
.bar:nth-child(1){{animation-delay:0.00s}}
.bar:nth-child(2){{animation-delay:0.10s}}
.bar:nth-child(3){{animation-delay:0.20s}}
.bar:nth-child(4){{animation-delay:0.30s}}
.bar:nth-child(5){{animation-delay:0.20s}}
.bar:nth-child(6){{animation-delay:0.10s}}
.bar:nth-child(7){{animation-delay:0.00s}}
@keyframes wave {{
    0%,100%{{height:18px}}
    50%{{height:100px}}
}}
.label {{
    color:#ff8c42;
    font-size:36px;
    font-weight:bold;
    margin-top:24px;
    letter-spacing:3px;
}}
.speech-text {{
    color:#fff;
    font-size:30px;
    text-align:center;
    line-height:1.6;
    margin-top:28px;
    max-width:90%;
    padding:16px 24px;
    border:2px solid #ff4e1a44;
    border-radius:16px;
    background:#ffffff0f;
}}
</style>
</head>
<body>
<div class="waves">
  <div class="bar"></div>
  <div class="bar"></div>
  <div class="bar"></div>
  <div class="bar"></div>
  <div class="bar"></div>
  <div class="bar"></div>
  <div class="bar"></div>
</div>
<div class="label">&#x1F50A;&nbsp;Speaking...</div>
<div class="speech-text">{text}</div>
<audio id="a" src="/speech.mp3" autoplay></audio>
<script>
function done(){{var x=new XMLHttpRequest();x.open('GET','/audio_done',true);x.send();}}
var a=document.getElementById('a');
a.volume={vol};
a.addEventListener('ended',done,false);
try{{a.play();}}catch(e){{}}
</script>
</body>
</html>""".format(text=safe_text, vol=vol)

HTML_PAGE = u"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background:#000;
    display:flex;
    justify-content:center;
    align-items:center;
    height:100vh;
    font-family:sans-serif;
  }
  .container {
    display:flex;
    flex-direction:column;
    align-items:center;
    gap:40px;
  }
  .circle {
    width:280px;
    height:280px;
    border-radius:50%;
    display:flex;
    justify-content:center;
    align-items:center;
    transition: background 0.5s, box-shadow 0.5s;
  }
  .circle.listening {
    background: radial-gradient(circle, #1a6fff, #003baa);
    box-shadow: 0 0 60px #1a6fff, 0 0 120px #1a6fff55;
    animation: pulse 2s infinite;
  }
  .circle.speaking {
    background: radial-gradient(circle, #ff4e1a, #aa1a00);
    box-shadow: 0 0 60px #ff4e1a, 0 0 120px #ff4e1a55;
    animation: pulse 0.6s infinite;
  }
  @keyframes pulse {
    0%   { transform: scale(1);    }
    50%  { transform: scale(1.08); }
    100% { transform: scale(1);    }
  }
  .icon {
    font-size: 100px;
  }
  .label {
    color: #fff;
    font-size: 48px;
    font-weight: bold;
    letter-spacing: 4px;
  }
  .label.listening { color: #6af; }
  .label.speaking  { color: #f84; }
  .last-text {
    color: #ccc;
    font-size: 26px;
    text-align: center;
    max-width: 85%;
    line-height: 1.5;
    min-height: 40px;
  }
  .reset-btn {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #333;
    color: #fff;
    border: 2px solid #555;
    border-radius: 12px;
    font-size: 28px;
    padding: 10px 28px;
    cursor: pointer;
  }
  .reset-btn:active { background: #c00; border-color: #f44; }
</style>
</head>
<body>
<div class="container">
  <div class="circle listening" id="circle">
    <span class="icon" id="icon">&#x1F3A4;</span>
  </div>
  <div class="label listening" id="label">Listening...</div>
  <div class="last-text" id="last-text"></div>
</div>
<button class="reset-btn" onclick="doReset()">&#x21BA; Reset</button>
<script>
function doReset() {
    var x = new XMLHttpRequest();
    x.open('GET', '/reset', true);
    x.send();
}
function checkStatus() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/status', true);
    xhr.onreadystatechange = function() {
        if (xhr.readyState == 4 && xhr.status == 200) {
            var status = xhr.responseText.trim();
            var circle = document.getElementById('circle');
            var icon   = document.getElementById('icon');
            var label  = document.getElementById('label');
            if (status === 'busy' || status === 'drain') {
                circle.className = 'circle speaking';
                icon.innerHTML   = '&#x1F50A;';
                label.className  = 'label speaking';
                label.innerHTML  = 'Speaking...';
            } else {
                circle.className = 'circle listening';
                icon.innerHTML   = '&#x1F3A4;';
                label.className  = 'label listening';
                label.innerHTML  = 'Listening...';
                fetchLastText();
            }
        }
    };
    xhr.send();
}
function fetchLastText() {
    var x = new XMLHttpRequest();
    x.open('GET', '/last_text', true);
    x.onreadystatechange = function() {
        if (x.readyState == 4 && x.status == 200) {
            document.getElementById('last-text').innerHTML = x.responseText;
        }
    };
    x.send();
}
setInterval(checkStatus, 500);
</script>
</body>
</html>"""


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

# เปิดหน้า UI บน tablet
tablet = session.service("ALTabletService")
tablet.hideWebview()
time.sleep(1)
tablet.showWebview("http://{}:{}/".format(COMPUTER_IP, STREAM_PORT))
print("เปิด tablet แล้ว!")

write_status("ready")
clear_command()
last_command = u""

print("รอคำสั่งจาก listener_gemini_live.py...")

while True:
    cmd = read_command()
    if cmd and cmd != last_command:
        last_command = cmd
        clear_command()
        pepper_say_thai(session, cmd)
    time.sleep(0.3)