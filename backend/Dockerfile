FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HF_HUB_CACHE=/models/hub

WORKDIR /app
COPY requirements-runtime.txt requirements-rag.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.13.0" \
    && pip install --no-cache-dir -r requirements-rag.txt
COPY . ./

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
