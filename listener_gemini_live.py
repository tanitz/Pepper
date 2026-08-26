# -*- coding: utf-8 -*-
# listener_gemini_live.py  –  unified TH / EN
# STT: Whisper CT2  |  AI: Google Gemini  |  TTS: edge-tts
#
# Language is selected on Pepper's tablet UI.
# pepper_main.py writes the choice to lang.txt; this script reacts immediately.
# Config hot-reload: edit config/config.json and save → takes effect on the next question.

# ── 1. CUDA library preload (must be before other imports) ────────────────────
# Windows: nvidia-*-cu12 ships DLLs under nvidia/<pkg>/bin
# Linux:   same packages ship .so under nvidia/<pkg>/lib
import os, sys, ctypes, site as _site

_SITES = list(_site.getsitepackages()) if hasattr(_site, "getsitepackages") else []
_user_site = _site.getusersitepackages()
if isinstance(_user_site, str) and _user_site not in _SITES:
    _SITES.append(_user_site)

_IS_WIN = sys.platform == "win32"
_LIB_SUBDIR = "bin" if _IS_WIN else "lib"
_DLL_DIR_HANDLES = []
_CUDA_LIBS = (
    ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"]
    if _IS_WIN else
    ["libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9", "libcudnn_ops.so.9"]
)

for _SITE in _SITES:
    for _pkg in ("cublas", "cuda_nvrtc", "cudnn"):
        _d = os.path.join(_SITE, "nvidia", _pkg, _LIB_SUBDIR)
        if not os.path.isdir(_d):
            continue
        if _IS_WIN:
            _DLL_DIR_HANDLES.append(os.add_dll_directory(_d))
            os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")
        else:
            os.environ["LD_LIBRARY_PATH"] = _d + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")

for _lib in _CUDA_LIBS:
    for _SITE in _SITES:
        for _pkg in ("cublas", "cuda_nvrtc", "cudnn"):
            _p = os.path.join(_SITE, "nvidia", _pkg, _LIB_SUBDIR, _lib)
            if not os.path.exists(_p):
                continue
            try:
                if _IS_WIN:
                    ctypes.CDLL(_p)
                else:
                    ctypes.CDLL(_p, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

# ── 2. Imports ────────────────────────────────────────────────────────────────
def cuda_runtime_available():
    """Detect an incomplete CUDA runtime before CT2 starts lazy inference."""
    required = (
        ("cublas64_12.dll", "cudnn64_9.dll")
        if _IS_WIN else
        ("libcublas.so.12", "libcudnn.so.9")
    )
    loader = ctypes.WinDLL if _IS_WIN else ctypes.CDLL
    missing = []
    for lib_name in required:
        try:
            loader(lib_name)
        except OSError:
            missing.append(lib_name)
    return not missing, missing


import json, datetime, time, shutil, re, asyncio, random
import numpy as np
import av
import sounddevice as sd
import pygame, keyboard
import ctranslate2
if _IS_WIN:
    # The Windows CT2 wheel bundles cuDNN beside the extension module.
    _ct2_lib_dir = os.path.dirname(ctranslate2.__file__)
    _DLL_DIR_HANDLES.append(os.add_dll_directory(_ct2_lib_dir))
    os.environ["PATH"] = _ct2_lib_dir + os.pathsep + os.environ.get("PATH", "")
import urllib.request, urllib.parse
import google.generativeai as genai
from faster_whisper import WhisperModel
from faster_whisper.feature_extractor import FeatureExtractor
from scipy.signal import resample_poly
from math import gcd
from collections import deque

try:
    import edge_tts as _edge_tts
    EDGE_TTS_OK = True
except ImportError:
    EDGE_TTS_OK = False

# ── 3. Constants ──────────────────────────────────────────────────────────────
_BASE        = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(_BASE, "config", "config.json")
LANG_FILE    = "lang.txt"
COMMAND_FILE = "command.txt"
STATUS_FILE  = "status.txt"
SPEECH_FILE  = "speech.mp3"
QUERY_FILE   = "query.txt"
FACE_GREETING_EVENT_FILE = os.path.join(_BASE, "face_greeting_event.json")
FACE_GREETING_STATE_FILE = os.path.join(_BASE, "config", "face_greeting_state.json")
AUDIO_DIR    = os.path.join(_BASE, "audio")
SONG_DIR     = os.path.join(_BASE, "song")
RATE         = 16000
CHUNK        = 1024
SILENCE_SECS = 0.8   # fallback when not in config.json

# ── 4. Language state ─────────────────────────────────────────────────────────
_current_lang = "th"   # updated from lang.txt in the main loop

def read_lang():
    try:
        with open(LANG_FILE, "r", encoding="utf-8") as f:
            lang = f.read().strip().lower()
        return lang if lang in ("th", "en") else "th"
    except Exception:
        return "th"

# ── 5. Config hot-reload ──────────────────────────────────────────────────────
_config_mtime   = 0
_prompt_mtime   = {"th": 0, "en": 0}
_cfg            = {}
_prompts        = {"th": "", "en": ""}

PROMPT_FILES = {
    "th": os.path.join(_BASE, "config", "system_prompt.txt"),
    "en": os.path.join(_BASE, "config", "system_prompt_en.txt"),
}

def load_config():
    global _config_mtime, _cfg
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
        if mtime != _config_mtime:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
            _config_mtime = mtime
            print(f"[config] Reloaded from {CONFIG_FILE}", flush=True)
    except Exception as e:
        print(f"[config] Read error: {e}", flush=True)

    for lang, pfile in PROMPT_FILES.items():
        try:
            mtime = os.path.getmtime(pfile)
            if mtime != _prompt_mtime[lang]:
                with open(pfile, "r", encoding="utf-8") as f:
                    _prompts[lang] = " ".join(line.strip() for line in f if line.strip())
                _prompt_mtime[lang] = mtime
                print(f"[config] Reloaded {pfile}", flush=True)
        except Exception:
            pass
    return _cfg

def cfg(key, default=None):
    return _cfg.get(key, default)

def get_prompt():
    return _prompts.get(_current_lang, "")

# ── 6. Chat history ───────────────────────────────────────────────────────────
HISTORY_CLEAR_SECS = 300
MAX_HISTORY_PAIRS  = 8
_chat_history      = []
_last_q_time       = 0.0

def clear_history():
    global _chat_history, _last_q_time
    _chat_history = []
    _last_q_time  = 0.0
    print("\n[Chat history cleared]", flush=True)

# ── 7. Gemini AI ──────────────────────────────────────────────────────────────
_GEMINI_ERROR = {"th": "ขอโทษครับ เกิดข้อผิดพลาด", "en": "Sorry, an error occurred."}

def ask_gemini(question):
    global _chat_history, _last_q_time
    load_config()
    now = datetime.datetime.now()
    if _current_lang == "th":
        thai_days = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]
        date_ctx = (f"วันนี้คือวัน{thai_days[now.weekday()]}ที่ "
                    f"{now.day}/{now.month}/{now.year+543} เวลา {now.strftime('%H:%M')} น.")
    else:
        date_ctx = f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')}."
    system = (get_prompt() or cfg("system_prompt", "")) + " " + date_ctx
    try:
        genai.configure(api_key=cfg("gemini_api_key"))
        model = genai.GenerativeModel(
            cfg("gemini_model", "gemini-2.0-flash-lite"),
            system_instruction=system,
            generation_config=genai.GenerationConfig(
                max_output_tokens=cfg("max_output_tokens", 80),
                temperature=cfg("temperature", 0.3),
            ),
        )
        chat   = model.start_chat(history=list(_chat_history))
        answer = chat.send_message(question).text.strip()
        _chat_history.append({"role": "user",  "parts": [question]})
        _chat_history.append({"role": "model", "parts": [answer]})
        if len(_chat_history) > MAX_HISTORY_PAIRS * 2:
            _chat_history = _chat_history[-(MAX_HISTORY_PAIRS * 2):]
        _last_q_time = time.time()
        return answer
    except Exception as e:
        print(f"Gemini error: {e}", flush=True)
        return _GEMINI_ERROR.get(_current_lang, "Error")

# ── 8. TTS ────────────────────────────────────────────────────────────────────
_VOICES = {
    "th": {"niwat": "th-TH-NiwatNeural", "premwadee": "th-TH-PremwadeeNeural"},
    "en": {"aria":  "en-US-AriaNeural",  "guy": "en-US-GuyNeural", "jenny": "en-US-JennyNeural"},
}
_TTS_MODE_KEY = {"th": "tts_mode_th", "en": "tts_mode_en"}
_TTS_DEFAULT  = {"th": "niwat",       "en": "guy"}
_TTS_GOOGLE_LANG = {"th": "th", "en": "en"}

def _is_valid_mp3(data):
    # Valid MP3 starts with an ID3 tag or an MPEG frame sync (0xFFEx).
    if not data or len(data) < 4:
        return False
    if data[:3] == b"ID3":
        return True
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0

def _valid_speech_file():
    try:
        with open(SPEECH_FILE, "rb") as f:
            return _is_valid_mp3(f.read(4))
    except Exception:
        return False

def _boost_tts_audio(gain_db):
    """Increase TTS loudness while soft-limiting peaks to avoid clipping."""
    try:
        gain_db = float(gain_db)
    except (TypeError, ValueError):
        print(f"[TTS] Invalid tts_gain_db={gain_db!r}; using +6 dB", flush=True)
        gain_db = 6.0
    gain_db = max(0.0, min(gain_db, 12.0))
    if gain_db == 0.0:
        return True

    temp_file = SPEECH_FILE + ".boosting.mp3"
    try:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        linear_gain = 10.0 ** (gain_db / 20.0)
        limiter_scale = np.tanh(linear_gain)

        with av.open(SPEECH_FILE) as input_audio:
            input_stream = input_audio.streams.audio[0]
            sample_rate = input_stream.codec_context.sample_rate
            layout = input_stream.codec_context.layout.name
            with av.open(temp_file, "w", format="mp3") as output_audio:
                output_stream = output_audio.add_stream("libmp3lame", rate=sample_rate)
                output_stream.layout = layout
                output_stream.bit_rate = 128000
                for frame in input_audio.decode(input_stream):
                    samples = frame.to_ndarray()
                    if not np.issubdtype(samples.dtype, np.floating):
                        raise TypeError(f"unsupported decoded sample format: {samples.dtype}")
                    # About +gain_db for speech, with a smooth ceiling at 95%.
                    boosted = np.tanh(samples * linear_gain) / limiter_scale * 0.95
                    boosted_frame = av.AudioFrame.from_ndarray(
                        boosted.astype(samples.dtype),
                        format=frame.format.name,
                        layout=frame.layout.name,
                    )
                    boosted_frame.sample_rate = frame.sample_rate
                    for packet in output_stream.encode(boosted_frame):
                        output_audio.mux(packet)
                for packet in output_stream.encode(None):
                    output_audio.mux(packet)

        if not os.path.exists(temp_file) or os.path.getsize(temp_file) < 1024:
            raise RuntimeError("boosted MP3 is empty")
        pygame.mixer.music.unload()
        os.replace(temp_file, SPEECH_FILE)
        print(f"[TTS] Boosted AI voice by +{gain_db:g} dB", flush=True)
        return True
    except Exception as e:
        print(f"[TTS] Audio boost skipped: {e}", flush=True)
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass
        return False

def download_google_tts(text, lang_code):
    url = "https://translate.google.com/translate_tts?ie=UTF-8&q={}&tl={}&client=tw-ob".format(
        urllib.parse.quote(text), lang_code
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if not _is_valid_mp3(data):
            print("TTS error: Google returned non-audio data (rate limited / text too long)")
            return False
        pygame.mixer.music.unload()
        with open(SPEECH_FILE, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print("TTS error:", e)
        return False

def _edge_tts_speak(text, voice, volume):
    async def _run():
        await _edge_tts.Communicate(
            text,
            voice=voice,
            volume=volume,
        ).save(SPEECH_FILE)
    pygame.mixer.music.unload()
    asyncio.run(_run())
    # edge-tts can silently produce an empty/invalid file for some text+voice.
    # Raise so speak() falls back to Google TTS instead of loading bad audio.
    if not _valid_speech_file():
        raise RuntimeError("edge-tts produced empty/invalid audio")

def speak(text, lang_override=None):
    target_lang = lang_override if lang_override in ("th", "en") else _current_lang
    mode_key  = _TTS_MODE_KEY.get(target_lang, "tts_mode_th")
    tts_mode  = cfg(mode_key, _TTS_DEFAULT.get(target_lang, "niwat"))
    tts_volume = str(cfg("tts_volume", "+100%")).strip()
    volume_match = re.match(r"^[+-](\d{1,3})%$", tts_volume)
    if not volume_match or int(volume_match.group(1)) > 100:
        print(f"[TTS] Invalid tts_volume={tts_volume!r}; using +100%", flush=True)
        tts_volume = "+100%"
    voices    = _VOICES.get(target_lang, _VOICES["th"])
    if tts_mode in voices and EDGE_TTS_OK:
        try:
            _edge_tts_speak(text, voices[tts_mode], tts_volume)
            _boost_tts_audio(cfg("tts_gain_db", 6.0))
            return True
        except Exception as e:
            print(f"edge-tts error: {e} — fallback Google TTS")
    success = download_google_tts(text, _TTS_GOOGLE_LANG.get(target_lang, "th"))
    if success:
        _boost_tts_audio(cfg("tts_gain_db", 6.0))
    return success

def _play_speech_blocking():
    # Load + play speech.mp3, guarding against invalid data so a bad TTS/song
    # file logs cleanly instead of crashing pygame's decoder.
    if not _valid_speech_file():
        print(f"[play] Skipped: {SPEECH_FILE} is missing or not a valid MP3", flush=True)
        return
    try:
        pygame.mixer.music.load(SPEECH_FILE)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
    except Exception as e:
        print(f"[play] Audio playback failed: {e}", flush=True)

def play_local():
    if cfg("debug", False):
        _play_speech_blocking()

# ── 9. Audio file helpers ─────────────────────────────────────────────────────
def find_audio_file(filename):
    for folder in [AUDIO_DIR, os.path.dirname(os.path.abspath(__file__))]:
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return path
    return None

def use_audio_file(filepath):
    pygame.mixer.music.unload()
    shutil.copy2(filepath, SPEECH_FILE)
    return True

# ── 10. Song shuffle queue ────────────────────────────────────────────────────
_SONG_COUNTRIES = ("thai", "korea", "japan")
_song_queues = {country: [] for country in _SONG_COUNTRIES}
_SING_INTRO  = {
    "th": "ได้เลยครับเจ้านาย",
    "en": "Sure thing! Here is a song for you.",
}
_SING_EMPTY  = {"th": "ขอโทษครับ ไม่พบเพลงในโฟลเดอร์ครับ", "en": "Sorry, no songs found in the songs folder."}

def get_sing_country(answer):
    """Return a requested country, or None when [SING] asks for a random one."""
    match = re.search(r'\[SING(?:_(THAI|KOREA|JAPAN))?\]', answer, re.IGNORECASE)
    return match.group(1).lower() if match and match.group(1) else None

def pick_next_song(country=None):
    if country not in _SONG_COUNTRIES:
        available = [
            item for item in _SONG_COUNTRIES
            if os.path.isdir(os.path.join(SONG_DIR, item))
            and any(name.lower().endswith(".mp3") for name in os.listdir(os.path.join(SONG_DIR, item)))
        ]
        if not available:
            print(f"[song] No mp3 files in country folders under {SONG_DIR}", flush=True)
            return None
        country = random.choice(available)

    country_dir = os.path.join(SONG_DIR, country)
    if not os.path.isdir(country_dir):
        print(f"[song] Folder not found: {country_dir}", flush=True)
        return None
    songs = [f for f in os.listdir(country_dir) if f.lower().endswith(".mp3")]
    if not songs:
        print(f"[song] No mp3 files in {country_dir}", flush=True)
        return None

    queue = _song_queues[country]
    if not queue or not set(queue).issubset(set(songs)):
        queue[:] = songs
        random.shuffle(queue)
        print(f"[song] Shuffled {len(queue)} {country} songs", flush=True)
    chosen = queue.pop(0)
    # Avoid printing Unicode filenames because some Windows consoles still use cp1252.
    print(f"[song] Playing a {country} song ({len(queue)} remaining)", flush=True)
    return os.path.join(country_dir, chosen), os.path.splitext(chosen)[0]

# ── 11. IPC: communicate with pepper_main.py ─────────────────────────────────
def write_command(text):
    with open(COMMAND_FILE, "w", encoding="utf-8") as f:
        f.write(text)

def write_query(text):
    with open(QUERY_FILE, "w", encoding="utf-8") as f:
        f.write(text)

def write_status(status):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(status)

def read_status():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "ready"


_FACE_GREETINGS = {
    "th": {
        "morning": [
            "สวัสดีตอนเช้าครับคุณ{name} วันนี้สบายดีไหมครับ",
            "อรุณสวัสดิ์ครับคุณ{name} มีอะไรให้ผมช่วยไหมครับ",
            "สวัสดีตอนเช้าครับคุณ{name} เช้านี้เป็นอย่างไรบ้างครับ",
            "ยินดีที่ได้พบคุณ{name} ในเช้าวันนี้ครับ ต้องการให้ช่วยอะไรไหมครับ",
        ],
        "afternoon": [
            "สวัสดีตอนบ่ายครับคุณ{name} วันนี้สบายดีไหมครับ",
            "สวัสดีตอนบ่ายครับคุณ{name} มีอะไรให้ผมช่วยไหมครับ",
            "ยินดีที่ได้พบคุณ{name} ในบ่ายวันนี้ครับ เป็นอย่างไรบ้างครับ",
            "สวัสดีครับคุณ{name} ช่วงบ่ายวันนี้ต้องการให้ผมช่วยอะไรไหมครับ",
        ],
        "evening": [
            "สวัสดีตอนเย็นครับคุณ{name} วันนี้เป็นอย่างไรบ้างครับ",
            "สวัสดีตอนเย็นครับคุณ{name} มีอะไรให้ผมช่วยไหมครับ",
            "ยินดีที่ได้พบคุณ{name} ในเย็นวันนี้ครับ สบายดีไหมครับ",
            "สวัสดีครับคุณ{name} เย็นนี้ต้องการให้ผมช่วยอะไรหรือเปล่าครับ",
        ],
        "night": [
            "สวัสดีตอนค่ำครับคุณ{name} วันนี้เป็นอย่างไรบ้างครับ",
            "สวัสดีครับคุณ{name} ดึกแล้ว มีอะไรให้ผมช่วยไหมครับ",
            "ยินดีที่ได้พบคุณ{name} ในคืนนี้ครับ สบายดีไหมครับ",
        ],
    },
    "en": {
        "morning": [
            "Good morning, {name}. How are you today?",
            "Good morning, {name}. How can I help you today?",
            "Morning, {name}. I hope you are doing well. What can I do for you?",
            "It is nice to see you this morning, {name}. How may I help?",
        ],
        "afternoon": [
            "Good afternoon, {name}. How are you today?",
            "Good afternoon, {name}. How can I help you?",
            "It is nice to see you this afternoon, {name}. How have you been?",
            "Hello, {name}. What can I do for you this afternoon?",
        ],
        "evening": [
            "Good evening, {name}. How are you today?",
            "Good evening, {name}. Is there anything I can help you with?",
            "It is nice to see you this evening, {name}. How have you been?",
            "Hello, {name}. What can I do for you this evening?",
        ],
        "night": [
            "Good evening, {name}. How are you tonight?",
            "Hello, {name}. You are up late. Is there anything I can help with?",
            "It is nice to see you tonight, {name}. How may I help?",
        ],
    },
}


def _is_unknown_face_name(name):
    try:
        normalized = re.sub(r"[\s_]+", "", str(name).casefold())
    except Exception:
        return True
    return normalized in {
        "", "unknown", "unknow", "unrecognized", "unrecognised",
        "none", "null", "?",
    }


def _face_greeting_period(moment=None):
    hour = (moment or datetime.datetime.now()).hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _read_face_greeting_state():
    try:
        with open(FACE_GREETING_STATE_FILE, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
        return state if isinstance(state, dict) else {"people": {}}
    except Exception:
        return {"people": {}}


def _write_face_greeting_state(state):
    temp_path = FACE_GREETING_STATE_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as state_file:
            json.dump(state, state_file, ensure_ascii=False, indent=2)
        os.replace(temp_path, FACE_GREETING_STATE_FILE)
    except Exception as exc:
        print(f"[face greeting] Could not save state: {exc}", flush=True)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _take_face_greeting_event():
    if not os.path.exists(FACE_GREETING_EVENT_FILE):
        return None
    try:
        with open(FACE_GREETING_EVENT_FILE, "r", encoding="utf-8") as event_file:
            event = json.load(event_file)
        name = str(event.get("name", "")).strip()
        try:
            seen_at = float(event.get("seen_at", 0.0))
        except (TypeError, ValueError):
            seen_at = 0.0
        if _is_unknown_face_name(name):
            name = ""
        os.remove(FACE_GREETING_EVENT_FILE)
        if time.time() - seen_at > 10.0:
            return None
        return name or None
    except (OSError, ValueError, TypeError) as exc:
        print(f"[face greeting] Event read error: {exc}", flush=True)
        return None


def greet_recognized_face():
    """Greet one queued known face when Pepper is free; return True if spoken."""
    if not cfg("face_greeting_enabled", True):
        # Do not keep a stale face queued and greet it later after re-enabling.
        _take_face_greeting_event()
        return False
    if read_status() != "ready":
        return False
    try:
        with open(COMMAND_FILE, "r", encoding="utf-8") as command_file:
            if command_file.read().strip():
                return False
    except OSError:
        pass
    name = _take_face_greeting_event()
    if not name:
        return False

    try:
        reset_minutes = max(0.0, float(cfg("face_greeting_reset_minutes", 10)))
    except (TypeError, ValueError):
        reset_minutes = 10.0
    state = _read_face_greeting_state()
    people = state.get("people")
    if not isinstance(people, dict):
        people = {}
        state["people"] = people
    person_key = name.casefold()
    previous = people.get(person_key, {})
    now = time.time()
    try:
        last_greeted = float(previous.get("last_greeted_at", 0.0))
    except (TypeError, ValueError):
        last_greeted = 0.0
    if now - last_greeted < reset_minutes * 60.0:
        return False

    lang = _current_lang if _current_lang in _FACE_GREETINGS else "th"
    period = _face_greeting_period()
    templates = _FACE_GREETINGS[lang][period]
    choices = [
        template.format(name=name) for template in templates
        if template.format(name=name) != previous.get("greeting")
    ]
    if not choices:
        choices = [template.format(name=name) for template in templates]
    greeting = random.choice(choices)
    print(f"\n[face greeting] {name}: {greeting}", flush=True)
    write_status("wait")
    if not speak(greeting, lang_override=lang):
        write_status("ready")
        return False

    write_status("busy")
    write_command(greeting)
    play_local()
    people[person_key] = {
        "name": name,
        "last_greeted_at": now,
        "last_greeted_iso": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "language": lang,
        "period": period,
        "greeting": greeting,
    }
    _write_face_greeting_state(state)
    return True

# ── 12. Audio recording ───────────────────────────────────────────────────────
class MicInput(object):
    """sounddevice InputStream with a pyaudio-like read() that returns int16 bytes."""

    def __init__(self, device, samplerate, channels=1, blocksize=CHUNK):
        self._stream = sd.InputStream(
            device=device,
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
        )
        self._stream.start()

    def read(self, frames, exception_on_overflow=False):
        data, overflowed = self._stream.read(frames)
        if overflowed and exception_on_overflow:
            raise RuntimeError("microphone input overflowed")
        # sounddevice returns shape (frames, channels); flatten to int16 bytes
        return np.asarray(data, dtype=np.int16).reshape(-1).tobytes()

    def stop_stream(self):
        if self._stream.active:
            self._stream.stop()

    def close(self):
        self._stream.close()


def list_input_devices():
    """Return [(device_index, name), ...] for devices with input channels."""
    devices = sd.query_devices()
    result = []
    for i, info in enumerate(devices):
        if int(info.get("max_input_channels", 0) or 0) > 0:
            result.append((i, info.get("name", "input-%d" % i)))
    return result


def default_input_rate(device_index=None):
    info = sd.query_devices(device_index, "input")
    return int(info.get("default_samplerate") or RATE)


def drain_buffer(seconds=1.5):
    chunks = int(seconds * DEVICE_RATE / CHUNK)
    for _ in range(chunks):
        stream.read(CHUNK, exception_on_overflow=False)

def record_until_silence(pre_frames=None):
    silence_threshold = cfg(f"silence_threshold_{_current_lang}", 400)
    max_chunks   = int(cfg("max_record_secs", 6) * DEVICE_RATE / CHUNK)
    silent_limit = int(cfg("silence_secs", SILENCE_SECS) * DEVICE_RATE / CHUNK)
    frames       = list(pre_frames) if pre_frames else []
    silent_chunks = 0
    while len(frames) < max_chunks:
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        if rms < silence_threshold:
            silent_chunks += 1
            if silent_chunks >= silent_limit and len(frames) > silent_limit:
                break
        else:
            silent_chunks = 0
    audio = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
    if DEVICE_RATE != RATE:
        g = gcd(DEVICE_RATE, RATE)
        audio = resample_poly(audio, RATE // g, DEVICE_RATE // g)
    return audio

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════
load_config()
_current_lang = read_lang()
print(f"Starting language: {_current_lang.upper()}", flush=True)
try:
    pygame.mixer.init()
except pygame.error as e:
    # Dev containers / headless hosts often have no ALSA device.
    # Dummy driver lets TTS write speech.mp3; local play stays silent.
    print(f"[audio] mixer init failed ({e}); using SDL dummy driver", flush=True)
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.mixer.quit()
    pygame.mixer.init()


cuda_count = ctranslate2.get_cuda_device_count()
cuda_runtime_ok, missing_cuda_libs = cuda_runtime_available()
FORCE_CPU = False
use_cuda = not FORCE_CPU and cuda_count > 0 and cuda_runtime_ok
device_label = "CPU (forced)" if FORCE_CPU else ("GPU (CUDA)" if use_cuda else "CPU")
print(f"CUDA devices: {cuda_count}  →  Using: {device_label}", flush=True)
if FORCE_CPU:
    print("  [info] Whisper is configured to run on CPU with int8 compute.", flush=True)
elif not use_cuda:
    if cuda_count > 0 and missing_cuda_libs:
        print(
            "  [warning] GPU detected, but missing CUDA libraries: "
            + ", ".join(missing_cuda_libs),
            flush=True,
        )
    print(
        "  [tip] For GPU: install nvidia-cublas-cu12 nvidia-cudnn-cu12, "
        "and ensure the NVIDIA driver is visible (nvidia-smi). "
        "In Dev Container: rebuild with GPU / --gpus all.",
        flush=True,
    )

_MODEL_PATH = cfg("whisper_model_path") or "large-v3"
print(f"Loading Whisper model: {_MODEL_PATH}", flush=True)
whisper = WhisperModel(
    _MODEL_PATH,
    device       = "cuda" if use_cuda else "cpu",
    compute_type = "float16" if use_cuda else "int8",
    cpu_threads  = 8,
    num_workers  = 2,
)
whisper.feature_extractor = FeatureExtractor(feature_size=128)
print("STT model loaded!", flush=True)


def transcribe_audio(audio, language):
    """Transcribe eagerly and retry once on CPU if CUDA fails."""
    global whisper, use_cuda

    options = dict(
        language=language,
        beam_size=cfg("beam_size", 1),
        temperature=0,
        no_speech_threshold=0.6,
        condition_on_previous_text=False,
        compression_ratio_threshold=2.0,
        vad_filter=True,
    )
    try:
        segments, info = whisper.transcribe(audio, **options)
        return list(segments), info
    except RuntimeError as exc:
        message = str(exc).lower()
        cuda_failure = any(
            marker in message
            for marker in ("cublas", "cudnn", "cuda", "library")
        )
        if not use_cuda or not cuda_failure:
            raise

        print(
            f"\n[warning] CUDA transcription failed ({exc}); retrying on CPU...",
            flush=True,
        )
        use_cuda = False
        whisper = WhisperModel(
            _MODEL_PATH,
            device="cpu",
            compute_type="int8",
            cpu_threads=8,
            num_workers=2,
        )
        whisper.feature_extractor = FeatureExtractor(feature_size=128)
        segments, info = whisper.transcribe(audio, **options)
        return list(segments), info


print("\n--- Microphones ---")
input_devices = list_input_devices()
for n, (_idx, name) in enumerate(input_devices):
    print(f"  [{n}] {name}")

selected = input("\nSelect microphone number (Enter = default): ").strip()
if selected.isdigit() and int(selected) < len(input_devices):
    device_index = input_devices[int(selected)][0]
    print(f"Using: {input_devices[int(selected)][1]}")
else:
    device_index = None
    print("Using default device")

DEVICE_RATE = default_input_rate(device_index)
print(f"Sample rate: {DEVICE_RATE} Hz")

stream = MicInput(device=device_index, samplerate=DEVICE_RATE, blocksize=CHUNK)
pre_buf = deque(maxlen=int(0.4 * DEVICE_RATE / CHUNK) + 1)
write_status("ready")
print(f"\nReady — [Space]=reset busy   Ctrl+C=stop")
print(f"Language on tablet: TH / EN button  (current: {_current_lang.upper()})\n")

_GREETINGS = {
    "th": "สวัสดีครับ พร้อมรับคำถามแล้ว",
    "en": "Hello! I am ready to answer your questions.",
}
GREETING = _GREETINGS.get(_current_lang, _GREETINGS["th"])
if speak(GREETING):
    play_local()          # PC เล่นเฉพาะตอน debug=true (กันเสียงซ้อนกับลำโพงหุ่น)
write_command(GREETING)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
_USER_LABEL  = {"th": "ผู้ใช้", "en": "User"}
_THINK_LABEL = {"th": "Gemini กำลังคิด...", "en": "Gemini thinking..."}
_STT_LABEL   = {"th": "กำลังถอดเสียง...", "en": "Transcribing..."}

try:
    while True:
        load_config()

        # ── Detect language change from tablet UI ─────────────────────────────
        new_lang = read_lang()
        if new_lang != _current_lang:
            _current_lang = new_lang
            clear_history()
            greet = _GREETINGS.get(_current_lang, _GREETINGS["th"])
            print(f"\n[Language → {_current_lang.upper()}]", flush=True)
            write_status("wait")   # UI แสดง WAIT ระหว่าง generate TTS
            if speak(greet):
                play_local()       # PC เล่นเฉพาะตอน debug=true (กันเสียงซ้อนกับลำโพงหุ่น)
            write_command(greet)   # pepper_main รับแล้วเปลี่ยนเป็น busy → drain → ready

        silence_threshold = cfg(f"silence_threshold_{_current_lang}", 400)

        # Auto-clear history after 5 minutes of inactivity
        if _last_q_time and time.time() - _last_q_time > HISTORY_CLEAR_SECS:
            clear_history()

        pepper_up = os.path.exists(STATUS_FILE)
        was_busy  = False
        if pepper_up:
            while read_status() == "busy":
                was_busy = True
                stream.read(CHUNK, exception_on_overflow=False)  # drain mic while Pepper speaks
                if keyboard.is_pressed("space"):
                    write_status("ready")
                    clear_history()
                    was_busy = False
                    break
            if was_busy or read_status() == "drain":
                drain_buffer()
                pre_buf.clear()
                write_status("ready")

        # Face greetings use the same TTS/command path as normal answers and
        # are only dispatched while the conversation pipeline is idle.
        if greet_recognized_face():
            continue

        data = stream.read(CHUNK, exception_on_overflow=False)
        rms  = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        print(f"\r[{_current_lang.upper()}][RMS: {rms:6.0f}]", end="", flush=True)
        pre_buf.append(data)
        if rms < silence_threshold:
            continue

        audio = record_until_silence(list(pre_buf))
        pre_buf.clear()
        print(_STT_LABEL.get(_current_lang, "Transcribing..."), flush=True)
        segments, _ = transcribe_audio(audio, _current_lang)
        confident = [s for s in segments if s.avg_logprob > -1.0 and s.no_speech_prob < 0.6]
        text = "".join(s.text for s in confident).strip()

        if text:
            print(f"{_USER_LABEL.get(_current_lang,'User')}: {text}", flush=True)
            write_query(text)
            print(_THINK_LABEL.get(_current_lang, "Thinking..."), flush=True)
            t0     = time.time()
            answer = ask_gemini(text)
            print(f"Answer ({time.time()-t0:.1f}s): {answer}", flush=True)

            sing_match = re.search(r'\[SING(?:_(THAI|KOREA|JAPAN))?\]', answer, re.IGNORECASE)
            if sing_match:
                result = pick_next_song(get_sing_country(answer))
                if result:
                    audio_path, display = result
                    intro = _SING_INTRO.get(_current_lang, _SING_INTRO["th"])
                    if speak(intro, lang_override=_current_lang):
                        if pepper_up:
                            write_status("busy")
                        write_command(intro)
                        play_local()
                        if pepper_up:
                            while read_status() == "busy":
                                stream.read(CHUNK, exception_on_overflow=False)  # drain mic during intro
                    if use_audio_file(audio_path):
                        if pepper_up:
                            write_status("busy")
                        write_command(display)
                        play_local()
                else:
                    speak_text = _SING_EMPTY.get(_current_lang, "")
                    if speak(speak_text):
                        if pepper_up:
                            write_status("busy")
                        write_command(speak_text)
                        play_local()
                # Song tokens are internal controls and must never reach TTS.
                continue
            else:
                mp3_match  = re.search(r'([\w\-]+\.mp3)', answer, re.IGNORECASE)
                audio_path = find_audio_file(mp3_match.group(1)) if mp3_match else None
                if audio_path:
                    print(f"[play file] {audio_path}", flush=True)
                    if use_audio_file(audio_path):
                        display = os.path.splitext(mp3_match.group(1))[0]
                        if pepper_up:
                            write_status("busy")
                        write_command(display)
                        play_local()

            no_mp3  = not re.search(r'[\w\-]+\.mp3', answer, re.IGNORECASE)
            if no_mp3:
                if speak(answer):
                    if pepper_up:
                        write_status("busy")
                    write_command(answer)
                    play_local()

except KeyboardInterrupt:
    stream.stop_stream()
    stream.close()
    print("\nStopped.")
