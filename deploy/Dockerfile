# Общий образ для бэка и воркера: код один, отличается только команда запуска.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY New_Sipuha/requirements.txt /app/requirements.txt

# Версии torch фиксируем через constraints: их нельзя поднять как зависимость
# чего-либо ещё. В torchaudio 2.9+ загрузка файлов идёт только через torchcodec,
# а тот приезжает CUDA-сборкой и требует libnvrtc. У 2.4 свои бэкенды.
RUN printf 'torch==2.4.1\ntorchaudio==2.4.1\n' > /app/constraints.txt

RUN pip install --no-cache-dir -c /app/constraints.txt torch torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -c /app/constraints.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /app/requirements.txt \
 && python -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__)"

COPY . /app

# Каталоги под общий обмен файлами, базу и метрики воркера
RUN mkdir -p /data/audio /data/db /app/New_Sipuha/core/logs
