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
_CUDA_LIBS = (
    ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"]
    if _IS_WIN else
    ["libcublas.so.12", "libcublasLt.so.12", "libcudnn.so.9", "libcudnn_ops.so.9"]
)

for _SITE in _SITES:
    for _pkg in ("cublas", "cudnn"):
        _d = os.path.join(_SITE, "nvidia", _pkg, _LIB_SUBDIR)
        if not os.path.isdir(_d):
            continue
        if _IS_WIN:
            os.add_dll_directory(_d)
            os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")
        else:
            os.environ["LD_LIBRARY_PATH"] = _d + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")

for _lib in _CUDA_LIBS:
    for _SITE in _SITES:
        for _pkg in ("cublas", "cudnn"):
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
import json, datetime, time, shutil, re, asyncio, random
import numpy as np
import sounddevice as sd
import pygame, keyboard
import ctranslate2
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

def _edge_tts_speak(text, voice):
    async def _run():
        await _edge_tts.Communicate(text, voice=voice).save(SPEECH_FILE)
    pygame.mixer.music.unload()
    asyncio.run(_run())
    # edge-tts can silently produce an empty/invalid file for some text+voice.
    # Raise so speak() falls back to Google TTS instead of loading bad audio.
    if not _valid_speech_file():
        raise RuntimeError("edge-tts produced empty/invalid audio")

def speak(text):
    mode_key  = _TTS_MODE_KEY.get(_current_lang, "tts_mode_th")
    tts_mode  = cfg(mode_key, _TTS_DEFAULT.get(_current_lang, "niwat"))
    voices    = _VOICES.get(_current_lang, _VOICES["th"])
    if tts_mode in voices and EDGE_TTS_OK:
        try:
            _edge_tts_speak(text, voices[tts_mode])
            return True
        except Exception as e:
            print(f"edge-tts error: {e} — fallback Google TTS")
    return download_google_tts(text, _TTS_GOOGLE_LANG.get(_current_lang, "th"))

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
_song_queue = []
_SING_INTRO  = {"th": "ได้เลยครับเจ้านาย",               "en": "Sure thing! Here is a song for you."}
_SING_EMPTY  = {"th": "ขอโทษครับ ไม่พบเพลงในโฟลเดอร์ครับ", "en": "Sorry, no songs found in the songs folder."}

def pick_next_song():
    global _song_queue
    if not os.path.isdir(SONG_DIR):
        print(f"[song] Folder not found: {SONG_DIR}", flush=True)
        return None
    songs = [f for f in os.listdir(SONG_DIR) if f.lower().endswith(".mp3")]
    if not songs:
        print(f"[song] No mp3 files in {SONG_DIR}", flush=True)
        return None
    if not _song_queue:
        _song_queue.extend(songs)
        random.shuffle(_song_queue)
        print(f"[song] Shuffled {len(_song_queue)} songs", flush=True)
    chosen = _song_queue.pop(0)
    print(f"[song] Playing: {chosen}  ({len(_song_queue)} remaining)", flush=True)
    return os.path.join(SONG_DIR, chosen), os.path.splitext(chosen)[0]

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
use_cuda   = cuda_count > 0
print(f"CUDA devices: {cuda_count}  →  Using: {'GPU (CUDA)' if use_cuda else 'CPU'}", flush=True)
if not use_cuda:
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

        data = stream.read(CHUNK, exception_on_overflow=False)
        rms  = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        print(f"\r[{_current_lang.upper()}][RMS: {rms:6.0f}]", end="", flush=True)
        pre_buf.append(data)
        if rms < silence_threshold:
            continue

        audio = record_until_silence(list(pre_buf))
        pre_buf.clear()
        print(_STT_LABEL.get(_current_lang, "Transcribing..."), flush=True)
        segments, _ = whisper.transcribe(
            audio,
            language                   = _current_lang,
            beam_size                  = cfg("beam_size", 1),
            temperature                = 0,
            no_speech_threshold        = 0.6,
            condition_on_previous_text = False,
            compression_ratio_threshold= 2.0,
            vad_filter                 = True,
        )
        confident = [s for s in segments if s.avg_logprob > -1.0 and s.no_speech_prob < 0.6]
        text = "".join(s.text for s in confident).strip()

        if text:
            print(f"{_USER_LABEL.get(_current_lang,'User')}: {text}", flush=True)
            write_query(text)
            print(_THINK_LABEL.get(_current_lang, "Thinking..."), flush=True)
            t0     = time.time()
            answer = ask_gemini(text)
            print(f"Answer ({time.time()-t0:.1f}s): {answer}", flush=True)

            if re.search(r'\[SING\]', answer, re.IGNORECASE):
                result = pick_next_song()
                if result:
                    audio_path, display = result
                    intro = _SING_INTRO.get(_current_lang, "")
                    if speak(intro):
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

            no_sing = not re.search(r'\[SING\]', answer, re.IGNORECASE)
            no_mp3  = not re.search(r'[\w\-]+\.mp3', answer, re.IGNORECASE)
            if no_sing and no_mp3:
                if speak(answer):
                    if pepper_up:
                        write_status("busy")
                    write_command(answer)
                    play_local()

except KeyboardInterrupt:
    stream.stop_stream()
    stream.close()
    print("\nStopped.")
