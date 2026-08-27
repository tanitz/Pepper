# -*- coding: utf-8 -*-
# pepper_main.py  –  unified TH/EN  (Python 2 / qi framework)
# Language is selected via the tablet UI; stored in lang.txt.
# Run alongside listener_gemini_live.py on the PC side.

import sys, os as _os

# Python 2 writes UTF-8 bytes below.  Make the Windows console interpret those
# bytes as UTF-8 instead of the default OEM code page (e.g. CP437).
if sys.platform.startswith("win"):
    try:
        import ctypes as _ctypes
        _ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        _ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from naoqi_path import add_sdk_to_path
add_sdk_to_path()

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
import struct
import json

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
COMPUTER_IP = "10.1.68.238"
# COMPUTER_IP = "10.1.68.242"
STREAM_PORT = 8081
VOLUME      = 100    # 0-100

# Tablet camera preview.  NAOqi constants: top camera=0, QVGA=1, RGB=11.
# QVGA keeps the HTTP preview responsive on Pepper's older Android WebView.
CAMERA_INDEX      = 0
CAMERA_RESOLUTION = 1
CAMERA_COLORSPACE = 11
# Ask NAOqi for fresh frames often enough that the tablet is not showing an
# old 5 FPS camera buffer.  The browser still keeps only one request in flight.
CAMERA_FPS        = 15
FACE_PERIOD_MS    = 200
FACE_HOLD_SECS    = 0.8
FACE_TRACKING_ENABLED = True
FACE_TRACKING_MODE = "Head"  # Follow with the head; "Move" can move the base.
FACE_TARGET_WIDTH = 0.10      # Approximate adult face width in metres.
FACE_CAPTURE_DIR  = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "face_captures"
)
FACE_GREETING_EVENT_FILE = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "face_greeting_event.json"
)

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
current_speech_duration = 0.0  # 0=loading, negative=unknown, positive=seconds
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
camera_lock      = threading.Lock()
camera_cache_lock = threading.Lock()
camera_proxy     = None
camera_client    = None
camera_session   = None
camera_last_bmp  = None
camera_last_bmp_at = 0.0
face_lock        = threading.Lock()
face_boxes       = []
face_known_names = []
face_capture_lock = threading.Lock()
pending_face_capture = None
face_capture_seq = 0

# ── Pepper built-in face detection / recognition ────────────────────────────
def _is_unknown_face_name(name):
    """Accept common NAOqi spellings for an unrecognized face."""
    try:
        if isinstance(name, str):
            name = name.decode("utf-8", "replace")
        normalized = name.strip().lower().replace(u" ", u"").replace(u"_", u"")
    except Exception:
        return True
    return normalized in (
        u"", u"unknown", u"unknow", u"unrecognized", u"unrecognised",
        u"none", u"null", u"?",
    )


def _face_label(extra_info):
    """Return ALFaceDetection's recognized label, or Unknown."""
    try:
        label = extra_info[2]
        if isinstance(label, str):
            label = label.decode("utf-8", "replace")
        elif not isinstance(label, unicode):
            label = unicode(label)
        label = label.strip()
        return u"Unknown" if _is_unknown_face_name(label) else label
    except Exception:
        return u"Unknown"


def _parse_face_event(data, video_service):
    """Convert FaceDetected angular boxes to normalized QVGA image boxes."""
    if not data or len(data) < 2 or not isinstance(data[1], (list, tuple)):
        return []
    result = []
    for face_info in data[1]:
        try:
            if not isinstance(face_info, (list, tuple)) or len(face_info) < 2:
                continue
            shape_info, extra_info = face_info[0], face_info[1]
            # NAOqi FaceDetected ShapeInfo is:
            # [reserved, alpha, beta, sizeX, sizeY]
            if len(shape_info) < 5:
                continue
            angular = [float(shape_info[i]) for i in xrange(1, 5)]
            image_info = video_service.getImageInfoFromAngularInfoWithResolution(
                CAMERA_INDEX, angular, CAMERA_RESOLUTION
            )
            if not image_info or len(image_info) < 4:
                continue
            center_x, center_y, width, height = [float(v) for v in image_info[:4]]
            # getImageInfo... returns QVGA pixels: center X/Y and width/height.
            left = max(0.0, center_x - width / 2.0)
            top = max(0.0, center_y - height / 2.0)
            right = min(320.0, center_x + width / 2.0)
            bottom = min(240.0, center_y + height / 2.0)
            if right <= left or bottom <= top:
                continue
            try:
                confidence = float(extra_info[1])
            except Exception:
                confidence = 0.0
            result.append({
                "x": round(left / 320.0, 4),
                "y": round(top / 240.0, 4),
                "w": round((right - left) / 320.0, 4),
                "h": round((bottom - top) / 240.0, 4),
                "name": _face_label(extra_info),
                "confidence": round(confidence, 3),
            })
        except Exception:
            continue
    return result


def _set_face_state(faces=None, known_names=None):
    global face_boxes, face_known_names
    with face_lock:
        if faces is not None:
            face_boxes = faces
        if known_names is not None:
            face_known_names = known_names


def _publish_face_greeting_event(name):
    """Queue one recognized name for the Python 3 listener/TTS process."""
    if _is_unknown_face_name(name):
        return False
    if _os.path.exists(FACE_GREETING_EVENT_FILE):
        return False
    temp_path = FACE_GREETING_EVENT_FILE + ".tmp"
    payload = json.dumps({
        "name": name,
        "seen_at": time.time(),
    }, ensure_ascii=True, separators=(",", ":"))
    try:
        with open(temp_path, "wb") as event_file:
            event_file.write(payload)
        if _os.path.exists(FACE_GREETING_EVENT_FILE):
            _os.remove(temp_path)
            return False
        _os.rename(temp_path, FACE_GREETING_EVENT_FILE)
        return True
    except Exception as e:
        try:
            if _os.path.exists(temp_path):
                _os.remove(temp_path)
        except Exception:
            pass
        print("Face greeting event error: " + str(e))
        return False


def face_detection_loop():
    """Publish face boxes and keep Pepper's head tracking the visible face."""
    subscriber_name = "pepper_tablet_faces_{}".format(_os.getpid())
    active_session = None
    detector = None
    memory = None
    video = None
    tracker = None
    subscribed = False
    tracking = False
    last_seen = 0.0
    last_error = None
    last_greeting_event = {}

    while True:
        try:
            shared_session = session
            if not _session_is_connected(shared_session):
                _set_face_state(faces=[])
                time.sleep(1.0)
                continue

            if shared_session is not active_session:
                if detector is not None and subscribed:
                    try:
                        detector.unsubscribe(subscriber_name)
                    except Exception:
                        pass
                if tracker is not None and tracking:
                    try:
                        tracker.stopTracker()
                        tracker.unregisterTarget("Face")
                    except Exception:
                        pass
                detector = shared_session.service("ALFaceDetection")
                memory = shared_session.service("ALMemory")
                video = shared_session.service("ALVideoDevice")
                detector.setActiveCamera(CAMERA_INDEX)
                detector.setResolution(CAMERA_RESOLUTION)
                detector.setRecognitionEnabled(True)
                detector.subscribe(subscriber_name, FACE_PERIOD_MS, 0.0)
                subscribed = True
                if FACE_TRACKING_ENABLED:
                    # Autonomous Life normally runs ALBasicAwareness in
                    # BodyRotation mode.  It competes with ALTracker for the
                    # head joints, so pause it while this app owns tracking.
                    awareness = shared_session.service("ALBasicAwareness")
                    if awareness.isEnabled() and not awareness.isAwarenessPaused():
                        awareness.pauseAwareness()
                    motion = shared_session.service("ALMotion")
                    motion.setStiffnesses("Head", 1.0)
                    tracker = shared_session.service("ALTracker")
                    tracker.registerTarget("Face", FACE_TARGET_WIDTH)
                    tracker.setMode(FACE_TRACKING_MODE)
                    tracker.track("Face")
                    tracking = True
                active_session = shared_session
                known_names = detector.getLearnedFacesList()
                _set_face_state(faces=[], known_names=list(known_names))
                print("Face detection ready - {} learned faces".format(len(known_names)))
                if tracking:
                    print("Face tracking ready - mode {}".format(FACE_TRACKING_MODE))
                last_error = None

            faces = _parse_face_event(memory.getData("FaceDetected"), video)
            now = time.time()
            if faces:
                last_seen = now
                _set_face_state(faces=faces)
                for visible_face in faces:
                    name = visible_face.get("name", u"Unknown").strip()
                    if _is_unknown_face_name(name):
                        continue
                    # Re-offer a visible name occasionally.  The listener owns
                    # the configurable, persistent per-person cooldown.
                    if now - last_greeting_event.get(name, 0.0) < 2.0:
                        continue
                    if _publish_face_greeting_event(name):
                        last_greeting_event[name] = now
                        break
            elif now - last_seen > FACE_HOLD_SECS:
                _set_face_state(faces=[])
            time.sleep(0.15)
        except Exception as e:
            _set_face_state(faces=[])
            message = str(e)
            if message != last_error:
                print("Face detection error: " + message)
                last_error = message
            if detector is not None and subscribed:
                try:
                    detector.unsubscribe(subscriber_name)
                except Exception:
                    pass
            if tracker is not None and tracking:
                try:
                    tracker.stopTracker()
                    tracker.unregisterTarget("Face")
                except Exception:
                    pass
            active_session = None
            detector = None
            memory = None
            video = None
            tracker = None
            subscribed = False
            tracking = False
            time.sleep(2.0)


def get_face_info_json():
    with face_lock:
        payload = {
            "faces": list(face_boxes),
            "known_count": len(face_known_names),
        }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def create_face_capture():
    """Freeze one camera frame for the enrollment preview."""
    global pending_face_capture, face_capture_seq
    # Prefer the frame already shown on the tablet.  Starting a second camera
    # request while the live preview is active can stall ALVideoDevice.
    image_data = get_recent_camera_bmp(1.0)
    if image_data is None:
        image_data = get_camera_bmp()
    with face_capture_lock:
        now_ms = int(time.time() * 1000)
        face_capture_seq += 1
        capture_id = now_ms * 1000 + (face_capture_seq % 1000)
        pending_face_capture = {
            "id": capture_id,
            "created": time.time(),
            "image": image_data,
        }
    return capture_id


def get_face_capture(capture_id):
    with face_capture_lock:
        capture = pending_face_capture
        if capture is None or capture.get("id") != capture_id:
            return None
        return capture.get("image")


def _normalise_face_name(raw_name):
    try:
        name = raw_name.decode("utf-8") if isinstance(raw_name, str) else unicode(raw_name)
    except Exception:
        return None
    name = u" ".join(name.strip().split())
    if not name or len(name) > 50:
        return None
    if any(ord(ch) < 32 for ch in name):
        return None
    return name


def _store_face_capture(capture_id, name, image_data):
    if not _os.path.isdir(FACE_CAPTURE_DIR):
        try:
            _os.makedirs(FACE_CAPTURE_DIR)
        except OSError:
            if not _os.path.isdir(FACE_CAPTURE_DIR):
                raise
    image_path = _os.path.join(FACE_CAPTURE_DIR, "{}.bmp".format(capture_id))
    metadata_path = _os.path.join(FACE_CAPTURE_DIR, "{}.json".format(capture_id))
    with open(image_path, "wb") as image_file:
        image_file.write(image_data)
    metadata = json.dumps({
        "name": name,
        "capture_id": capture_id,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2).encode("utf-8")
    with open(metadata_path, "wb") as metadata_file:
        metadata_file.write(metadata)
    return image_path


def learn_captured_face(capture_id, raw_name):
    """Learn the currently visible face and retain its frozen reference image."""
    name = _normalise_face_name(raw_name)
    if name is None:
        return False, "invalid_name", "Enter a name between 1 and 50 characters."
    with face_capture_lock:
        capture = pending_face_capture
        if capture is None or capture.get("id") != capture_id:
            return False, "capture_expired", "The captured photo is no longer available."
        if time.time() - capture.get("created", 0) > 300:
            return False, "capture_expired", "The captured photo has expired. Retake it."
        image_data = capture.get("image")

    active_session = session
    if not _session_is_connected(active_session):
        return False, "pepper_offline", "Pepper is not connected."
    detector = active_session.service("ALFaceDetection")
    learned_names = list(detector.getLearnedFacesList())
    comparable_name = name.encode("utf-8") if isinstance(name, unicode) else name
    if name in learned_names or comparable_name in learned_names:
        return False, "name_exists", "This name is already registered."

    try:
        learned = detector.learnFace(comparable_name)
    finally:
        # learnFace temporarily owns the camera pipeline on some Pepper/NAOqi
        # versions.  Recreate our preview subscription instead of reusing the
        # potentially stale client after enrollment.
        reset_camera_subscription()
    if not learned:
        return False, "no_face", "No clear face was found. Keep facing Pepper and retake."

    learned_names = list(detector.getLearnedFacesList())
    _set_face_state(known_names=learned_names)
    saved_path = _store_face_capture(capture_id, name, image_data)
    print("Learned face: {} (reference saved: {})".format(
        name.encode("utf-8"), saved_path
    ))
    return True, "ok", "Face saved successfully."

# ── Pepper camera preview ────────────────────────────────────────────────────
def _close_camera_locked():
    """Release the current ALVideoDevice subscription. camera_lock is held."""
    global camera_proxy, camera_client, camera_session
    if camera_proxy is not None and camera_client is not None:
        try:
            camera_proxy.unsubscribe(camera_client)
        except Exception:
            pass
    camera_proxy = None
    camera_client = None
    camera_session = None


def reset_camera_subscription():
    """Force the next preview request to create a fresh video client."""
    with camera_lock:
        _close_camera_locked()


def get_recent_camera_bmp(max_age):
    """Return the most recent encoded preview without touching ALVideoDevice."""
    with camera_cache_lock:
        if camera_last_bmp is None or time.time() - camera_last_bmp_at > max_age:
            return None
        return camera_last_bmp


def _rgb_to_bmp(width, height, rgb_data):
    """Encode packed RGB bytes as a dependency-free 24-bit BMP."""
    rgb = bytearray(rgb_data)
    expected = width * height * 3
    if width <= 0 or height <= 0 or len(rgb) < expected:
        raise ValueError("incomplete camera frame")
    if len(rgb) > expected:
        del rgb[expected:]

    # BMP stores BGR rows from bottom to top, padded to a four-byte boundary.
    for i in xrange(0, expected, 3):
        rgb[i], rgb[i + 2] = rgb[i + 2], rgb[i]
    row_size = width * 3
    padding = b"\x00" * ((4 - (row_size % 4)) % 4)
    rows = []
    for y in xrange(height - 1, -1, -1):
        start = y * row_size
        rows.append(str(rgb[start:start + row_size]) + padding)
    pixels = b"".join(rows)
    header_size = 14 + 40
    file_header = struct.pack("<2sIHHI", b"BM", header_size + len(pixels), 0, 0, header_size)
    info_header = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels),
        2835, 2835, 0, 0
    )
    return file_header + info_header + pixels


def get_camera_bmp():
    """Capture one top-camera frame and return it as BMP bytes."""
    global camera_proxy, camera_client, camera_session
    global camera_last_bmp, camera_last_bmp_at
    with camera_lock:
        if session is None:
            raise RuntimeError("Pepper session is not connected")
        if camera_session is not session:
            _close_camera_locked()
        if camera_proxy is None or camera_client is None:
            camera_proxy = session.service("ALVideoDevice")
            camera_client = camera_proxy.subscribeCamera(
                "pepper_tablet_{}".format(_os.getpid()),
                CAMERA_INDEX,
                CAMERA_RESOLUTION,
                CAMERA_COLORSPACE,
                CAMERA_FPS,
            )
            camera_session = session
            print("Pepper top camera preview started")

        active_proxy = camera_proxy
        active_client = camera_client
        try:
            frame = None
            try:
                frame = active_proxy.getImageRemote(active_client)
                if not frame or len(frame) < 7:
                    raise RuntimeError("camera returned no frame")
                width, height = int(frame[0]), int(frame[1])
                # Copy before releaseImage returns NAOqi's shared buffer.
                rgb_data = bytearray(frame[6])
                image_data = _rgb_to_bmp(width, height, rgb_data)
                with camera_cache_lock:
                    camera_last_bmp = image_data
                    camera_last_bmp_at = time.time()
                return image_data
            finally:
                if frame is not None:
                    try:
                        active_proxy.releaseImage(active_client)
                    except Exception:
                        pass
        except Exception:
            _close_camera_locked()
            raise

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
        duration = _mp3_duration(data)
        with speech_lock:
            global current_speech, current_speech_duration
            current_speech = data
            current_speech_duration = duration if duration else -1.0
        return True
    except Exception as e:
        with speech_lock:
            current_speech_duration = -1.0
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
    global last_speech_text, speech_seq, current_speech_duration
    if not _session_is_connected(session):
        raise RuntimeError("Session not connected")
    last_speech_text = text          # set text BEFORE status flips to busy
    speech_seq += 1
    my_seq = speech_seq
    with speech_lock:
        current_speech_duration = 0.0
    page_ready_event.clear()
    write_status("busy")
    print("Pepper: " + text.encode("utf-8"))
    if load_speech_from_file():
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

        # ── Current frame from Pepper's top camera ────────────────────────────
        elif path == "/camera.bmp":
            try:
                body = get_camera_bmp()
            except Exception as e:
                print("Camera preview error: " + str(e))
                body = b"camera unavailable"
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, no-store")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/bmp")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except Exception:
                pass

        # ── Face boxes from Pepper's built-in ALFaceDetection ────────────────
        elif path == "/face_info":
            body = get_face_info_json()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except Exception:
                pass

        # ── Freeze a frame for face enrollment ───────────────────────────────
        elif path == "/capture_face":
            try:
                capture_id = create_face_capture()
                payload = {"ok": True, "capture_id": capture_id}
                status_code = 200
            except Exception as e:
                payload = {"ok": False, "error": "capture_failed", "message": str(e)}
                status_code = 500
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        # ── Frozen enrollment preview ────────────────────────────────────────
        elif path == "/face_capture.bmp":
            params = urlparse.parse_qs(parsed.query)
            try:
                capture_id = int(params.get("id", ["0"])[0])
            except (TypeError, ValueError):
                capture_id = 0
            body = get_face_capture(capture_id)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/bmp")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except Exception:
                pass

        # ── Add the currently visible face to Pepper's recognition database ─
        elif path == "/learn_face":
            params = urlparse.parse_qs(parsed.query)
            try:
                capture_id = int(params.get("id", ["0"])[0])
            except (TypeError, ValueError):
                capture_id = 0
            raw_name = params.get("name", [""])[0]
            try:
                ok, error_code, message = learn_captured_face(capture_id, raw_name)
                status_code = 200 if ok else 400
                payload = {
                    "ok": ok,
                    "error": None if ok else error_code,
                    "message": message,
                    "known_count": len(face_known_names),
                }
            except Exception as e:
                status_code = 500
                payload = {
                    "ok": False,
                    "error": "learn_failed",
                    "message": str(e),
                }
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

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
            with speech_lock:
                duration = current_speech_duration
            body = (u"{}\n{:.3f}\n{}".format(
                speech_seq, duration, last_speech_text
            )).encode("utf-8")
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

face_thread = threading.Thread(target=face_detection_loop)
face_thread.daemon = True
face_thread.start()

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
