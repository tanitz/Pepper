# -*- coding: utf-8 -*-
# listener_gemini_live.py
# STT: Thonburian Whisper CT2  |  AI: Google Gemini  |  TTS: Google Translate
# แก้ไข config.json แล้วบันทึก → มีผลทันทีโดยไม่ต้อง restart

# ── 1. CUDA DLL preload (ต้องอยู่ก่อน import อื่น) ───────────────────────────
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
import json, datetime, time
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

# ── 3. Constants ──────────────────────────────────────────────────────────────
CONFIG_FILE  = "config.json"
PROMPT_FILE  = "system_prompt.txt"
COMMAND_FILE = "command.txt"
STATUS_FILE  = "status.txt"
SPEECH_FILE  = "speech.mp3"
QUERY_FILE   = "query.txt"
RATE         = 16000
CHUNK        = 1024
SILENCE_SECS = 0.8        # fallback ถ้าไม่มีใน config.json

# ── 4. Config: hot-reload ─────────────────────────────────────────────────────
_config_mtime = 0
_prompt_mtime = 0
_cfg          = {}
_prompt_text  = ""

# ── 4b. Chat history ──────────────────────────────────────────────────────────
HISTORY_CLEAR_SECS = 300   # auto-clear หลัง 5 นาที ไม่มีคำถาม
MAX_HISTORY_PAIRS  = 8     # จำได้สูงสุด 8 คู่ถาม-ตอบ
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
            print(f"[config] โหลดใหม่จาก {CONFIG_FILE}", flush=True)
    except Exception as e:
        print(f"[config] อ่านไฟล์ผิดพลาด: {e}", flush=True)
    try:
        mtime = os.path.getmtime(PROMPT_FILE)
        if mtime != _prompt_mtime:
            with open(PROMPT_FILE, "r", encoding="utf-8") as f:
                _prompt_text = " ".join(line.strip() for line in f if line.strip())
            _prompt_mtime = mtime
            print(f"[config] โหลด prompt ใหม่จาก {PROMPT_FILE}", flush=True)
    except Exception as e:
        print(f"[config] อ่าน prompt ผิดพลาด: {e}", flush=True)
    return _cfg

def cfg(key, default=None):
    return _cfg.get(key, default)

# ── 5. Gemini AI ──────────────────────────────────────────────────────────────
def ask_gemini(question):
    global _chat_history, _last_q_time
    load_config()
    now      = datetime.datetime.now()
    thai_days = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]
    date_ctx = (f"วันนี้คือวัน{thai_days[now.weekday()]}ที่ "
                f"{now.day}/{now.month}/{now.year+543} เวลา {now.strftime('%H:%M')} น.")
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
        return "ขอโทษครับ เกิดข้อผิดพลาด"

def clear_history():
    global _chat_history, _last_q_time
    _chat_history = []
    _last_q_time  = 0.0
    print("\n[ล้างประวัติการสนทนาแล้ว]", flush=True)

# ── 6. TTS (Google Translate) ─────────────────────────────────────────────────
def download_thai_tts(text):
    url = "https://translate.google.com/translate_tts?ie=UTF-8&q={}&tl=th&client=tw-ob".format(
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

# ── 7. IPC: สื่อสารกับ pepper_main_py2.py ────────────────────────────────────
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

# ── 8. Audio: บันทึกและประมวลผลเสียง ─────────────────────────────────────────
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
print(f"CUDA devices: {cuda_count}  →  ใช้: {'GPU (CUDA)' if use_cuda else 'CPU'}", flush=True)
if not use_cuda:
    print("  [tip] GPU: py -3 -m pip install ctranslate2 --force-reinstall", flush=True)

_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "thonburian-large-ct2")
whisper = WhisperModel(
    _MODEL_PATH,
    device       = "cuda" if use_cuda else "cpu",
    compute_type = "float16" if use_cuda else "int8",
    cpu_threads  = 8,
    num_workers  = 2,
)
whisper.feature_extractor = FeatureExtractor(feature_size=128)
print("โหลด STT สำเร็จ!", flush=True)

p = pyaudio.PyAudio()
print("\n--- ไมโครโฟนที่พบ ---")
input_devices = []
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info["maxInputChannels"] > 0:
        input_devices.append((i, info["name"]))
        print(f"  [{len(input_devices)-1}] {info['name']}")

selected = input("\nเลือกหมายเลขไมโครโฟน (Enter = ค่าเริ่มต้น): ").strip()
if selected.isdigit() and int(selected) < len(input_devices):
    device_index = input_devices[int(selected)][0]
    print(f"ใช้: {input_devices[int(selected)][1]}")
else:
    device_index = None
    print("ใช้ค่าเริ่มต้น")

DEVICE_RATE = int(p.get_device_info_by_index(device_index)["defaultSampleRate"]) if device_index is not None \
              else int(p.get_default_input_device_info()["defaultSampleRate"])
print(f"Sample rate: {DEVICE_RATE} Hz")

stream = p.open(format=pyaudio.paInt16, channels=1, rate=DEVICE_RATE,
                input=True, input_device_index=device_index, frames_per_buffer=CHUNK)
stream.start_stream()
pre_buf = deque(maxlen=int(0.4 * DEVICE_RATE / CHUNK) + 1)  # pre-buffer 400ms
write_status("ready")
print(f"\nพร้อมฟัง  [Space]=reset busy  Ctrl+C=หยุด")
print(f"แก้ไข config.json แล้วบันทึก → มีผลทันทีในคำถามถัดไป\n")

GREETING = "สวัสดีครับ พร้อมรับคำถามแล้ว"
if download_thai_tts(GREETING):
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

        # Auto-clear history หลัง 5 นาที ไม่มีคำถาม
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
            # ถ้า loop จบเอง หรือ ข้าม busy → ลงมาที่ drain โดยตรง → ต้อง reset ด้วย
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
        print("กำลังถอดเสียง...", flush=True)
        segments, _ = whisper.transcribe(
            audio, language="th",
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
            print(f"ผู้ใช้: {text}", flush=True)
            write_query(text)
            print("Gemini กำลังคิด...", flush=True)
            t0     = time.time()
            answer = ask_gemini(text)
            print(f"ตอบ ({time.time()-t0:.1f}s): {answer}", flush=True)
            if download_thai_tts(answer):
                if pepper_up:
                    write_status("busy")
                write_command(answer)
                play_local()

except KeyboardInterrupt:
    stream.stop_stream()
    stream.close()
    p.terminate()
    print("\nหยุดแล้ว")
