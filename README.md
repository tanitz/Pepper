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
├── pepper_main.py            ← Pepper controller + Tablet UI server (Python 2)
├── listener_gemini_live.py   ← STT + Gemini + TTS (Python 3)
├── naoqi_path.py             ← ค้นหา Pepper NAOqi SDK
├── pepper_ui.html            ← หน้าหลักบน Tablet
├── pepper_speak.html         ← หน้าสำรองสำหรับเล่นเสียง
├── config/                   ← config และ system prompts
├── model/                    ← Whisper CT2 model
├── SDK_pynaoqi/              ← Pepper NAOqi SDK
├── song/                     ← เพลงแยกตามภาษา/ประเทศ
├── bin/
│   ├── launchers/            ← สคริปต์ช่วยเปิดโปรแกรม
│   ├── setup/                ← สคริปต์ติดตั้งและตรวจระบบ
│   └── tools/                ← เครื่องมือทดสอบ/ดูแล repository
├── requirements*.txt         ← Python dependencies
└── run.txt                   ← สองคำสั่งหลักสำหรับรันระบบ
```

---

## Prerequisites

| รายการ | รายละเอียด |
|---|---|
| Python 3.11+ | สำหรับ `listener_gemini_live.py` |
| Python 2.7 | สำหรับ `pepper_main.py` (NAOqi SDK รองรับ Python 2 เท่านั้น) |
| Pepper robot | NAOqi 2.x, เชื่อมต่อ network เดียวกัน |
| GPU CUDA (optional) | ถ้าไม่มีจะใช้ CPU (ช้ากว่า) |
| Google Gemini API key | ฟรีที่ [aistudio.google.com](https://aistudio.google.com/app/apikey) |

---

## Setup

### 0. Check readiness (Docker / Dev Container)

```bash
make docker-check   # Docker daemon + Dev Container files
make check          # full READY / NOT READY report
make setup          # config + NAOqi SDK download
```

`make check` exits `0` only when ready to run.

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
snapshot_download('CodeHardThailand/whisper-th-large-v3-combined-ct2',
                  local_dir='model/thonburian-large-ct2')
"
```

> ขนาดประมาณ 3.1 GB

### 3. ดาวน์โหลด Pepper NAOqi SDK (Linux)

รีโปนี้ใช้ **pynaoqi Python 2.7 linux64 2.8.7.4** (ไฟล์ใหญ่ ~670 MB หลังแตก — ไม่ commit ใน git)

ดาวน์โหลดจาก [snc-iiot/nao6-doc-sdk](https://github.com/snc-iiot/nao6-doc-sdk) แล้วติดตั้งด้วยสคริปต์:

```bash
bash bin/setup/download_pynaoqi_linux.sh
```

หรือทำมือ: ดาวน์โหลด `pynaoqi-python2.7-2.8.7.4-linux64-*.tar.gz` แล้วแตกเป็น:

```
Pepper/
└── SDK_pynaoqi/
    └── linux64/
        └── lib/
            ├── libqi.so ...
            └── python2.7/site-packages/    ← _qi.so + qi module อยู่ที่นี่
```

ตรวจสอบด้วย:

```bash
python2 naoqi_path.py
```

ถ้าวาง SDK ที่อื่น ให้ตั้ง env `PYNAOQI_LIB` ชี้ไปยัง folder ที่มี `_qi.so` โดยตรง

### 4. ติดตั้ง Python 3 dependencies

```bash
pip install faster-whisper google-generativeai pyaudio pygame keyboard numpy scipy
```

สำหรับ GPU CUDA (optional) — ติดตั้งแล้วใน `.devcontainer/requirements.txt`:

```bash
pip install ctranslate2 nvidia-cublas-cu12 nvidia-cudnn-cu12
```

เมื่อรัน `listener_gemini_live.py` จะ auto-detect GPU (`CUDA devices: N → Using: GPU (CUDA)`).

**Dev Container + GPU:** host ต้องมี NVIDIA driver + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) แล้ว Rebuild Container (`runArgs: --gpus all` ใน `devcontainer.json`). ตรวจด้วย `nvidia-smi` ภายใน container.

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

### 6. ตั้งค่า IP ใน `pepper_main.py`

เปิดไฟล์และแก้ไขบรรทัด:

```python
PEPPER_IP   = "172.101.99.97"   # IP ของ Pepper robot
COMPUTER_IP = "10.1.8.88"       # IP ของ computer ที่รันโปรแกรม
```

---

## วิธีรัน

**Terminal 1** — รัน Pepper controller (Python 2):

```bash
.\.venv-py2\Scripts\python.exe .\pepper_main.py
```

**Terminal 2** — รัน Listener (Python 3):

```bash
.\.venv\Scripts\python.exe .\listener_gemini_live.py
```

หรือใช้ PowerShell script:

```powershell
.\bin\launchers\run_listener.ps1
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
