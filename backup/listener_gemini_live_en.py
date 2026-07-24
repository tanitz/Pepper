# -*- coding: utf-8 -*-
# listener_gemini_live_en.py
# STT: Whisper CT2  |  AI: Google Gemini  |  TTS: edge-tts (English)
# Edit config_en.json and save → changes take effect immediately without restart

# ── 1. CUDA DLL preload (must be before other imports) ────────────────────────
import os, ctypes, site as _site

_SITES = _site.getsitepackages() if hasattr(_site, "getsitepackages") else []
for _SITE in _SITES:
    for _pkg in ["cublas", "cudnn"]:
        _d = os.path.join(_SITE, "nvidia", _pkg, "bin")
        if os.path.isdir(_d):
            os.add_dll_directory(_d)
            os.environ["PATH"] = _d + ";" + os.environ.get("PATH", "")
for _dll in ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll"]:
    for _SITE in _SITES:
        for _pkg in ["cublas", "cudnn"]:
            _p = os.path.join(_SITE, "nvidia", _pkg, "bin", _dll)
            if os.path.exists(_p):
                try: ctypes.CDLL(_p)
                except: pass

# ── 2. Imports ────────────────────────────────────────────────────────────────
import json, datetime, time, shutil, re, asyncio, random
import numpy as np
import pyaudio, pygame, keyboard
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
CONFIG_FILE  = "config_en.json"
PROMPT_FILE  = "system_prompt_en.txt"
COMMAND_FILE = "command.txt"
STATUS_FILE  = "status.txt"
SPEECH_FILE  = "speech.mp3"
QUERY_FILE   = "query.txt"
AUDIO_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
SONG_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "song")
RATE         = 16000
CHUNK        = 1024
SILENCE_SECS = 0.8        # fallback if not set in config_en.json

# ── TTS voice selection ───────────────────────────────────────────────────────
# "aria"  → edge-tts: en-US-AriaNeural  (female)
# "guy"   → edge-tts: en-US-GuyNeural   (male)
# "jenny" → edge-tts: en-US-JennyNeural (female)
TTS_MODE = "guy"

# ── 4. Config: hot-reload ─────────────────────────────────────────────────────
_config_mtime = 0
_prompt_mtime = 0
_cfg          = {}
_prompt_text  = ""

# ── 4b. Chat history ──────────────────────────────────────────────────────────
HISTORY_CLEAR_SECS = 300   # auto-clear after 5 minutes of inactivity
MAX_HISTORY_PAIRS  = 8     # remember up to 8 question-answer pairs
_chat_history      = []    # [{"role":"user","parts":[q]}, {"role":"model","parts":[a]}, ...]
_last_q_time       = 0.0

def load_config():
    global _config_mtime, _prompt_mtime, _cfg, _prompt_text
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
        if mtime != _config_mtime:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                _cfg = json.load(f)
            _config_mtime = mtime
            print(f"[config] Reloaded from {CONFIG_FILE}", flush=True)
    except Exception as e:
        print(f"[config] Read error: {e}", flush=True)
    try:
        mtime = os.path.getmtime(PROMPT_FILE)
        if mtime != _prompt_mtime:
            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                _prompt_text = " ".join(line.strip() for line in f if line.strip())
            _prompt_mtime = mtime
            print(f"[config] Reloaded prompt from {PROMPT_FILE}", flush=True)
    except Exception as e:
        print(f"[config] Prompt read error: {e}", flush=True)
    return _cfg

def cfg(key, default=None):
    return _cfg.get(key, default)

# ── 5. Gemini AI ──────────────────────────────────────────────────────────────
def ask_gemini(question):
    global _chat_history, _last_q_time
    load_config()
    now      = datetime.datetime.now()
    date_ctx = f"Today is {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')}."
    system   = (_prompt_text or cfg("system_prompt", "")) + " " + date_ctx
    try:
        genai.configure(api_key=cfg("gemini_api_key"))
        model = genai.GenerativeModel(
            cfg("gemini_model", "gemini-3.1-flash-lite"),
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
        return "Sorry, an error occurred."

def clear_history():
    global _chat_history, _last_q_time
    _chat_history = []
    _last_q_time  = 0.0
    print("\n[Chat history cleared]", flush=True)

# ── 6. TTS ────────────────────────────────────────────────────────────────────

_EDGE_TTS_VOICES = {
    "aria":  "en-US-AriaNeural",
    "guy":   "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
}

def download_tts_google(text):
    url = "https://translate.google.com/translate_tts?ie=UTF-8&q={}&tl=en&client=tw-ob".format(
        urllib.parse.quote(text)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        pygame.mixer.music.unload()
        with open(SPEECH_FILE, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print("TTS error:", e)
        return False

def play_local():
    if cfg("debug", False):
        pygame.mixer.music.load(SPEECH_FILE)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)

def _edge_tts_speak(text, voice_key):
    async def _run():
        await _edge_tts.Communicate(text, voice=_EDGE_TTS_VOICES[voice_key]).save(SPEECH_FILE)
    pygame.mixer.music.unload()
    asyncio.run(_run())

def speak(text):
    if TTS_MODE in _EDGE_TTS_VOICES and EDGE_TTS_OK:
        try:
            _edge_tts_speak(text, TTS_MODE)
            return True
        except Exception as e:
            print(f"edge-tts error: {e} — fallback Google TTS")
    return download_tts_google(text)

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

# ── Song shuffle queue ────────────────────────────────────────────────────────
_song_queue = []

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
    print(f"[song] Playing: {chosen}  ({len(_song_queue)} remaining in queue)", flush=True)
    return os.path.join(SONG_DIR, chosen), os.path.splitext(chosen)[0]

# ── 7. IPC: communicate with pepper_main_py2.py ───────────────────────────────
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
    except:
        return "ready"

# ── 8. Audio: record and process ──────────────────────────────────────────────
def drain_buffer(seconds=1.5):
    chunks = int(seconds * DEVICE_RATE / CHUNK)
    for _ in range(chunks):
        stream.read(CHUNK, exception_on_overflow=False)

def record_until_silence(pre_frames=None):
    silence_threshold = cfg("silence_threshold", 400)
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
pygame.mixer.init()

cuda_count = ctranslate2.get_cuda_device_count()
use_cuda   = cuda_count > 0
print(f"CUDA devices: {cuda_count}  →  Using: {'GPU (CUDA)' if use_cuda else 'CPU'}", flush=True)
if not use_cuda:
    print("  [tip] For GPU: py -3 -m pip install ctranslate2 --force-reinstall", flush=True)

_MODEL_PATH = cfg("whisper_model_path") or "large-v3"
whisper = WhisperModel(
    _MODEL_PATH,
    device       = "cuda" if use_cuda else "cpu",
    compute_type = "float16" if use_cuda else "int8",
    cpu_threads  = 8,
    num_workers  = 2,
)
whisper.feature_extractor = FeatureExtractor(feature_size=128)
print("STT model loaded!", flush=True)

p = pyaudio.PyAudio()
print("\n--- Microphones found ---")
input_devices = []
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info["maxInputChannels"] > 0:
        input_devices.append((i, info["name"]))
        print(f"  [{len(input_devices)-1}] {info['name']}")

selected = input("\nSelect microphone number (Enter = default): ").strip()
if selected.isdigit() and int(selected) < len(input_devices):
    device_index = input_devices[int(selected)][0]
    print(f"Using: {input_devices[int(selected)][1]}")
else:
    device_index = None
    print("Using default device")

DEVICE_RATE = int(p.get_device_info_by_index(device_index)["defaultSampleRate"]) if device_index is not None \
              else int(p.get_default_input_device_info()["defaultSampleRate"])
print(f"Sample rate: {DEVICE_RATE} Hz")

stream = p.open(format=pyaudio.paInt16, channels=1, rate=DEVICE_RATE,
                input=True, input_device_index=device_index, frames_per_buffer=CHUNK)
stream.start_stream()
pre_buf = deque(maxlen=int(0.4 * DEVICE_RATE / CHUNK) + 1)  # pre-buffer 400ms
write_status("ready")
print(f"\nReady to listen  [Space]=reset busy  Ctrl+C=stop")
print(f"Edit config_en.json and save → takes effect on next question\n")

GREETING = "Hello! I am ready to answer your questions."
if speak(GREETING):
    pygame.mixer.music.load(SPEECH_FILE)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.05)
write_command(GREETING)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
try:
    while True:
        load_config()
        silence_threshold = cfg("silence_threshold", 400)

        # Auto-clear history after 5 minutes of inactivity
        if _last_q_time and time.time() - _last_q_time > HISTORY_CLEAR_SECS:
            clear_history()

        pepper_up = os.path.exists(STATUS_FILE)
        was_busy  = False
        if pepper_up:
            while read_status() == "busy":
                was_busy = True
                if keyboard.is_pressed("space"):
                    write_status("ready")
                    clear_history()
                    was_busy = False
                    break
                time.sleep(0.2)
            if was_busy or read_status() == "drain":
                drain_buffer()
                pre_buf.clear()
                write_status("ready")

        data = stream.read(CHUNK, exception_on_overflow=False)
        rms  = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        print(f"\r[RMS: {rms:6.0f}]", end="", flush=True)
        pre_buf.append(data)
        if rms < silence_threshold:
            continue

        audio = record_until_silence(list(pre_buf))
        pre_buf.clear()
        print("Transcribing...", flush=True)
        segments, _ = whisper.transcribe(
            audio, language="en",
            beam_size=cfg("beam_size", 1),
            temperature=0,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.0,
            vad_filter=True,
        )
        confident = [s for s in segments if s.avg_logprob > -1.0 and s.no_speech_prob < 0.6]
        text = "".join(s.text for s in confident).strip()

        if text:
            print(f"User: {text}", flush=True)
            write_query(text)
            print("Gemini thinking...", flush=True)
            t0     = time.time()
            answer = ask_gemini(text)
            print(f"Answer ({time.time()-t0:.1f}s): {answer}", flush=True)
            if re.search(r'\[SING\]', answer, re.IGNORECASE):
                result = pick_next_song()
                if result:
                    audio_path, display = result
                    intro = "Sure thing! Here is a song for you."
                    if speak(intro):
                        if pepper_up:
                            write_status("busy")
                        write_command(intro)
                        play_local()
                        if pepper_up:
                            while read_status() == "busy":
                                time.sleep(0.1)
                    if use_audio_file(audio_path):
                        if pepper_up:
                            write_status("busy")
                        write_command(display)
                        play_local()
                else:
                    speak_text = "Sorry, no songs found in the songs folder."
                    if speak(speak_text):
                        if pepper_up:
                            write_status("busy")
                        write_command(speak_text)
                        play_local()
            else:
                mp3_match = re.search(r'([\w\-]+\.mp3)', answer, re.IGNORECASE)
                audio_path = find_audio_file(mp3_match.group(1)) if mp3_match else None
                if audio_path:
                    print(f"[play file] {audio_path}", flush=True)
                    if use_audio_file(audio_path):
                        display = os.path.splitext(mp3_match.group(1))[0]
                        if pepper_up:
                            write_status("busy")
                        write_command(display)
                        play_local()
            if not re.search(r'\[SING\]', answer, re.IGNORECASE) and not re.search(r'[\w\-]+\.mp3', answer, re.IGNORECASE):
                if speak(answer):
                    if pepper_up:
                        write_status("busy")
                    write_command(answer)
                    play_local()

except KeyboardInterrupt:
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("\nStopped.")
