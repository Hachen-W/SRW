import os
import sys
import uuid
import time
import json
import pika
import redis
import tempfile
import numpy as np
import scipy.io.wavfile as wavfile
from datasets import load_dataset, Audio

# СНАЧАЛА учим Python видеть корень проекта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.metrics import MetricsLogger

# Настройки инфраструктуры
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
RABBIT_HOST = "localhost"
QUEUE_NAME = "audio_processing_queue"

print("[*] Подключение к RabbitMQ и Redis...")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST))
channel = connection.channel()
channel.queue_declare(queue=QUEUE_NAME, durable=True)

# Создаем логгер для замера сквозного системного E2E
logger = MetricsLogger(log_file='network_benchmark_log.csv', batch_size=10)

print("[*] Подключение к датасету...")
dataset = load_dataset("kijjjj/audio_data_russian", split="train", streaming=True)
dataset = dataset.cast_column("audio", Audio(sampling_rate=16000))

print("[*] Запуск интеграционного хронометража...")
for i, sample in enumerate(dataset.take(20)):
    req_id = str(uuid.uuid4())
    audio_array = sample["audio"]["array"]
    duration = len(audio_array) / 16000.0
    text_preview = sample['text'][:30] if sample['text'] else "Без текста"

    print(f"Отправка трека {i+1}: '{text_preview}...' (Спикер: {sample['speaker_name']})")

    try:
        # 1. Сохраняем аудио во временный файл (так как воркер ожидает file_path)
        # Файл закроется сразу после блока with, но останется на диске. 
        # Наш универсальный worker.py сам удалит его в своем блоке finally!
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wavfile.write(tf.name, 16000, audio_array.astype(np.float32))
            temp_file_path = tf.name

        # Стартуем таймер полного системного E2E
        full_system_start = time.perf_counter()

        # 2. Формируем тело задачи и отправляем в RabbitMQ
        task_payload = {
            "file_path": temp_file_path,
            "request_id": req_id
        }
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=json.dumps(task_payload),
            properties=pika.BasicProperties(delivery_mode=2)  # Делаем сообщение персистентным
        )

        # 3. Опрашиваем Redis в ожидании ответа от воркера
        print(f"   [~] Ожидание ответа из Redis для ID: {req_id}...", end="", flush=True)
        while True:
            result_raw = redis_client.get(req_id)
            if result_raw:
                result = json.loads(result_raw)
                break
            time.sleep(0.01)  # Спим 10 миллисекунд, чтобы не вешать процессор частыми запросами

        full_system_time = time.perf_counter() - full_system_start
        print(f"\r   [+] Результат получен за {full_system_time:.4f}с. Вердикт: {result.get('verdict')}")
        
        # Логируем полное время прохождения через сеть и очереди
        logger.log_timing(req_id, 'full_system_network_e2e', duration, full_system_time)

    except Exception as e:
        print(f"\n[!] Ошибка при обработке индекса {i}: {e}")

# Принудительно сохраняем остатки буфера в CSV и закрываем соединение
logger.flush()
connection.close()
print("[+] Интеграционный прогон завершен! Данные записаны в network_benchmark_log.csv")
