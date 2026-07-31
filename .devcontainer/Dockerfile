# Pepper Thai Speech Q&A — Linux Dev Container
# Ubuntu 20.04: Python 3.11 (listener) + system Python 2.7 (NAOqi / pepper_main)
# Ubuntu 20.04 keeps OpenSSL 1.1 so Python 2.7 / pynaoqi work reliably.
# --platform=linux/amd64 forced: this image ships amd64-only (no arm64 manifest),
# so it must run under emulation on Apple Silicon hosts.

FROM --platform=linux/amd64 mcr.microsoft.com/devcontainers/base:ubuntu-20.04

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
    alsa-utils \
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
    # Build deps for compiling Python 3.11 from source (deadsnakes dropped focal support)
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libffi-dev \
    liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11 for listener_gemini_live.py
# deadsnakes/ppa no longer publishes python3.11 for focal (20.04), so build from
# source against focal's system OpenSSL 1.1 (same lib pynaoqi/py2.7 needs).
RUN curl -sSL https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz -o /tmp/python3.11.tgz \
    && tar -xzf /tmp/python3.11.tgz -C /tmp \
    && cd /tmp/Python-3.11.9 \
    && ./configure --enable-optimizations --with-ensurepip=install \
    && make -j"$(nproc)" \
    && make altinstall \
    && cd / && rm -rf /tmp/Python-3.11.9 /tmp/python3.11.tgz

RUN update-alternatives --install /usr/bin/python3 python3 /usr/local/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/local/bin/python3.11 1 \
    && ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip3 \
    && ln -sf /usr/local/bin/pip3.11 /usr/local/bin/pip \
    && ln -sf /usr/bin/python2.7 /usr/local/bin/python2

# "audio" group so vscode can open /dev/snd when the container is started
# with --device=/dev/snd on a host that has a real sound card.
RUN groupadd -f audio && usermod -aG audio vscode

WORKDIR /workspaces/Pepper
