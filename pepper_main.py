# -*- coding: utf-8 -*-
# pepper_main.py  –  unified TH/EN  (Python 2 / qi framework)
# Language is selected via the tablet UI; stored in lang.txt.
# Run alongside listener_gemini_live.py on the PC side.

import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "SDK_pynaoqi", "pynaoqi", "lib"))

import qi
import threading
import BaseHTTPServer
import SocketServer
import re
import time
import random
import urlparse
import urllib
import cgi

# ── Gesture animations ────────────────────────────────────────────────────────
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
            except Exception as e:
                # Do not keep retrying a proxy bound to a dead qi session.
                # The main loop owns reconnection and will create a new gesture
                # thread on the next utterance.
                if _is_session_lost(e):
                    break
                time.sleep(0.5)
    except Exception as e:
        if _is_session_lost(e):
            print("Gesture stopped: Pepper session disconnected")
        else:
            print("Gesture error: " + str(e))

# ── Network / file settings ───────────────────────────────────────────────────
PEPPER_IP   = "10.1.68.244"
# PEPPER_IP   = "10.1.68.202"
COMPUTER_IP = "10.1.68.242"
STREAM_PORT = 8080
VOLUME      = 80    # 0-100

# Play speech through Pepper's own speakers via ALAudioPlayer (reliable).
# If it fails, we fall back to playing through the tablet webview.
USE_ROBOT_SPEAKER = True

COMMAND_FILE = "command.txt"
STATUS_FILE  = "status.txt"
SPEECH_FILE  = "speech.mp3"
QUERY_FILE   = "query.txt"
LANG_FILE    = "lang.txt"

# ── Globals ───────────────────────────────────────────────────────────────────
current_speech   = None
last_speech_text = u""
speech_seq       = 0     # increments per utterance; UI echoes it via /page_ready
ready_seq        = 0     # last seq the tablet UI confirmed it displayed
speech_lock      = threading.Lock()
audio_done_event = threading.Event()
page_ready_event = threading.Event()   # tablet UI displayed the current text
last_ui_poll     = time.time()         # last /status poll from the tablet UI
session          = None
tablet           = None
session_lock     = threading.RLock()

# ── MP3 duration (CBR estimate from first frame header) ──────────────────────
def _mp3_duration(data):
    try:
        pos = 0
        if data[:3] == "ID3":   # skip ID3v2 tag (syncsafe size)
            size = ((ord(data[6]) & 0x7F) << 21) | ((ord(data[7]) & 0x7F) << 14) | \
                   ((ord(data[8]) & 0x7F) << 7)  |  (ord(data[9]) & 0x7F)
            pos = 10 + size
        while pos < len(data) - 4:   # find MPEG frame sync
            if ord(data[pos]) == 0xFF and (ord(data[pos + 1]) & 0xE0) == 0xE0:
                break
            pos += 1
        else:
            return None
        b1, b2  = ord(data[pos + 1]), ord(data[pos + 2])
        version = (b1 >> 3) & 0x03           # 3 = MPEG1, else MPEG2/2.5
        if version == 3:
            table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
        else:
            table = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
        kbps = table[(b2 >> 4) & 0x0F]
        if kbps <= 0:
            return None
        return (len(data) - pos) * 8.0 / (kbps * 1000.0)
    except Exception:
        return None

# ── HTML loading ──────────────────────────────────────────────────────────────
_HTML_DIR = _os.path.dirname(_os.path.abspath(__file__))

def _load_html(filename):
    with open(_os.path.join(_HTML_DIR, filename), "r") as f:
        return f.read().decode("utf-8")

HTML_PAGE      = _load_html("pepper_ui.html")
_PLAY_TEMPLATE = _load_html("pepper_speak.html")

def make_play_page(text=u"", tablet_audio=False):
    safe_text = cgi.escape(text) if text else u""
    vol  = str(VOLUME / 100.0)
    page = _PLAY_TEMPLATE.replace(u"{TEXT}", safe_text).replace(u"{VOL}", vol)
    return page.replace(u"{TABLET_AUDIO}", u"1" if tablet_audio else u"0")

# ── Language helpers ──────────────────────────────────────────────────────────
def read_lang():
    try:
        with open(LANG_FILE, "r") as f:
            lang = f.read().strip()
        return lang if lang in ("th", "en") else "th"
    except Exception:
        return "th"

def write_lang(lang):
    with open(LANG_FILE, "w") as f:
        f.write(lang)

# ── Status / command file helpers ─────────────────────────────────────────────
def write_status(status):
    with open(STATUS_FILE, "w") as f:
        f.write(status)

def read_command():
    try:
        with open(COMMAND_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return content.decode("utf-8")
    except Exception:
        pass
    return None

def clear_command():
    with open(COMMAND_FILE, "w") as f:
        f.write("")

def read_status_file():
    try:
        with open(STATUS_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "ready"

# ── Load pre-generated MP3 from listener ─────────────────────────────────────
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

# ── Play MP3 through Pepper's speakers (ALAudioPlayer) ───────────────────────
def _play_on_robot(session, fallback):
    """Returns 'ok' (played fully), 'failed' (never started - safe to fall back),
    'disconnected' (qi session was lost), or 'timeout' (watchdog fired - audio
    was force-stopped, do NOT fall back)."""
    try:
        ap = session.service("ALAudioPlayer")
    except Exception as e:
        print("ALAudioPlayer unavailable: " + str(e))
        if _is_session_lost(e):
            return "disconnected"
        return "failed"
    url = "http://{}:{}/speech.mp3?_={}".format(COMPUTER_IP, STREAM_PORT, int(time.time() * 1000))
    result = {"ok": False, "error": None}

    def _run():
        try:
            ap.playWebStream(url, VOLUME / 100.0, 0.0)   # blocks until playback ends
            result["ok"] = True
        except Exception as e:
            result["error"] = e
            print("ALAudioPlayer error: " + str(e))

    th = threading.Thread(target=_run)
    th.daemon = True
    th.start()
    th.join(fallback)          # safety timeout: never hang forever
    if th.is_alive():
        try:
            ap.stopAll()
        except Exception:
            pass
        th.join(2)
        return "timeout"
    if result["error"] is not None and _is_session_lost(result["error"]):
        return "disconnected"
    return "ok" if result["ok"] else "failed"

# ── Speak (robot speakers; main UI page shows the text - no page navigation) ──
def _wait_text_displayed(my_seq, timeout=2.5):
    """Wait until the tablet UI confirms it displayed utterance my_seq."""
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        if not page_ready_event.wait(remaining):
            return False
        page_ready_event.clear()
        if ready_seq >= my_seq:
            return True

def pepper_say(session, text):
    global last_speech_text, speech_seq
    if not _session_is_connected(session):
        raise RuntimeError("Session not connected")
    last_speech_text = text          # set text BEFORE status flips to busy
    speech_seq += 1
    my_seq = speech_seq
    page_ready_event.clear()
    write_status("busy")
    print("Pepper: " + text.encode("utf-8"))
    if load_speech_from_file():
        try:
            motion = session.service("ALMotion")
            motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, 0.1], 0.3)
        except Exception as e:
            if _is_session_lost(e):
                raise
        stop_gesture = threading.Event()
        gesture_thread = threading.Thread(target=gesture_loop, args=(session, stop_gesture))
        gesture_thread.daemon = True
        gesture_thread.start()
        try:
            # Main UI polls /speak_info and shows the text itself - no page load.
            if not _wait_text_displayed(my_seq):
                if time.time() - last_ui_poll > 3:
                    # UI stopped polling = dead/white page: reload it now, retry once
                    print("Tablet UI silent - reloading webview before speaking")
                    try:
                        tablet = session.service("ALTabletService")
                        tablet.showWebview("http://{}:{}/?_={}".format(
                            COMPUTER_IP, STREAM_PORT, int(time.time())))
                    except Exception as e:
                        print("Webview reload failed: " + str(e))
                        if _is_session_lost(e):
                            raise
                    if not _wait_text_displayed(my_seq, timeout=4.0):
                        print("Warning: tablet did not confirm text display - playing anyway")
                else:
                    print("Warning: tablet did not confirm text display - playing anyway")
            with speech_lock:
                data = current_speech
            duration = _mp3_duration(data) if data else None
            if duration:
                fallback = duration + 8.0                       # real length + margin
            else:
                fallback = max(10.0, (len(data) if data else 0) / 3000.0 + 8.0)
            outcome = _play_on_robot(session, fallback) if USE_ROBOT_SPEAKER else "failed"
            if outcome == "disconnected":
                # A tablet fallback would use the same broken qi session.
                raise RuntimeError("Session not connected while playing speech")
            elif outcome == "failed":
                # Nothing playing - safe to let the tablet play it (navigates once).
                print("Robot speaker failed - falling back to tablet audio")
                try:
                    tablet = session.service("ALTabletService")
                    audio_done_event.clear()
                    play_url = u"http://{}:{}/play?_={}&a=1".format(
                        COMPUTER_IP, STREAM_PORT, int(time.time() * 1000))
                    tablet.showWebview(play_url)
                    audio_done_event.wait(timeout=fallback)
                    tablet.showWebview("http://{}:{}/".format(COMPUTER_IP, STREAM_PORT))
                except Exception as e:
                    print("Tablet fallback error: " + str(e))
                    if _is_session_lost(e):
                        raise
            elif outcome == "timeout":
                print("Robot playback watchdog fired at {:.1f}s (force-stopped)".format(fallback))
        except Exception as e:
            if _is_session_lost(e):
                raise
            print("Speak error: " + str(e))
        finally:
            stop_gesture.set()
    last_speech_text = u""   # clear so stale text never flashes on the next turn
    write_status("drain")

# ── HTTP Server ───────────────────────────────────────────────────────────────
class SpeechHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive: the tablet's media player streams over a persistent
    # connection; with HTTP/1.0 it must reconnect mid-stream and often stalls.
    # NOTE: every response MUST send Content-Length or the connection hangs.
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        path   = parsed.path

        # ── Main tablet UI ────────────────────────────────────────────────────
        if path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        # ── Language: read ────────────────────────────────────────────────────
        elif path == "/lang":
            lang = read_lang()
            body = lang.encode("utf-8") if isinstance(lang, unicode) else lang
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except Exception:
                pass

        # ── Language: set ─────────────────────────────────────────────────────
        elif path == "/set_lang":
            qs     = parsed.query
            params = urlparse.parse_qs(qs)
            lang   = params.get("lang", ["th"])[0]
            if lang in ("th", "en"):
                write_lang(lang)
                print("Language set to: " + lang)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        # ── Status ────────────────────────────────────────────────────────────
        elif path == "/status":
            global last_ui_poll
            last_ui_poll = time.time()   # heartbeat: proves the tablet UI is alive
            status = read_status_file()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(status)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(status)
            self.wfile.flush()

        # ── Play page (speaking view) ─────────────────────────────────────────
        elif path == "/play":
            qs     = urlparse.urlparse(self.path).query
            params = urlparse.parse_qs(qs)
            raw    = params.get("t", [b""])[0]
            # Text comes from memory (set by pepper_say); t= kept for compatibility.
            speech_text  = urllib.unquote(raw).decode("utf-8") if raw else last_speech_text
            tablet_audio = params.get("a", ["0"])[0] == "1"
            body = make_play_page(speech_text, tablet_audio).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        # ── Current utterance (seq + text) for the main UI ────────────────────
        elif path == "/speak_info":
            body = (u"{}\n{}".format(speech_seq, last_speech_text)).encode("utf-8")
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

        # ── Tablet UI confirmed it displayed utterance <seq> ──────────────────
        elif path == "/page_ready":
            params = urlparse.parse_qs(parsed.query)
            try:
                seq = int(params.get("seq", ["0"])[0])
            except ValueError:
                seq = 0
            global ready_seq
            if seq > ready_seq:
                ready_seq = seq
            page_ready_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        # ── Tablet audio diagnostics ──────────────────────────────────────────
        elif path == "/log":
            params = urlparse.parse_qs(parsed.query)
            msg = params.get("m", [""])[0]
            if msg:
                try:
                    print("Tablet audio: " + urllib.unquote(msg))
                except Exception:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        # ── Audio done signal ─────────────────────────────────────────────────
        elif path == "/audio_done":
            params = urlparse.parse_qs(parsed.query)
            reason = params.get("r", [None])[0]
            if reason:
                try:
                    print("Tablet audio issue: " + urllib.unquote(reason))
                except Exception:
                    print("Tablet audio issue (unprintable reason)")
            audio_done_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            try:
                self.wfile.write(b"ok")
            except Exception:
                pass

        # ── Serve speech MP3 ──────────────────────────────────────────────────
        elif path == "/speech.mp3":
            with speech_lock:
                data = current_speech
            if data is None:
                self.send_error(404)
                return
            total = len(data)
            # Android WebView's media player probes with a Range request and
            # will suspend (never play) if the server ignores it. Honour it.
            start, end, partial = 0, total - 1, False
            rng = self.headers.get("Range")
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
                if m:
                    g1, g2 = m.group(1), m.group(2)
                    if g1 == "" and g2 != "":            # suffix range: last N bytes
                        start, end = max(0, total - int(g2)), total - 1
                    else:
                        start = int(g1) if g1 else 0
                        end   = int(g2) if g2 else total - 1
                    end = min(end, total - 1)
                    if 0 <= start <= end:
                        partial = True
            chunk = data[start:end + 1] if partial else data
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, total))
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except Exception:
                pass

        # ── Reset ─────────────────────────────────────────────────────────────
        elif path == "/reset":
            audio_done_event.set()
            try:
                session.service("ALAudioPlayer").stopAll()   # stop robot-speaker playback too
            except Exception:
                pass
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

        # ── Query text (what user said) ───────────────────────────────────────
        elif path == "/query_text":
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

        # ── Last speech text ──────────────────────────────────────────────────
        elif path == "/last_text":
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


class ThreadingHTTPServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    daemon_threads      = True
    allow_reuse_address = True

def start_server():
    server = ThreadingHTTPServer(("0.0.0.0", STREAM_PORT), SpeechHandler)
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────────────
def _is_session_lost(error):
    """True when a NAOqi proxy belongs to a disconnected qi session."""
    try:
        return "session not connected" in str(error).lower()
    except Exception:
        return False

def _session_is_connected(candidate):
    try:
        return candidate is not None and candidate.isConnected()
    except Exception:
        return False

def connect_session():
    for _ in range(30):
        try:
            # A failed connection can leave a qi.Session unusable, so every
            # retry starts with a fresh session object.
            s = qi.Session()
            s.connect("tcp://{}:9559".format(PEPPER_IP))
            return s
        except Exception as _e:
            print("Waiting for Pepper... ({})".format(_e))
            time.sleep(5)
    print("Could not connect to Pepper after retries.")
    sys.exit(1)

def reconnect_session(stale_session):
    """Replace a dead shared session once, even if several threads notice it."""
    global session
    with session_lock:
        # Another thread may already have completed the reconnect while this
        # caller waited for the lock.
        if session is not stale_session and _session_is_connected(session):
            return session
        print("Session lost - reconnecting to Pepper...")
        session = connect_session()
        print("Reconnected!")
        return session

def restore_tablet_ui(active_session, hide_first=False):
    """Restore the main page after connecting without using stale proxies."""
    global tablet
    try:
        tablet = active_session.service("ALTabletService")
        if hide_first:
            tablet.hideWebview()
            time.sleep(1)
        tablet.showWebview("http://{}:{}/?_={}".format(
            COMPUTER_IP, STREAM_PORT, int(time.time())))
        print("Tablet UI ready - select TH / EN on screen")
        return True
    except Exception as e:
        print("Tablet UI restore failed: " + str(e))
        return False

session = connect_session()
print("Connected to Pepper!")

# Initialise language file
if not _os.path.exists(LANG_FILE):
    write_lang("th")

t = threading.Thread(target=start_server)
t.daemon = True
t.start()
print("HTTP server started on port {}".format(STREAM_PORT))

write_status("ready")
clear_command()

restore_tablet_ui(session, hide_first=True)
print("Waiting for commands from listener_gemini_live.py ...")

_last_ui_reload = 0
while True:
    cmd = read_command()
    if cmd:
        clear_command()
        try:
            pepper_say(session, cmd)
        except Exception as _e:
            if _is_session_lost(_e):
                # The current response did not complete.  Unblock the listener
                # before waiting for a potentially slow robot reconnect.
                last_speech_text = u""
                write_status("drain")
                session = reconnect_session(session)
                restore_tablet_ui(session)
            else:
                print("Command failed: " + str(_e))

    # ── Tablet watchdog: UI polls /status every 0.3s; silence = dead/white page ──
    _now = time.time()
    if _now - last_ui_poll > 6 and _now - _last_ui_reload > 10:
        _last_ui_reload = _now
        print("Tablet UI not responding - reloading webview")
        try:
            tablet = session.service("ALTabletService")
            tablet.showWebview("http://{}:{}/?_={}".format(COMPUTER_IP, STREAM_PORT, int(_now)))
        except Exception as _e:
            print("Webview reload failed: " + str(_e))
            if _is_session_lost(_e):
                session = reconnect_session(session)
                restore_tablet_ui(session)
    time.sleep(0.3)
