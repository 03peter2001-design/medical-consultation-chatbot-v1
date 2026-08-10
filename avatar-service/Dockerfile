FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG COSYVOICE_COMMIT=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
ARG MUSETALK_COMMIT=0a89dec45a0192b824e3cf4daf96c239440c5ed8

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HF_HOME=/models/huggingface
ENV TRANSFORMERS_CACHE=/models/huggingface
ENV PYTHONPATH=/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:/opt/MuseTalk:/app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates ffmpeg git python3.10 python3-pip python3.10-dev \
        build-essential libgl1 libglib2.0-0 libsox-dev sox \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --recursive https://github.com/QwenAudio/CosyVoice.git /opt/CosyVoice \
    && git -C /opt/CosyVoice checkout "$COSYVOICE_COMMIT" \
    && git -C /opt/CosyVoice submodule update --init --recursive \
    && git clone https://github.com/TMElyralab/MuseTalk.git /opt/MuseTalk \
    && git -C /opt/MuseTalk checkout "$MUSETALK_COMMIT" \
    && mkdir -p /app/assets \
    && cp /opt/CosyVoice/asset/zero_shot_prompt.wav /app/assets/voice-prompt.wav

WORKDIR /app
RUN python3.10 -m pip install --no-cache-dir --upgrade "pip<26" "setuptools<81" wheel \
    && python3.10 -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cu128 \
        torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
    && python3.10 -m pip install --no-cache-dir numpy==1.26.4

COPY avatar-service/requirements.txt /app/requirements.txt
RUN python3.10 -m pip install --no-cache-dir --no-deps --no-build-isolation openai-whisper==20231117 \
    && python3.10 -m pip install --no-cache-dir -r /app/requirements.txt

COPY avatar-service/app /app/app
COPY ["pic/dr training pc.png", "/app/assets/doctor.png"]

ENV PYTHONPATH=/app:/opt/CosyVoice:/opt/CosyVoice/third_party/Matcha-TTS:/opt/MuseTalk
WORKDIR /app
EXPOSE 8090
CMD ["python3.10", "-m", "uvicorn", "app.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-access-log"]
