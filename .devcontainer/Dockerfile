# Pepper Thai Speech Q&A — Linux Dev Container
# Ubuntu 20.04: Python 3.11 (listener) + system Python 2.7 (NAOqi / pepper_main)
# Ubuntu 20.04 keeps OpenSSL 1.1 so Python 2.7 / pynaoqi work reliably.

FROM mcr.microsoft.com/devcontainers/base:ubuntu-20.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    curl \
    wget \
    git \
    build-essential \
    pkg-config \
    # Audio / SDL (pyaudio, pygame)
    portaudio19-dev \
    libasound2-dev \
    libportmidi-dev \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-mixer-dev \
    libsdl2-ttf-dev \
    libfreetype6-dev \
    ffmpeg \
    # Python 2.7 for pepper_main.py + Linux pynaoqi
    python2.7 \
    python2.7-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11 for listener_gemini_live.py
RUN add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3.11-distutils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3 \
    && ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip \
    && ln -sf /usr/bin/python2.7 /usr/local/bin/python2

WORKDIR /workspaces/Pepper
