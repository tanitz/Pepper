# Pepper Thai Speech Q&A — SNC Former

ระบบถาม-ตอบภาษาไทยสำหรับหุ่นยนต์ Pepper ของบริษัท SNC Former

- **STT**: Thonburian Whisper CT2 (local, รองรับ GPU)
- **AI**: Google Gemini API
- **TTS**: Google Translate TTS
- **UI**: แสดงผลบน Pepper tablet (HTTP)

---

## โครงสร้างโปรเจกต์

```
Pepper/
├── listener_gemini_live.py   ← โปรแกรมหลัก 1: STT + AI + TTS (Python 3)
├── pepper_main_py2.py        ← โปรแกรมหลัก 2: Pepper robot control (Python 2)
├── config.json               ← config (copy จาก config.example.json)
├── config.example.json       ← ตัวอย่าง config
├── system_prompt.txt         ← system prompt ของ Gemini (แก้ได้ขณะรัน)
├── run_listener.ps1          ← script รัน listener (Windows PowerShell)
│
├── SDK_pynaoqi/              ← Pepper NAOqi SDK  [ดาวน์โหลดแยก ดู Setup ด้านล่าง]
│   └── pynaoqi/
│       └── lib/
│           └── qi, ...
│
└── model/                    ← STT model  [ดาวน์โหลดแยก ดู Setup ด้านล่าง]
    └── thonburian-large-ct2/
        ├── model.bin
        ├── vocabulary.json
        └── config.json
```

---

## Prerequisites

| รายการ | รายละเอียด |
|---|---|
| Python 3.11+ | สำหรับ `listener_gemini_live.py` |
| Python 2.7 | สำหรับ `pepper_main_py2.py` (NAOqi SDK รองรับ Python 2 เท่านั้น) |
| Pepper robot | NAOqi 2.x, เชื่อมต่อ network เดียวกัน |
| GPU CUDA (optional) | ถ้าไม่มีจะใช้ CPU (ช้ากว่า) |
| Google Gemini API key | ฟรีที่ [aistudio.google.com](https://aistudio.google.com/app/apikey) |

---

## Setup

### 1. Clone repo

```bash
git clone https://github.com/tanitz/Pepper.git
cd Pepper
```

### 2. ดาวน์โหลด Thonburian Whisper model

ดาวน์โหลด `thonburian-large-ct2` จาก HuggingFace แล้ววางไว้ที่ `model/thonburian-large-ct2/`

```bash
pip install huggingface_hub
python -c "
from huggingface_hub import snapshot_download
snapshot_download('biodatlab/whisper-th-large-v3-combined',
                  local_dir='model/thonburian-large-ct2')
"
```

> ขนาดประมาณ 1.6 GB

### 3. ดาวน์โหลด Pepper NAOqi SDK

SDK เป็น binary เฉพาะแพลตฟอร์ม — ต้องใช้ build ให้ตรงกับเครื่องที่รัน `pepper_main.py`
โดยดาวน์โหลดจาก [SoftBank Robotics Developer Center](https://developer.softbankrobotics.com/pepper-naoqi-25/downloads/pepper-naoqi-25-downloads-linux-mac-and-windows)

**Linux / Dev Container** (build ที่ commit ไว้ในรีโปเป็นของ Windows ใช้บน Linux ไม่ได้)

1. ดาวน์โหลด `pynaoqi-python2.7-2.8.7.4-linux64-*.tar.gz`
2. แตกไฟล์แล้ว rename folder เป็น `linux64` วางไว้ใต้ `SDK_pynaoqi/` ให้ได้โครงสร้าง:

```
Pepper/
└── SDK_pynaoqi/
    └── linux64/
        └── lib/
            ├── libqi.so ...
            └── python2.7/site-packages/    ← _qi.so + qi module อยู่ที่นี่
```

**Windows**

1. ดาวน์โหลด `pynaoqi-python2.7-2.8.7.4-win64-vs2015.zip`
2. แตกไฟล์แล้ววางให้ได้โครงสร้าง `SDK_pynaoqi/pynaoqi/lib/` (ต้องมี `_qi.pyd`)

`naoqi_path.py` จะเลือก path ให้อัตโนมัติตาม OS หากวางไว้ที่อื่น ให้ตั้ง env `PYNAOQI_LIB`
ชี้ไปยัง folder ที่มี `_qi.so` / `_qi.pyd` โดยตรง ตรวจสอบด้วย:

```bash
python2 naoqi_path.py
```

### 4. ติดตั้ง Python 3 dependencies

```bash
pip install faster-whisper google-generativeai pyaudio pygame keyboard numpy scipy
```

สำหรับ GPU CUDA (optional):

```bash
pip install ctranslate2
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

### 5. ตั้งค่า config

```bash
copy config.example.json config.json
```

แก้ไข `config.json`:

```json
{
  "gemini_api_key": "ใส่ API key ของคุณที่นี่",
  ...
}
```

### 6. ตั้งค่า IP ใน `pepper_main_py2.py`

เปิดไฟล์และแก้ไขบรรทัด:

```python
PEPPER_IP   = "172.101.99.97"   # IP ของ Pepper robot
COMPUTER_IP = "10.1.8.88"       # IP ของ computer ที่รันโปรแกรม
```

---

## วิธีรัน

**Terminal 1** — รัน Pepper controller (Python 2):

```bash
python2 pepper_main_py2.py
```

**Terminal 2** — รัน Listener (Python 3):

```bash
python listener_gemini_live.py
```

หรือใช้ PowerShell script:

```powershell
.\run_listener.ps1
```

---

## การทำงาน

```
ผู้ใช้พูด
    → listener ตรวจจับเสียง (RMS threshold)
    → Thonburian Whisper ถอดเสียงเป็นข้อความ
    → Google Gemini ตอบ
    → Google TTS สร้าง speech.mp3
    → pepper_main เล่นเสียง + ขยับท่าทาง + แสดงข้อความบน tablet
    → กลับไปรอฟังใหม่
```

## การควบคุม

| ปุ่ม | ผล |
|---|---|
| `Space` | รีเซ็ต busy state + ล้างประวัติการสนทนา |
| `Ctrl+C` | หยุด listener |

## Hot-reload config

แก้ไข `config.json` หรือ `system_prompt.txt` แล้วบันทึก → มีผลทันทีในคำถามถัดไป ไม่ต้อง restart

---

## Network

| Host | Port | ใช้ทำอะไร |
|---|---|---|
| Computer | 8080 | HTTP server ให้ Pepper tablet เชื่อมต่อ |
| Pepper | 9559 | NAOqi framework port |
