from fastapi import FastAPI, UploadFile, File, HTTPException
import librosa
import tempfile
import shutil
import os
from scipy.signal import welch, wiener
import numpy as np
import uuid
import time
import json
import pika


app = FastAPI()
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"wav", "mp3", "aac", "flac", "ogg"}


# Эта функция срабатывает каждый раз, когда в очереди появляется новое сообщение
def process_message(ch, method, properties, body):
    # Превращаем текстовую строку body обратно в удобный словарь
    task_data = json.loads(body)
    
    # Дальше нейросети должны начать анализ...


def calculate_snr(audio):
    # Применяем метод Уэлча для анализа спектра
    frequencies, psd = welch(audio, fs=16000, nperseg=320)

    # Создаем маску для частот человеческого голоса
    speech_mask = (frequencies >= 300) & (frequencies <= 4000)

    # Находим суммарную мощность полезного сигнала и шума
    power_signal = psd[speech_mask].sum()
    power_noise = psd[~speech_mask].sum()

    # Защита от деления на ноль
    if power_noise == 0:
        return float('inf')

    # Считаем SNR в децибелах
    snr = 10 * np.log10(power_signal / power_noise)
    return snr


def apply_wiener_filter(audio):
    return wiener(audio)


@app.post("/api/v1/detect")
async def detect_deepfake(file: UploadFile = File(...)):
    # Проверка размера файла
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    # Проверка расширения
    ext = file.filename.split('.')[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Bad Request")

    # Создаем временный файл на диске с нужным расширением
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        file_path = temp_file.name

    # Устанавливаем соединение с локальным сервером
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
    channel = connection.channel()
    # Убеждаемся, что почтовый ящик (очередь) существует, прежде чем писать туда
    channel.queue_declare(queue='audio_processing_queue', durable=True)
    # Метаданные RabbitMQ
    message_data = {
        "request_id": str(uuid.uuid4()),  # Генерируем уникальный ID
        "client_id": "ivr_system_01",
        "timestamp": time.time(),
        "file_path": file_path,          # Путь к временному файлу
        "priority": "high"
        }
    message_body = json.dumps(message_data)
    channel.basic_publish(
        exchange='',
        routing_key='audio_processing_queue',
        body=message_body
        )
    connection.close()

    # Получение аудиофайла
    audio, sr = librosa.load(file_path, sr=16000)
    os.remove(file_path)

    # Проверка длительности аудиофайла
    duration = len(audio) / sr
    if duration < 1.0:
        raise HTTPException(status_code=400, detail="Audio duration is too short")

    # Расчет SNR
    snr_value = calculate_snr(audio)
    if snr_value < 5:
        audio = apply_wiener_filter(audio)

    return {
        "status": "accepted", 
        "request_id": message_data["request_id"]
        }
