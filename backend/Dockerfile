FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HF_HUB_CACHE=/models/hub

WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime.txt requirements-rag.txt requirements-asr.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cu128 \
        "torch==2.11.0" \
    && pip install --no-cache-dir -r requirements-rag.txt \
    && pip install --no-cache-dir -r requirements-asr.txt
COPY . ./

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
