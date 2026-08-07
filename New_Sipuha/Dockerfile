# Общий образ для бэка и воркера: код один, отличается только команда запуска.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY New_Sipuha/requirements.txt /app/requirements.txt

# torch ставим отдельно CPU-сборкой: иначе pip тянет CUDA и образ пухнет до ~4 ГБ.
RUN pip install --no-cache-dir torch torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Каталоги под общий обмен файлами, базу и метрики воркера
RUN mkdir -p /data/audio /data/db /app/New_Sipuha/core/logs
